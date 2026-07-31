import assert from 'node:assert/strict';
import { SCANNER_OUTCOME, ScannerGateError } from './scanner-gate-policy.mjs';
import { runSonarCi } from './run-sonar-ci.mjs';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');

const configuredEnv = {
  SONAR_HOST_URL: 'https://sonarcloud.io',
  SONAR_ORGANIZATION: 'crimsonsoul',
  SONAR_TOKEN: 'sonar-token-sentinel-never-print',
  GITHUB_SHA: 'abc123',
};

const cleanCommand = async () => ({ code: 0, timedOut: false, output: '' });
const noSleep = async () => {};

test('runs the clean pull-request phases in exact order with a bounded upload', async () => {
  const calls = [];
  let command;
  const result = await runSonarCi({
    argv: ['--pull-request=221'],
    env: configuredEnv,
    runCommand: async (options) => {
      calls.push('upload');
      command = options;
      return cleanCommand();
    },
    waitAnalysis: async (options) => calls.push(['wait', options.argv]),
    reconcile: async () => calls.push('reconcile'),
    readIssues: async (options) => {
      calls.push(['issues', options.argv]);
      return { summary: { open: [] } };
    },
    checkGate: async (options) => calls.push(['gate', options.argv]),
    sleep: noSleep,
  });

  assert.equal(result.outcome, SCANNER_OUTCOME.CLEAN);
  assert.deepEqual(calls, [
    'upload',
    ['wait', ['wait-analysis', '--pull-request=221']],
    ['issues', ['--pull-request=221']],
    ['issues', ['--pull-request=221']],
    ['issues', ['--pull-request=221']],
    ['gate', ['check-quality-gate', '--pull-request=221']],
  ]);
  assert.equal(command.timeoutMs, 600_000);
  assert.equal(command.maxOutputBytes, 32_768);
  assert.match(command.file, /sonar-scanner-npm(?:\.cmd)?$/u);
  assert.deepEqual(command.args, [
    '-Dsonar.organization=crimsonsoul',
    '-Dsonar.qualitygate.wait=false',
    '-Dsonar.host.url=https://sonarcloud.io',
  ]);
  assert.equal(command.args.join(' ').includes(configuredEnv.SONAR_TOKEN), false);
});

test('reconciles reviewed findings exactly once only for the test branch', async () => {
  const calls = [];
  const result = await runSonarCi({
    argv: ['--branch=test'],
    env: configuredEnv,
    runCommand: cleanCommand,
    waitAnalysis: async () => calls.push('wait'),
    reconcile: async (options) => calls.push(['reconcile', options.argv]),
    readIssues: async () => {
      calls.push('issues');
      return { summary: { open: [] } };
    },
    checkGate: async () => calls.push('gate'),
    sleep: noSleep,
  });

  assert.equal(result.outcome, SCANNER_OUTCOME.CLEAN);
  assert.deepEqual(calls, [
    'wait',
    ['reconcile', ['--branch=test', '--apply']],
    'issues',
    'issues',
    'issues',
    'gate',
  ]);
});

test('warns and succeeds for bounded or documented transient availability failures', async () => {
  for (const result of [
    { code: null, timedOut: true, output: '' },
    { code: 2, timedOut: false, output: 'upstream HTTP 503 service unavailable' },
    { code: null, timedOut: false, output: 'spawn ENOTFOUND sonarcloud.io' },
  ]) {
    const reports = [];
    const outcome = await runSonarCi({
      argv: ['--pull-request=221'],
      env: configuredEnv,
      runCommand: async () => result,
      reportUnavailable: (report) => reports.push(report),
    });
    assert.equal(outcome.outcome, SCANNER_OUTCOME.UNAVAILABLE);
    assert.equal(reports.length, 1);
    assert.equal(reports[0].reason.includes(configuredEnv.SONAR_TOKEN), false);
  }
});

