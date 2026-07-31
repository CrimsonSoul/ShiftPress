import { readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { pathToFileURL } from 'node:url';
import { classifyHttpFailure, findingError, unavailableError } from './scanner-gate-policy.mjs';
import { parseProjectKey, parseScopeArgs } from './sonar-open-findings.mjs';

const DEFAULT_SONAR_HOST_URL = 'https://sonarcloud.io';
const DEFAULT_TIMEOUT_MS = 300_000;
const DEFAULT_POLL_INTERVAL_MS = 2_000;
const MAX_REQUEST_TIMEOUT_MS = 30_000;
const MAX_TIMEOUT_MS = 600_000;
const SAFE_IDENTIFIER_PATTERN = /^[A-Za-z0-9._:-]{1,400}$/u;
const SAFE_TASK_IDENTIFIER_PATTERN = /^[A-Za-z0-9_-]{1,160}$/u;
const ACTIONS = new Set(['wait-analysis', 'check-quality-gate']);
const COMPUTE_STATUSES = new Set(['PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILED', 'CANCELED']);
const BRANCH_TASK_TYPES = new Set(['BRANCH', 'LONG', 'SHORT']);
const QUALITY_GATE_STATUSES = new Set(['OK', 'WARN', 'ERROR', 'NONE']);
const monotonicNow = () => performance.now();

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function validateIdentifier(value, label, pattern = SAFE_IDENTIFIER_PATTERN) {
  if (!nonEmptyString(value) || !pattern.test(value)) {
    throw new Error(`${label} is invalid.`);
  }
  return value;
}

function normalizeSonarHostUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error('SONAR_HOST_URL must be a valid HTTPS URL.');
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('SONAR_HOST_URL must be a credential-free HTTPS base URL.');
  }
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url;
}

function parseKeyValueFile(contents, label) {
  if (typeof contents !== 'string') throw new TypeError(`${label} must be readable text.`);
  const values = new Map();
  for (const line of contents.split(/\r?\n/u)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const separator = trimmed.indexOf('=');
    if (separator <= 0) throw new Error(`${label} contains a malformed entry.`);
    const key = trimmed.slice(0, separator).trim();
    const value = trimmed.slice(separator + 1).trim();
    if (values.has(key)) throw new Error(`${label} contains a duplicate ${key} entry.`);
    values.set(key, value);
  }
  return values;
}

function requiredValue(values, key, label) {
  const value = values.get(key);
  if (!nonEmptyString(value)) throw new Error(`${label} must define ${key}.`);
  return value;
}

function validateScope(scope) {
  if (scope && typeof scope === 'object' && !Array.isArray(scope)) {
    if (Object.keys(scope).length === 1 && typeof scope.branch === 'string') {
      return parseScopeArgs([`--branch=${scope.branch}`]);
    }
    if (Object.keys(scope).length === 1 && typeof scope.pullRequest === 'string') {
      return parseScopeArgs([`--pull-request=${scope.pullRequest}`]);
    }
  }
  throw new Error('Specify exactly one --branch or --pull-request scope.');
}

function scopeLabel(scope) {
  return 'branch' in scope ? `branch ${scope.branch}` : `pull request ${scope.pullRequest}`;
}

function validateTiming(timeoutMs, pollIntervalMs) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error('Sonar gate timeout must be between 1 and 600000 milliseconds.');
  }
  if (!Number.isSafeInteger(pollIntervalMs) || pollIntervalMs < 1 || pollIntervalMs > timeoutMs) {
    throw new Error('Sonar poll interval must be bounded by the gate timeout.');
  }
}

export function parseSonarGateArgs(argv) {
  if (!Array.isArray(argv) || !nonEmptyString(argv[0]) || !ACTIONS.has(argv[0])) {
    throw new Error('Specify a Sonar gate action: wait-analysis or check-quality-gate.');
  }
  return {
    action: argv[0],
    scope: parseScopeArgs(argv.slice(1)),
  };
}

