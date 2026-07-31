import { spawn } from 'node:child_process';
import { appendFileSync } from 'node:fs';

export const SCANNER_OUTCOME = Object.freeze({
  CLEAN: 'clean',
  FINDING: 'finding',
  UNAVAILABLE: 'unavailable',
  CONFIGURATION: 'configuration',
});

const ERROR_OUTCOMES = new Set([
  SCANNER_OUTCOME.FINDING,
  SCANNER_OUTCOME.UNAVAILABLE,
  SCANNER_OUTCOME.CONFIGURATION,
]);
const SECRET_NAME_PATTERN = /(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)$/u;
const MAX_REPORT_REASON_LENGTH = 500;

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function boundedText(value, maximum) {
  const text = String(value);
  return text.length <= maximum ? text : `${text.slice(0, maximum - 1)}…`;
}

function secretValues(env) {
  if (!env || typeof env !== 'object' || Array.isArray(env)) return [];
  return Object.entries(env)
    .filter(([name, value]) => SECRET_NAME_PATTERN.test(name) && nonEmptyString(value))
    .map(([, value]) => value)
    .sort((left, right) => right.length - left.length);
}

export function sanitizeScannerText(value, env = {}) {
  let text = String(value ?? '');
  for (const secret of secretValues(env)) text = text.replaceAll(secret, '[REDACTED]');
  return text;
}

function workflowCommandText(value, env) {
  return sanitizeScannerText(value, env)
    .replaceAll('%', '%25')
    .replaceAll('\r', '%0D')
    .replaceAll('\n', '%0A');
}

function appendBounded(buffer, chunk, maximum) {
  const addition = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
  const combined = Buffer.concat([buffer, addition]);
  return combined.length <= maximum ? combined : combined.subarray(combined.length - maximum);
}

function signalProcessTree(child, signal) {
  if (!Number.isInteger(child?.pid)) return;
  if (process.platform === 'win32') {
    if (signal === 'SIGKILL') {
      const terminator = spawn(
        String.raw`C:\Windows\System32\taskkill.exe`,
        ['/pid', String(child.pid), '/t', '/f'],
        { shell: false, stdio: 'ignore', windowsHide: true },
      );
      terminator.on('error', () => child.kill());
      return;
    }
    child.kill(signal);
    return;
  }

  try {
    process.kill(-child.pid, signal);
  } catch {
    child.kill(signal);
  }
}

export class ScannerGateError extends Error {
  constructor(outcome, message, options = {}) {
    if (!ERROR_OUTCOMES.has(outcome)) {
      throw new TypeError('Scanner error outcome is invalid.');
    }
    super(message, options);
    this.name = 'ScannerGateError';
    this.outcome = outcome;
  }
}

export const findingError = (message, options = {}) =>
  new ScannerGateError(SCANNER_OUTCOME.FINDING, message, options);

export const unavailableError = (message, options = {}) =>
  new ScannerGateError(SCANNER_OUTCOME.UNAVAILABLE, message, options);

export const configurationError = (message, options = {}) =>
  new ScannerGateError(SCANNER_OUTCOME.CONFIGURATION, message, options);

export function classifyHttpFailure(scanner, status) {
  if (!nonEmptyString(scanner)) throw new TypeError('Scanner name is required.');
  if (!Number.isInteger(status)) {
    return configurationError(`${scanner} returned an invalid HTTP status.`);
  }
  if (status === 429 || (status >= 500 && status <= 599)) {
    return unavailableError(`${scanner} request failed with HTTP ${status}.`);
  }
  return configurationError(`${scanner} request failed with HTTP ${status}.`);
}

export function classifyCommandResult(result, policy) {
  if (result === null || typeof result !== 'object' || Array.isArray(result)) {
    throw new TypeError('Scanner command result is invalid.');
  }
  if (result.sawTransientOutput !== undefined && typeof result.sawTransientOutput !== 'boolean') {
    throw new TypeError('Scanner command transient evidence is invalid.');
  }
  if (
    !policy ||
    typeof policy !== 'object' ||
    Array.isArray(policy) ||
    !Array.isArray(policy.findingExitCodes) ||
    !Array.isArray(policy.unavailableExitCodes) ||
    !Array.isArray(policy.configurationExitCodes) ||
    !(policy.transientOutput instanceof RegExp)
  ) {
    throw new TypeError('Scanner command policy is invalid.');
  }
  if (policy.findingExitCodes.includes(result.code)) return SCANNER_OUTCOME.FINDING;
  if (policy.configurationExitCodes.includes(result.code)) return SCANNER_OUTCOME.CONFIGURATION;
  if (result.timedOut === true) return SCANNER_OUTCOME.UNAVAILABLE;
  if (result.code === 0) return SCANNER_OUTCOME.CLEAN;
  if (policy.unavailableExitCodes.includes(result.code)) return SCANNER_OUTCOME.UNAVAILABLE;
  policy.transientOutput.lastIndex = 0;
  if (
    result.sawTransientOutput === true ||
    policy.transientOutput.test(String(result.output ?? ''))
  ) {
    return SCANNER_OUTCOME.UNAVAILABLE;
  }
  return SCANNER_OUTCOME.CONFIGURATION;
}

