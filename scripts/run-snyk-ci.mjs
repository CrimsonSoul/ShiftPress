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

const COMMAND_TIMEOUT_MS = 600_000;
const AGGREGATE_TIMEOUT_MS = 1_080_000;
const MAX_OUTPUT_BYTES = 32_768;
const SAFE_IDENTIFIER = /^[A-Za-z0-9._-]{1,200}$/u;
const SAFE_REPOSITORY = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/u;
const TRANSIENT_OUTPUT =
  /(?:HTTP\s+(?:429|5\d\d)|ETIMEDOUT|ECONNRESET|EAI_AGAIN|ENOTFOUND|socket hang up|temporarily unavailable|service unavailable|maintenance window)/iu;
// Snyk exit 2 is a generic failure: it is Unavailable only with positive transient evidence.
// Exit 3 (no supported project) and 77 (no permission) are always configuration failures.
const SCAN_POLICY = Object.freeze({
  findingExitCodes: [1],
  unavailableExitCodes: [69, 75],
  configurationExitCodes: [3, 77],
  transientOutput: TRANSIENT_OUTPUT,
});
const MONITOR_POLICY = Object.freeze({
  findingExitCodes: [],
  unavailableExitCodes: [69, 75],
  configurationExitCodes: [1, 3, 77],
  transientOutput: TRANSIENT_OUTPUT,
});
const monotonicNow = () => performance.now();

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function validateServerUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw configurationError('GITHUB_SERVER_URL must be a valid HTTPS URL.');
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw configurationError('GITHUB_SERVER_URL must be a credential-free HTTPS URL.');
  }
  return url.href.replace(/\/$/u, '');
}

function validateConfiguration(env) {
  if (!env || typeof env !== 'object' || Array.isArray(env)) {
    throw configurationError('Snyk environment configuration is invalid.');
  }
  if (!nonEmptyString(env.SNYK_TOKEN)) throw configurationError('SNYK_TOKEN is required.');
  if (!nonEmptyString(env.SNYK_ORG) || !SAFE_IDENTIFIER.test(env.SNYK_ORG)) {
    throw configurationError('SNYK_ORG is required and must be a valid identifier.');
  }
  const repositoryParts = nonEmptyString(env.GITHUB_REPOSITORY)
    ? env.GITHUB_REPOSITORY.split('/')
    : [];
  if (
    !SAFE_REPOSITORY.test(env.GITHUB_REPOSITORY || '') ||
    repositoryParts.some((part) => part === '.' || part === '..')
  ) {
    throw configurationError('GITHUB_REPOSITORY must identify one owner and repository.');
  }
  const serverUrl = validateServerUrl(env.GITHUB_SERVER_URL);
  const pullRequest = env.GITHUB_EVENT_NAME === 'pull_request';
  const testPush = env.GITHUB_EVENT_NAME === 'push' && env.GITHUB_REF === 'refs/heads/test';
  if (!pullRequest && !testPush) {
    throw configurationError('Snyk CI supports only pull requests or pushes targeting test.');
  }
  return { serverUrl, testPush };
}

// ShiftPrint is a pip project, so Snyk is invoked directly rather than through
// npm scripts. requirements-dev.txt is the scan target because it includes the
// runtime requirements and the build tooling that PyInstaller packages.
const SEVERITY_THRESHOLD = 'high';
const PIP_MANIFEST = 'requirements-dev.txt';
const PIP_ARGS = [`--file=${PIP_MANIFEST}`, '--package-manager=pip'];

export const SNYK_PHASE_ARGS = Object.freeze({
  'open-source': ['test', ...PIP_ARGS, `--severity-threshold=${SEVERITY_THRESHOLD}`],
  code: ['code', 'test', `--severity-threshold=${SEVERITY_THRESHOLD}`],
  monitor: ['monitor', ...PIP_ARGS],
});

function snykCommand(env, platform, phase, args, timeoutMs, transientOutput) {
  const phaseArgs = SNYK_PHASE_ARGS[phase];
  if (!phaseArgs) throw configurationError(`Unknown Snyk phase: ${phase}.`);
  const scannerArgs = [...phaseArgs, ...args];
  const windows = platform === 'win32';
  return {
    file:
      windows && nonEmptyString(env.ComSpec)
        ? env.ComSpec
        : windows
          ? String.raw`C:\Windows\System32\cmd.exe`
          : 'snyk',
    args: windows ? ['/d', '/s', '/c', 'snyk.cmd', ...scannerArgs] : scannerArgs,
    env,
    timeoutMs,
    maxOutputBytes: MAX_OUTPUT_BYTES,
    transientOutput,
  };
}