export function parseReportTask({ report, configuredHostUrl, expectedProjectKey }) {
  const configuredBase = normalizeSonarHostUrl(configuredHostUrl);
  const values = parseKeyValueFile(report, 'Sonar scanner report');
  const projectKey = validateIdentifier(
    requiredValue(values, 'projectKey', 'Sonar scanner report'),
    'Sonar scanner project key',
  );
  if (projectKey !== expectedProjectKey) {
    throw new Error('Sonar scanner report project key does not match the configured project.');
  }

  const reportBase = normalizeSonarHostUrl(
    requiredValue(values, 'serverUrl', 'Sonar scanner report'),
  );
  if (reportBase.href !== configuredBase.href) {
    throw new Error('Sonar scanner report does not match the configured Sonar host.');
  }

  const ceTaskId = validateIdentifier(
    requiredValue(values, 'ceTaskId', 'Sonar scanner report'),
    'Sonar compute task identifier',
    SAFE_TASK_IDENTIFIER_PATTERN,
  );
  const expectedTaskUrl = new URL('api/ce/task', reportBase);
  expectedTaskUrl.searchParams.set('id', ceTaskId);
  const reportedTaskUrl = requiredValue(values, 'ceTaskUrl', 'Sonar scanner report');
  let parsedTaskUrl;
  try {
    parsedTaskUrl = new URL(reportedTaskUrl);
  } catch {
    throw new Error('Sonar scanner report task URL is invalid.');
  }
  if (parsedTaskUrl.href !== expectedTaskUrl.href) {
    throw new Error('Sonar scanner report task URL does not match its compute task.');
  }

  return {
    ceTaskId,
    projectKey,
    serverUrl: reportBase.href,
  };
}

async function requestJson({ fetcher, url, token, timeoutMs }) {
  let response;
  try {
    response = await fetcher(url, {
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
      signal: AbortSignal.timeout(
        Math.max(1, Math.floor(Math.min(timeoutMs, MAX_REQUEST_TIMEOUT_MS))),
      ),
    });
  } catch (error) {
    throw unavailableError('Sonar API request failed before receiving a response.', {
      cause: error,
    });
  }
  if (!response?.ok) {
    throw classifyHttpFailure('Sonar API', response?.status);
  }
  try {
    return await response.json();
  } catch {
    throw new Error('Sonar returned invalid JSON.');
  }
}

function validateComputeTask(payload, { taskId, projectKey, scope }) {
  if (
    payload === null ||
    typeof payload !== 'object' ||
    Array.isArray(payload) ||
    payload.task === null ||
    typeof payload.task !== 'object' ||
    Array.isArray(payload.task)
  ) {
    throw new Error('Sonar returned an invalid compute task response.');
  }
  const task = payload.task;
  if (
    task.id !== taskId ||
    !nonEmptyString(task.componentKey) ||
    !COMPUTE_STATUSES.has(task.status)
  ) {
    throw new Error('Sonar returned an invalid compute task response.');
  }
  if (task.componentKey !== projectKey) {
    throw new Error('Sonar compute task belongs to a different project.');
  }
  if ('branch' in scope) {
    if (!BRANCH_TASK_TYPES.has(task.branchType) || task.branch !== scope.branch) {
      throw new Error('Sonar compute task belongs to a different branch.');
    }
  } else {
    const hasBranchIdentity = task.branch !== undefined || task.branchType !== undefined;
    if (hasBranchIdentity || task.pullRequest !== scope.pullRequest) {
      throw new Error('Sonar compute task belongs to a different pull request.');
    }
  }
  if (task.status === 'SUCCESS') {
    validateIdentifier(task.analysisId, 'Sonar analysis identifier', SAFE_TASK_IDENTIFIER_PATTERN);
  }
  return task;
}

export async function waitForComputeTask({
  fetcher = globalThis.fetch,
  serverUrl,
  taskId,
  projectKey,
  scope,
  token,
  now = monotonicNow,
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  timeoutMs = DEFAULT_TIMEOUT_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}) {
  if (typeof fetcher !== 'function') throw new Error('A Fetch implementation is required.');
  if (typeof now !== 'function' || typeof sleep !== 'function') {
    throw new TypeError('Sonar gate timing functions are required.');
  }
  if (!nonEmptyString(token)) throw new Error('SONAR_TOKEN is required.');
  validateIdentifier(taskId, 'Sonar compute task identifier', SAFE_TASK_IDENTIFIER_PATTERN);
  validateIdentifier(projectKey, 'Sonar project key');
  const validatedScope = validateScope(scope);
  validateTiming(timeoutMs, pollIntervalMs);
  const base = normalizeSonarHostUrl(serverUrl);
  const taskUrl = new URL('api/ce/task', base);
  taskUrl.searchParams.set('id', taskId);
  const deadline = now() + timeoutMs;
  let firstRequest = true;

  while (true) {
    const remainingBeforeRequest = deadline - now();
    if (!firstRequest && remainingBeforeRequest <= 0) {
      throw unavailableError(`Sonar compute task timed out for ${scopeLabel(validatedScope)}.`);
    }
    firstRequest = false;
    const payload = await requestJson({
      fetcher,
      url: taskUrl,
      token,
      timeoutMs: Math.max(1, remainingBeforeRequest),
    });
    const task = validateComputeTask(payload, {
      taskId,
      projectKey,
      scope: validatedScope,
    });
    if (task.status === 'SUCCESS') {
      return { analysisId: task.analysisId, taskId: task.id };
    }
    if (task.status === 'FAILED' || task.status === 'CANCELED') {
      throw new Error(`Sonar compute task finished with status ${task.status}.`);
    }

    const remaining = deadline - now();
    if (remaining <= 0) {
      throw unavailableError(`Sonar compute task timed out for ${scopeLabel(validatedScope)}.`);
    }
    await sleep(Math.min(pollIntervalMs, remaining));
  }
}

