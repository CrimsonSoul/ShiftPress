import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  SCANNER_OUTCOME,
  ScannerGateError,
  classifyCommandResult,
  classifyHttpFailure,
  configurationError,
  findingError,
  runBoundedCommand,
  unavailableError,
  writeUnavailableReport,
} from './scanner-gate-policy.mjs';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');

const COMMAND_POLICY = {
  findingExitCodes: [1],
  unavailableExitCodes: [69, 75],
  configurationExitCodes: [3, 77],
  transientOutput: /HTTP 429/iu,
};

test('classifies only documented HTTP availability failures as unavailable', () => {
  assert.equal(classifyHttpFailure('Sonar', 429).outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.equal(classifyHttpFailure('Sonar', 503).outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.equal(classifyHttpFailure('Sonar', 401).outcome, SCANNER_OUTCOME.CONFIGURATION);
  assert.equal(classifyHttpFailure('Sonar', 403).outcome, SCANNER_OUTCOME.CONFIGURATION);
  assert.equal(classifyHttpFailure('Sonar', 400).outcome, SCANNER_OUTCOME.CONFIGURATION);
  assert.equal(classifyHttpFailure('Sonar', undefined).outcome, SCANNER_OUTCOME.CONFIGURATION);
});

test('constructs typed errors and rejects ambiguous outcomes', () => {
  assert.equal(findingError('found').outcome, SCANNER_OUTCOME.FINDING);
  assert.equal(unavailableError('offline').outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.equal(configurationError('bad config').outcome, SCANNER_OUTCOME.CONFIGURATION);
  assert.throws(() => new ScannerGateError('maybe', 'ambiguous'), /outcome/i);
  assert.throws(() => new ScannerGateError(SCANNER_OUTCOME.CLEAN, 'not an error'), /outcome/i);
});

test('classifies clean, finding, unavailable, timeout, transient, and unknown commands', () => {
  assert.equal(
    classifyCommandResult({ code: 0, timedOut: false, output: '' }, COMMAND_POLICY),
    SCANNER_OUTCOME.CLEAN,
  );
  assert.equal(
    classifyCommandResult({ code: 0, timedOut: true, output: '' }, COMMAND_POLICY),
    SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(
    classifyCommandResult({ code: 1, timedOut: false, output: 'issues found' }, COMMAND_POLICY),
    SCANNER_OUTCOME.FINDING,
  );
  assert.equal(
    classifyCommandResult({ code: 1, timedOut: true, output: 'issues found' }, COMMAND_POLICY),
    SCANNER_OUTCOME.FINDING,
  );
  assert.equal(
    classifyCommandResult({ code: 75, timedOut: false, output: '' }, COMMAND_POLICY),
    SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(
    classifyCommandResult({ code: null, timedOut: true, output: '' }, COMMAND_POLICY),
    SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(
    classifyCommandResult({ code: 2, timedOut: false, output: 'HTTP 429' }, COMMAND_POLICY),
    SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(
    classifyCommandResult({ code: 3, timedOut: false, output: 'HTTP 429' }, COMMAND_POLICY),
    SCANNER_OUTCOME.CONFIGURATION,
  );
  for (const code of [3, 77]) {
    assert.equal(
      classifyCommandResult({ code, timedOut: true, output: '' }, COMMAND_POLICY),
      SCANNER_OUTCOME.CONFIGURATION,
    );
  }
  assert.equal(
    classifyCommandResult(
      { code: 2, timedOut: false, output: 'authentication failed' },
      COMMAND_POLICY,
    ),
    SCANNER_OUTCOME.CONFIGURATION,
  );
  assert.equal(
    classifyCommandResult({ code: null, timedOut: false, output: 'spawn failed' }, COMMAND_POLICY),
    SCANNER_OUTCOME.CONFIGURATION,
  );
});

test('rejects invalid command results and policies', () => {
  assert.throws(() => classifyCommandResult(null, COMMAND_POLICY), /result/i);
  assert.throws(
    () =>
      classifyCommandResult(
        { code: 0, timedOut: false, output: '' },
        { ...COMMAND_POLICY, findingExitCodes: '1' },
      ),
    /policy/i,
  );
});

test('runs a command, bounds retained output, and redacts token values', async () => {
  const emitted = [];
  const result = await runBoundedCommand({
    file: process.execPath,
    args: ['-e', "process.stdout.write('prefix-token-sentinel-abcdefghijklmnopqrstuvwxyz')"],
    env: { ...process.env, SCANNER_TOKEN: 'token-sentinel' },
    timeoutMs: 1_000,
    maxOutputBytes: 24,
    write: (text) => emitted.push(text),
  });

  assert.equal(result.code, 0);
  assert.equal(result.timedOut, false);
  assert.ok(Buffer.byteLength(result.output) <= 24);
  assert.equal(result.output.includes('token-sentinel'), false);
  assert.equal(emitted.join('').includes('token-sentinel'), false);
});

test('preserves transient evidence after it scrolls out of the bounded output tail', async () => {
  const result = await runBoundedCommand({
    file: process.execPath,
    args: [
      '-e',
      "process.stdout.write('HTTP 429 rate limited\\n'); process.stdout.write('x'.repeat(8192)); process.exit(2)",
    ],
    env: process.env,
    timeoutMs: 1_000,
    maxOutputBytes: 128,
    transientOutput: COMMAND_POLICY.transientOutput,
    write: () => {},
  });

  assert.equal(result.output.includes('HTTP 429'), false);
  assert.equal(result.sawTransientOutput, true);
  assert.equal(classifyCommandResult(result, COMMAND_POLICY), SCANNER_OUTCOME.UNAVAILABLE);
});

test('kills a command at its internal deadline', async () => {
  const result = await runBoundedCommand({
    file: process.execPath,
    args: ['-e', 'setInterval(() => {}, 1000)'],
    env: process.env,
    timeoutMs: 50,
    maxOutputBytes: 4_096,
    write: () => {},
  });

  assert.equal(result.timedOut, true);
  assert.equal(result.code, null);
});

test('bounds an npm command and its descendant process tree', async () => {
  const fixture = mkdtempSync(join(tmpdir(), 'shiftpress-scanner-gate-'));
  try {
    writeFileSync(
      join(fixture, 'package.json'),
      JSON.stringify({
        scripts: {
          hang: `"${process.execPath}" -e "setInterval(() => {}, 1000)"`,
        },
      }),
    );
    const started = Date.now();
    const result = await runBoundedCommand({
      file: process.platform === 'win32' ? 'npm.cmd' : 'npm',
      args: ['run', 'hang'],
      cwd: fixture,
      env: process.env,
      timeoutMs: 100,
      maxOutputBytes: 4_096,
      write: () => {},
    });

    assert.equal(result.timedOut, true);
    assert.equal(result.code, null);
    assert.ok(Date.now() - started < 2_000, 'npm descendant tree exceeded the bounded deadline');
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});

test('preserves a finding exit code when inherited pipes outlive the command', async () => {
  const escapedChild = [
    "const { spawn } = require('node:child_process');",
    "const child = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 5000)'], {",
    "  detached: true, stdio: ['ignore', 1, 2],",
    '});',
    'child.unref();',
    'process.exit(1);',
  ].join('\n');
  const result = await runBoundedCommand({
    file: process.execPath,
    args: ['-e', escapedChild],
    env: process.env,
    timeoutMs: 1_000,
    maxOutputBytes: 4_096,
    write: () => {},
  });

  assert.equal(result.timedOut, true);
  assert.equal(result.code, 1);
  assert.equal(classifyCommandResult(result, COMMAND_POLICY), SCANNER_OUTCOME.FINDING);
});

test('writes a bounded warning and job summary without echoing tokens', () => {
  const annotations = [];
  const summaries = [];
  writeUnavailableReport({
    scanner: 'Snyk',
    reason: 'service unavailable\nusing token-sentinel',
    revision: 'abc123',
    env: { SNYK_TOKEN: 'token-sentinel', GITHUB_STEP_SUMMARY: '/summary' },
    appendFile: (path, text) => summaries.push({ path, text }),
    write: (text) => annotations.push(text),
  });

  assert.match(annotations.join(''), /::warning title=Snyk unavailable::/u);
  assert.equal(annotations.join('').includes('\nusing'), false);
  assert.equal(summaries[0].path, '/summary');
  assert.match(summaries[0].text, /No security decision was produced/u);
  assert.match(summaries[0].text, /Retry the scan when the service is available/u);
  assert.equal(`${annotations.join('')} ${summaries[0].text}`.includes('token-sentinel'), false);
});

test('does not write a summary when GitHub did not provide a summary path', () => {
  let appended = false;
  writeUnavailableReport({
    scanner: 'Sonar',
    reason: 'HTTP 503',
    revision: 'abc123',
    env: {},
    appendFile: () => {
      appended = true;
    },
    write: () => {},
  });
  assert.equal(appended, false);
});