export async function runBoundedCommand({
  file,
  args,
  cwd,
  env,
  timeoutMs,
  maxOutputBytes,
  transientOutput,
  write = (text) => process.stdout.write(text),
}) {
  if (!nonEmptyString(file)) throw new TypeError('Scanner command file is required.');
  if (!Array.isArray(args) || args.some((argument) => typeof argument !== 'string')) {
    throw new TypeError('Scanner command arguments are invalid.');
  }
  if (cwd !== undefined && !nonEmptyString(cwd)) {
    throw new TypeError('Scanner command working directory is invalid.');
  }
  if (!env || typeof env !== 'object' || Array.isArray(env)) {
    throw new TypeError('Scanner command environment is invalid.');
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 3_600_000) {
    throw new TypeError('Scanner command timeout is invalid.');
  }
  if (!Number.isSafeInteger(maxOutputBytes) || maxOutputBytes < 1 || maxOutputBytes > 1_048_576) {
    throw new TypeError('Scanner command output bound is invalid.');
  }
  if (transientOutput !== undefined && !(transientOutput instanceof RegExp)) {
    throw new TypeError('Scanner command transient pattern is invalid.');
  }
  if (typeof write !== 'function') throw new TypeError('Scanner command writer is invalid.');

  return new Promise((resolve) => {
    let retained = Buffer.alloc(0);
    let sawTransientOutput = false;
    let timedOut = false;
    let deadline;
    let killTimer;
    let settleTimer;
    let child;
    let settled = false;
    let observedExitCode = null;

    const retain = (chunk) => {
      const addition = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
      if (!sawTransientOutput && transientOutput) {
        transientOutput.lastIndex = 0;
        sawTransientOutput = transientOutput.test(
          Buffer.concat([retained, addition]).toString('utf8'),
        );
      }
      retained = appendBounded(retained, addition, maxOutputBytes);
    };

    const finish = (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      clearTimeout(killTimer);
      clearTimeout(settleTimer);
      child?.stdout?.destroy();
      child?.stderr?.destroy();
      const output = sanitizeScannerText(retained.toString('utf8'), env);
      if (output) write(output.endsWith('\n') ? output : `${output}\n`);
      resolve({
        code: Number.isInteger(code) ? code : null,
        timedOut,
        output,
        sawTransientOutput,
      });
    };

    try {
      child = spawn(file, args, {
        cwd,
        detached: process.platform !== 'win32',
        env,
        shell: false,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
    } catch (error) {
      retain(error instanceof Error ? error.message : 'Scanner command could not start.');
      finish(null);
      return;
    }

    child.stdout.on('data', retain);
    child.stderr.on('data', retain);
    child.on('error', (error) => retain(error.message));
    child.once('exit', (code) => {
      if (Number.isInteger(code)) observedExitCode = code;
    });
    child.once('close', (code) => finish(Number.isInteger(code) ? code : observedExitCode));

    deadline = setTimeout(() => {
      timedOut = true;
      signalProcessTree(child, 'SIGTERM');
      killTimer = setTimeout(() => signalProcessTree(child, 'SIGKILL'), 250);
      killTimer.unref?.();
      settleTimer = setTimeout(() => finish(observedExitCode), 1_000);
      settleTimer.unref?.();
    }, timeoutMs);
    deadline.unref?.();
  });
}

export function writeUnavailableReport({
  scanner,
  reason,
  revision,
  env = process.env,
  appendFile = appendFileSync,
  write = (text) => process.stdout.write(text),
}) {
  if (!nonEmptyString(scanner)) throw new TypeError('Scanner name is required.');
  if (typeof appendFile !== 'function' || typeof write !== 'function') {
    throw new TypeError('Scanner report writer is invalid.');
  }
  const safeReason = boundedText(
    sanitizeScannerText(reason || 'Temporary scanner availability failure.', env),
    MAX_REPORT_REASON_LENGTH,
  );
  const safeRevision = boundedText(sanitizeScannerText(revision || 'unknown', env), 160);
  const safeTitle = workflowCommandText(`${scanner} unavailable`, env);
  write(`::warning title=${safeTitle}::${workflowCommandText(safeReason, env)}\n`);

  if (nonEmptyString(env.GITHUB_STEP_SUMMARY)) {
    appendFile(
      env.GITHUB_STEP_SUMMARY,
      [
        `## ${scanner} unavailable`,
        '',
        `- Revision: \`${safeRevision.replaceAll('`', "'")}\``,
        `- Category: ${safeReason.replaceAll(/\s+/gu, ' ')}`,
        '- No security decision was produced.',
        '- Retry the scan when the service is available.',
        '',
      ].join('\n'),
    );
  }
}