function validateQualityGate(payload) {
  if (
    payload === null ||
    typeof payload !== 'object' ||
    Array.isArray(payload) ||
    payload.projectStatus === null ||
    typeof payload.projectStatus !== 'object' ||
    Array.isArray(payload.projectStatus) ||
    !QUALITY_GATE_STATUSES.has(payload.projectStatus.status)
  ) {
    throw new Error('Sonar returned an invalid quality gate response.');
  }
  return payload.projectStatus;
}

function validateLatestBranchAnalysis(payload, expectedAnalysisId, scope) {
  if (
    payload === null ||
    typeof payload !== 'object' ||
    Array.isArray(payload) ||
    payload.paging === null ||
    typeof payload.paging !== 'object' ||
    Array.isArray(payload.paging) ||
    payload.paging.pageIndex !== 1 ||
    payload.paging.pageSize !== 1 ||
    !Number.isSafeInteger(payload.paging.total) ||
    payload.paging.total < 1 ||
    !Array.isArray(payload.analyses) ||
    payload.analyses.length !== 1 ||
    payload.analyses[0] === null ||
    typeof payload.analyses[0] !== 'object' ||
    Array.isArray(payload.analyses[0]) ||
    !SAFE_TASK_IDENTIFIER_PATTERN.test(payload.analyses[0].key)
  ) {
    throw new Error('Sonar returned an invalid latest-analysis response.');
  }
  if (payload.analyses[0].key !== expectedAnalysisId) {
    throw new Error(`Sonar analysis is no longer the latest for ${scopeLabel(scope)}.`);
  }
}

function remainingGateTime(deadline, now, scope) {
  const remaining = deadline - now();
  if (remaining <= 0) {
    throw unavailableError(`Sonar quality gate timed out for ${scopeLabel(scope)}.`);
  }
  return remaining;
}

async function assertLatestBranchAnalysis({
  fetcher,
  latestAnalysisUrl,
  analysisId,
  scope,
  token,
  deadline,
  now,
}) {
  const payload = await requestJson({
    fetcher,
    url: latestAnalysisUrl,
    token,
    timeoutMs: remainingGateTime(deadline, now, scope),
  });
  validateLatestBranchAnalysis(payload, analysisId, scope);
}

async function waitForBranchQualityGate({
  fetcher,
  statusUrl,
  latestAnalysisUrl,
  analysisId,
  scope,
  token,
  now,
  sleep,
  timeoutMs,
  pollIntervalMs,
}) {
  const deadline = now() + timeoutMs;
  let lastStatus;
  const assertLatest = () =>
    assertLatestBranchAnalysis({
      fetcher,
      latestAnalysisUrl,
      analysisId,
      scope,
      token,
      deadline,
      now,
    });

  while (true) {
    if (lastStatus === 'ERROR' && deadline - now() <= 0) {
      throw findingError(`Sonar quality gate failed for ${scopeLabel(scope)} with status ERROR.`);
    }
    await assertLatest();
    const payload = await requestJson({
      fetcher,
      url: statusUrl,
      token,
      timeoutMs: remainingGateTime(deadline, now, scope),
    });
    const projectStatus = validateQualityGate(payload);
    if (projectStatus.status === 'OK') {
      await assertLatest();
      return projectStatus;
    }
    if (projectStatus.status !== 'ERROR') {
      throw findingError(
        `Sonar quality gate failed for ${scopeLabel(scope)} with status ${projectStatus.status}.`,
      );
    }
    lastStatus = projectStatus.status;
    const remaining = deadline - now();
    if (remaining <= 0) {
      throw findingError(`Sonar quality gate failed for ${scopeLabel(scope)} with status ERROR.`);
    }
    await sleep(Math.min(pollIntervalMs, remaining));
  }
}

async function checkPullRequestQualityGate({ fetcher, statusUrl, scope, token, timeoutMs }) {
  const payload = await requestJson({
    fetcher,
    url: statusUrl,
    token,
    timeoutMs,
  });
  const projectStatus = validateQualityGate(payload);
  if (projectStatus.status !== 'OK') {
    throw findingError(
      `Sonar quality gate failed for ${scopeLabel(scope)} with status ${projectStatus.status}.`,
    );
  }
  return projectStatus;
}