function repositoryArguments(env, serverUrl) {
  return [
    `--org=${env.SNYK_ORG}`,
    `--project-name=${env.GITHUB_REPOSITORY}`,
    '--target-reference=test',
    `--remote-repo-url=${serverUrl}/${env.GITHUB_REPOSITORY}.git`,
  ];
}

function phaseTimeout(deadline, now, label) {
  const remaining = Math.floor(deadline - now());
  if (remaining <= 0) throw unavailableError(`Snyk ${label} exceeded the aggregate deadline.`);
  return Math.min(COMMAND_TIMEOUT_MS, remaining);
}

async function runPhase({ env, platform, runCommand, phase, args, policy, label, timeoutMs }) {
  const result = await runCommand(
    snykCommand(env, platform, phase, args, timeoutMs, policy.transientOutput),
  );
  const outcome = classifyCommandResult(result, policy);
  if (outcome === SCANNER_OUTCOME.CLEAN) return;
  if (outcome === SCANNER_OUTCOME.FINDING) {
    throw findingError(`Snyk ${label} reported a blocking security finding.`);
  }
  if (outcome === SCANNER_OUTCOME.UNAVAILABLE) {
    throw unavailableError(
      result.timedOut
        ? `Snyk ${label} exceeded its bounded deadline.`
        : `Snyk ${label} encountered a temporary service or network failure.`,
    );
  }
  throw configurationError(`Snyk ${label} failed without a confirmed scanner finding.`);
}

function unavailableReason(error, env) {
  const message = error instanceof Error ? error.message : 'Temporary Snyk availability failure.';
  return sanitizeScannerText(message, env);
}

export async function runSnykCi({
  env = process.env,
  runCommand = runBoundedCommand,
  reportUnavailable = writeUnavailableReport,
  now = monotonicNow,
  platform = process.platform,
} = {}) {
  try {
    if (typeof now !== 'function') throw configurationError('Snyk CI timing function is invalid.');
    const { serverUrl, testPush } = validateConfiguration(env);
    const deadline = now() + AGGREGATE_TIMEOUT_MS;
    const projectArgs = repositoryArguments(env, serverUrl);
    await runPhase({
      env,
      platform,
      runCommand,
      phase: 'open-source',
      args: projectArgs,
      policy: SCAN_POLICY,
      label: 'Open Source scan',
      timeoutMs: phaseTimeout(deadline, now, 'Open Source scan'),
    });
    await runPhase({
      env,
      platform,
      runCommand,
      phase: 'code',
      args: [`--org=${env.SNYK_ORG}`],
      policy: SCAN_POLICY,
      label: 'Code scan',
      timeoutMs: phaseTimeout(deadline, now, 'Code scan'),
    });
    if (testPush) {
      await runPhase({
        env,
        platform,
        runCommand,
        phase: 'monitor',
        args: projectArgs,
        policy: MONITOR_POLICY,
        label: 'test-branch monitor',
        timeoutMs: phaseTimeout(deadline, now, 'test-branch monitor'),
      });
    }
    return { outcome: SCANNER_OUTCOME.CLEAN };
  } catch (error) {
    if (error instanceof ScannerGateError) {
      if (error.outcome !== SCANNER_OUTCOME.UNAVAILABLE) throw error;
      const reason = unavailableReason(error, env);
      reportUnavailable({
        scanner: 'Snyk',
        reason,
        revision: env?.GITHUB_SHA,
        env,
      });
      return { outcome: SCANNER_OUTCOME.UNAVAILABLE, reason };
    }
    throw configurationError(
      sanitizeScannerText(
        error instanceof Error ? error.message : 'Unknown Snyk CI gate failure.',
        env,
      ),
      { cause: error },
    );
  }
}

async function main() {
  try {
    await runSnykCi();
  } catch (error) {
    const safe = sanitizeScannerText(
      error instanceof Error ? error.message : 'Unknown Snyk CI gate failure.',
      process.env,
    );
    process.stderr.write(`Snyk CI gate failed: ${safe}\n`);
    process.exitCode =
      error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING ? 1 : 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