test('blocks confirmed findings, authentication failures, and ambiguous upload failures', async () => {
  const phases = {
    waitAnalysis: async () => {},
    readIssues: async () => ({ summary: { open: ['shiftprint-finding'] } }),
    checkGate: async () => {},
  };
  await assert.rejects(
    runSonarCi({
      argv: ['--pull-request=221'],
      env: configuredEnv,
      runCommand: cleanCommand,
      ...phases,
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING,
  );
  for (const commandResult of [
    { code: 2, timedOut: false, output: 'HTTP 401 Unauthorized' },
    { code: 2, timedOut: false, output: 'scanner stopped unexpectedly' },
  ]) {
    await assert.rejects(
      runSonarCi({
        argv: ['--pull-request=221'],
        env: configuredEnv,
        runCommand: async () => commandResult,
      }),
      (error) =>
        error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
    );
  }
});

test('softens only typed downstream availability failures', async () => {
  const reports = [];
  const unavailable = new ScannerGateError(
    SCANNER_OUTCOME.UNAVAILABLE,
    `temporary failure using ${configuredEnv.SONAR_TOKEN}`,
  );
  const result = await runSonarCi({
    argv: ['--pull-request=221'],
    env: configuredEnv,
    runCommand: cleanCommand,
    waitAnalysis: async () => {
      throw unavailable;
    },
    reportUnavailable: (report) => reports.push(report),
  });
  assert.equal(result.outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.equal(reports[0].reason.includes(configuredEnv.SONAR_TOKEN), false);

  await assert.rejects(
    runSonarCi({
      argv: ['--pull-request=221'],
      env: configuredEnv,
      runCommand: cleanCommand,
      waitAnalysis: async () => {
        throw new Error('malformed scanner response');
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
  );
});

test('catches findings that appear while the Sonar issue index settles', async () => {
  let issueReads = 0;
  let sleeps = 0;
  await assert.rejects(
    runSonarCi({
      argv: ['--pull-request=221'],
      env: configuredEnv,
      runCommand: cleanCommand,
      waitAnalysis: async () => {},
      readIssues: async () => {
        issueReads += 1;
        return { summary: { open: issueReads === 1 ? [] : ['eventual-finding'] } };
      },
      checkGate: async () => {},
      sleep: async () => {
        sleeps += 1;
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING,
  );
  assert.equal(issueReads, 2);
  assert.equal(sleeps, 1);
});

test('uses one aggregate deadline across Sonar upload and API phases', async () => {
  let clock = 0;
  const calls = [];
  const reports = [];
  const result = await runSonarCi({
    argv: ['--branch=test'],
    env: configuredEnv,
    now: () => clock,
    runCommand: async (command) => {
      calls.push(['upload', command.timeoutMs]);
      clock += 600_000;
      return { code: 0, timedOut: false, output: '' };
    },
    waitAnalysis: async (options) => {
      calls.push(['wait', options.timeoutMs]);
      clock += 300_000;
    },
    reconcile: async (options) => {
      calls.push(['reconcile', options.timeoutMs]);
      clock += 180_000;
    },
    readIssues: async () => {
      calls.push(['issues']);
      return { summary: { open: [] } };
    },
    checkGate: async () => calls.push(['gate']),
    reportUnavailable: (report) => reports.push(report),
  });

  assert.equal(result.outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.deepEqual(calls, [
    ['upload', 600_000],
    ['wait', 300_000],
    ['reconcile', 180_000],
  ]);
  assert.equal(reports.length, 1);
});

test('rejects missing configuration, insecure hosts, and non-test branch scope', async () => {
  for (const [env, argv] of [
    [{ ...configuredEnv, SONAR_TOKEN: '' }, ['--branch=test']],
    [{ ...configuredEnv, SONAR_ORGANIZATION: '' }, ['--branch=test']],
    [
      { ...configuredEnv, SONAR_HOST_URL: ['http:', '//sonar.invalid'].join('') },
      ['--branch=test'],
    ],
    [configuredEnv, ['--branch=main']],
  ]) {
    await assert.rejects(
      runSonarCi({ argv, env, runCommand: cleanCommand }),
      (error) =>
        error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
    );
  }
});
