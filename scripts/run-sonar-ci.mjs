import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import {
  SCANNER_OUTCOME,
  ScannerGateError,
  classifyCommandResult,
  configurationError,
  findingError,
  runBoundedCommand,
  sanitizeScannerText,
  unavailableError,
  writeUnavailableReport,
} from './scanner-gate-policy.mjs';
import { parseScopeArgs, runSonarOpenFindings } from './sonar-open-findings.mjs';
import { runSonarQualityGate } from './sonar-quality-gate.mjs';
import { runSonarReviewedIssues } from './sonar-reviewed-issues.mjs';

const COMMAND_TIMEOUT_MS = 600_000;
const AGGREGATE_TIMEOUT_MS = 1_080_000;
const API_PHASE_TIMEOUT_MS = 300_000;
const REQUEST_TIMEOUT_MS = 30_000;
const ISSUE_SETTLE_ATTEMPTS = 3;
const ISSUE_SETTLE_INTERVAL_MS = 2_000;
const MAX_OUTPUT_BYTES = 32_768;
const SAFE_ORGANIZATION = /^[A-Za-z0-9._-]{1,200}$/u;
const SONAR_UPLOAD_POLICY = Object.freeze({
  findingExitCodes: [],
  unavailableExitCodes: [],
  configurationExitCodes: [],
  transientOutput:
    /(?:HTTP\s+(?:429|5\d\d)|ETIMEDOUT|ECONNRESET|EAI_AGAIN|ENOTFOUND|socket hang up|temporarily unavailable|service unavailable)/iu,
});
const monotonicNow = () => performance.now();

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function validateHostUrl(value) {
  if (!nonEmptyString(value)) return;
  let url;
  try {
    url = new URL(value);
  } catch {
    throw configurationError('SONAR_HOST_URL must be a valid HTTPS URL.');
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw configurationError('SONAR_HOST_URL must be a credential-free HTTPS URL.');
  }
}

function validateConfiguration(argv, env) {
  if (!env || typeof env !== 'object' || Array.isArray(env)) {
    throw configurationError('Sonar environment configuration is invalid.');
  }
  if (!nonEmptyString(env.SONAR_TOKEN)) {
    throw configurationError('SONAR_TOKEN is required.');
  }
  if (!nonEmptyString(env.SONAR_ORGANIZATION) || !SAFE_ORGANIZATION.test(env.SONAR_ORGANIZATION)) {
    throw configurationError('SONAR_ORGANIZATION is required and must be a valid identifier.');
  }
  validateHostUrl(env.SONAR_HOST_URL);

  let scope;
  try {
    scope = parseScopeArgs(argv);
  } catch (error) {
    throw configurationError(error instanceof Error ? error.message : 'Sonar scope is invalid.', {
      cause: error,
    });
  }
  if ('branch' in scope && scope.branch !== 'main') {
    throw configurationError('The Sonar CI branch scope must be main.');
  }
  return scope;
}

function scopeArgument(scope) {
  return 'branch' in scope ? `--branch=${scope.branch}` : `--pull-request=${scope.pullRequest}`;
}

function scannerCommand(env, timeoutMs) {
  return {
    file: process.platform === 'win32' ? 'sonar-scanner-npm.cmd' : 'sonar-scanner-npm',
    args: [
      `-Dsonar.organization=${env.SONAR_ORGANIZATION}`,
      '-Dsonar.qualitygate.wait=false',
      ...(nonEmptyString(env.SONAR_HOST_URL) ? [`-Dsonar.host.url=${env.SONAR_HOST_URL}`] : []),
    ],
    env,
    timeoutMs,
    maxOutputBytes: MAX_OUTPUT_BYTES,
    transientOutput: SONAR_UPLOAD_POLICY.transientOutput,
  };
}

function phaseTimeout(deadline, now, label, maximum = AGGREGATE_TIMEOUT_MS) {
  const remaining = Math.floor(deadline - now());
  if (remaining <= 0) throw unavailableError(`Sonar ${label} exceeded the aggregate deadline.`);
  return Math.min(maximum, remaining);
}

function validateOpenIssueResult(result) {
  if (!Array.isArray(result?.summary?.open)) {
    throw configurationError('Sonar returned an invalid open-issue summary.');
  }
  if (result.summary.open.length > 0) {
    const visible = result.summary.open.slice(0, 20).join(', ');
    const remainder = result.summary.open.length > 20 ? ' and additional findings' : '';
    throw findingError(`Sonar reported open or confirmed issues: ${visible}${remainder}.`);
  }
}