export async function waitForQualityGate({
  fetcher = globalThis.fetch,
  serverUrl,
  analysisId,
  projectKey,
  scope,
  token,
  now = monotonicNow,
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  timeoutMs = DEFAULT_TIMEOUT_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}) {
  if (typeof fetcher !== 'function') throw new Error('A Fetch implementation is required.');
  if (typeof now !== 'function' || typeof sleep !== 'function') {
    throw new TypeError('Sonar gate timing functions are required.');
  }
  if (!nonEmptyString(token)) throw new Error('SONAR_TOKEN is required.');
  validateIdentifier(analysisId, 'Sonar analysis identifier', SAFE_TASK_IDENTIFIER_PATTERN);
  const validatedScope = validateScope(scope);
  validateTiming(timeoutMs, pollIntervalMs);
  const base = normalizeSonarHostUrl(serverUrl);
  const statusUrl = new URL('api/qualitygates/project_status', base);
  if ('pullRequest' in validatedScope) {
    statusUrl.searchParams.set('analysisId', analysisId);
    return checkPullRequestQualityGate({
      fetcher,
      statusUrl,
      scope: validatedScope,
      token,
      timeoutMs,
    });
  }

  validateIdentifier(projectKey, 'Sonar project key');
  const latestAnalysisUrl = new URL('api/project_analyses/search', base);
  latestAnalysisUrl.searchParams.set('project', projectKey);
  latestAnalysisUrl.searchParams.set('branch', validatedScope.branch);
  latestAnalysisUrl.searchParams.set('p', '1');
  latestAnalysisUrl.searchParams.set('ps', '1');
  statusUrl.searchParams.set('projectKey', projectKey);
  statusUrl.searchParams.set('branch', validatedScope.branch);
  return waitForBranchQualityGate({
    fetcher,
    statusUrl,
    latestAnalysisUrl,
    analysisId,
    scope: validatedScope,
    token,
    now,
    sleep,
    timeoutMs,
    pollIntervalMs,
  });
}

export async function runSonarQualityGate({
  argv = process.argv.slice(2),
  env = process.env,
  fetcher = globalThis.fetch,
  readProjectProperties = () =>
    readFileSync(new URL('../sonar-project.properties', import.meta.url), 'utf8'),
  readReportTask = () =>
    readFileSync(new URL('../.scannerwork/report-task.txt', import.meta.url), 'utf8'),
  write = (line) => process.stdout.write(`${line}\n`),
  now = monotonicNow,
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  timeoutMs = DEFAULT_TIMEOUT_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
} = {}) {
  const token = env.SONAR_TOKEN;
  if (!nonEmptyString(token)) throw new Error('SONAR_TOKEN is required.');
  if (typeof now !== 'function') throw new TypeError('Sonar gate timing function is required.');
  validateTiming(timeoutMs, pollIntervalMs);
  const deadline = now() + timeoutMs;
  const remainingTimeout = () => {
    const remaining = Math.floor(deadline - now());
    if (remaining <= 0) throw unavailableError('Sonar quality-gate workflow timed out.');
    return remaining;
  };
  const { action, scope } = parseSonarGateArgs(argv);
  const expectedProjectKey = parseProjectKey(readProjectProperties());
  validateIdentifier(expectedProjectKey, 'Sonar project key');
  const report = parseReportTask({
    report: readReportTask(),
    configuredHostUrl: env.SONAR_HOST_URL || DEFAULT_SONAR_HOST_URL,
    expectedProjectKey,
  });
  const computeTimeoutMs = remainingTimeout();
  const task = await waitForComputeTask({
    fetcher,
    serverUrl: report.serverUrl,
    taskId: report.ceTaskId,
    projectKey: report.projectKey,
    scope,
    token,
    now,
    sleep,
    timeoutMs: computeTimeoutMs,
    pollIntervalMs: Math.min(pollIntervalMs, computeTimeoutMs),
  });

  if (action === 'wait-analysis') {
    write(`Sonar analysis ${task.analysisId} completed for ${scopeLabel(scope)}.`);
    return { ...task, scope };
  }

  const qualityTimeoutMs = remainingTimeout();
  const qualityGate = await waitForQualityGate({
    fetcher,
    serverUrl: report.serverUrl,
    analysisId: task.analysisId,
    projectKey: report.projectKey,
    scope,
    token,
    now,
    sleep,
    timeoutMs: qualityTimeoutMs,
    pollIntervalMs: Math.min(pollIntervalMs, qualityTimeoutMs),
  });
  write(`Sonar quality gate passed for ${scopeLabel(scope)} (analysis ${task.analysisId}).`);
  return { ...task, qualityGate, scope };
}

function safeMessage(error, token) {
  const message = error instanceof Error ? error.message : 'Unknown Sonar quality gate failure.';
  return token ? message.replaceAll(token, '[REDACTED]') : message;
}

async function main() {
  try {
    await runSonarQualityGate();
  } catch (error) {
    process.stderr.write(
      `Sonar quality gate check failed: ${safeMessage(error, process.env.SONAR_TOKEN)}\n`,
    );
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