async function waitForSettledIssues({ deadline, now, readIssues, scopedArgument, env, sleep }) {
  for (let attempt = 0; attempt < ISSUE_SETTLE_ATTEMPTS; attempt += 1) {
    const timeoutMs = phaseTimeout(deadline, now, 'open-issue inspection');
    const issues = await readIssues({
      argv: [scopedArgument],
      env,
      timeoutMs,
      requestTimeoutMs: Math.min(REQUEST_TIMEOUT_MS, timeoutMs),
    });
    validateOpenIssueResult(issues);
    if (attempt === ISSUE_SETTLE_ATTEMPTS - 1) return;
    await sleep(phaseTimeout(deadline, now, 'issue-index settling', ISSUE_SETTLE_INTERVAL_MS));
  }
}

function unavailableReason(error, env) {
  const message = error instanceof Error ? error.message : 'Temporary Sonar availability failure.';
  return sanitizeScannerText(message, env);
}

export async function runSonarCi({
  argv = process.argv.slice(2),
  env = process.env,
  runCommand = runBoundedCommand,
  waitAnalysis = runSonarQualityGate,
  reconcile = runSonarReviewedIssues,
  readIssues = runSonarOpenFindings,
  checkGate = runSonarQualityGate,
  reportUnavailable = writeUnavailableReport,
  now = monotonicNow,
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
} = {}) {
  try {
    if (typeof now !== 'function') throw configurationError('Sonar CI timing function is invalid.');
    if (typeof sleep !== 'function') {
      throw configurationError('Sonar CI sleep function is invalid.');
    }
    const scope = validateConfiguration(argv, env);
    const deadline = now() + AGGREGATE_TIMEOUT_MS;
    const scopedArgument = scopeArgument(scope);
    const upload = await runCommand(
      scannerCommand(env, phaseTimeout(deadline, now, 'upload', COMMAND_TIMEOUT_MS)),
    );
    const uploadOutcome = classifyCommandResult(upload, SONAR_UPLOAD_POLICY);
    if (uploadOutcome === SCANNER_OUTCOME.UNAVAILABLE) {
      throw new ScannerGateError(
        SCANNER_OUTCOME.UNAVAILABLE,
        upload.timedOut
          ? 'Sonar upload exceeded its bounded deadline.'
          : 'Sonar upload encountered a temporary service or network failure.',
      );
    }
    if (uploadOutcome !== SCANNER_OUTCOME.CLEAN) {
      throw configurationError('Sonar upload failed without a confirmed scanner finding.');
    }

    await waitAnalysis({
      argv: ['wait-analysis', scopedArgument],
      env,
      timeoutMs: phaseTimeout(deadline, now, 'analysis wait', API_PHASE_TIMEOUT_MS),
    });
    if ('branch' in scope) {
      const timeoutMs = phaseTimeout(deadline, now, 'reviewed-issue reconciliation');
      await reconcile({
        argv: ['--branch=main', '--apply'],
        env,
        timeoutMs,
        requestTimeoutMs: Math.min(REQUEST_TIMEOUT_MS, timeoutMs),
      });
    }
    await waitForSettledIssues({
      deadline,
      now,
      readIssues,
      scopedArgument,
      env,
      sleep,
    });
    await checkGate({
      argv: ['check-quality-gate', scopedArgument],
      env,
      timeoutMs: phaseTimeout(deadline, now, 'quality gate', API_PHASE_TIMEOUT_MS),
    });
    return { outcome: SCANNER_OUTCOME.CLEAN, scope };
  } catch (error) {
    if (error instanceof ScannerGateError) {
      if (error.outcome !== SCANNER_OUTCOME.UNAVAILABLE) throw error;
      const reason = unavailableReason(error, env);
      reportUnavailable({
        scanner: 'Sonar',
        reason,
        revision: env?.GITHUB_SHA,
        env,
      });
      return { outcome: SCANNER_OUTCOME.UNAVAILABLE, reason };
    }
    throw configurationError(
      sanitizeScannerText(
        error instanceof Error ? error.message : 'Unknown Sonar CI gate failure.',
        env,
      ),
      { cause: error },
    );
  }
}

async function main() {
  try {
    await runSonarCi();
  } catch (error) {
    const safe = sanitizeScannerText(
      error instanceof Error ? error.message : 'Unknown Sonar CI gate failure.',
      process.env,
    );
    process.stderr.write(`Sonar CI gate failed: ${safe}\n`);
    process.exitCode =
      error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING ? 1 : 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
