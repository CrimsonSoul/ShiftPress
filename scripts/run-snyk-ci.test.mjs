import assert from 'node:assert/strict';
import { SCANNER_OUTCOME, ScannerGateError } from './scanner-gate-policy.mjs';
import { runSnykCi } from './run-snyk-ci.mjs';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');

const configuredEnv = {
  SNYK_ORG: 'crimsonsoul',
  SNYK_TOKEN: 'snyk-token-sentinel-never-print',
  GITHUB_EVENT_NAME: 'pull_request',
  GITHUB_REF: 'refs/pull/221/merge',
  GITHUB_REPOSITORY: 'CrimsonSoul/ShiftPress',
  GITHUB_SERVER_URL: 'https://github.com',
  GITHUB_SHA: 'abc123',
};

const commandResult = (code, output = '', timedOut = false) => ({ code, output, timedOut });

test('runs Open Source and Code with exact bounded repository arguments on pull requests', async () => {
  const commands = [];
  const result = await runSnykCi({
    env: configuredEnv,
    runCommand: async (command) => {
      commands.push(command);
      return commandResult(0);
    },
  });

  assert.equal(result.outcome, SCANNER_OUTCOME.CLEAN);
  assert.equal(commands.length, 2);
  assert.deepEqual(commands[0].args, [
    'test',
    '--file=requirements-dev.txt',
    '--package-manager=pip',
    '--severity-threshold=high',
    '--org=crimsonsoul',
    '--project-name=CrimsonSoul/ShiftPress',
    '--target-reference=test',
    '--remote-repo-url=https://github.com/CrimsonSoul/ShiftPress.git',
  ]);
  assert.deepEqual(commands[1].args, [
    'code',
    'test',
    '--severity-threshold=high',
    '--org=crimsonsoul',
  ]);
  for (const command of commands) {
    assert.match(command.file, /snyk(?:\.cmd)?$/u);
    assert.equal(command.timeoutMs, 600_000);
    assert.equal(command.maxOutputBytes, 32_768);
    assert.ok(command.transientOutput instanceof RegExp);
    assert.equal(command.args.join(' ').includes(configuredEnv.SNYK_TOKEN), false);
  }
});

test('launches the Windows npm shim through the command processor', async () => {
  const commands = [];
  const windowsEnv = {
    ...configuredEnv,
    ComSpec: String.raw`C:\Windows\System32\cmd.exe`,
  };

  await runSnykCi({
    env: windowsEnv,
    platform: 'win32',
    runCommand: async (command) => {
      commands.push(command);
      return commandResult(0);
    },
  });

  assert.equal(commands[0].file, windowsEnv.ComSpec);
  assert.deepEqual(commands[0].args.slice(0, 5), ['/d', '/s', '/c', 'snyk.cmd', 'test']);
});

test('adds the monitor command only after clean scans on a test-branch push', async () => {
  const commands = [];
  const result = await runSnykCi({
    env: {
      ...configuredEnv,
      GITHUB_EVENT_NAME: 'push',
      GITHUB_REF: 'refs/heads/test',
    },
    runCommand: async (command) => {
      commands.push(command.args);
      return commandResult(0);
    },
  });

  assert.equal(result.outcome, SCANNER_OUTCOME.CLEAN);
  assert.deepEqual(
    commands.map((args) => args.slice(0, 2).join(' ')),
    ['test --file=requirements-dev.txt', 'code test', 'monitor --file=requirements-dev.txt'],
  );
  // monitor carries the same repository arguments as the Open Source scan
  const repoArgs = (args) => args.filter((a) => a.startsWith('--org=') || a.startsWith('--project-name=') || a.startsWith('--target-reference=') || a.startsWith('--remote-repo-url='));
  assert.deepEqual(repoArgs(commands[2]), repoArgs(commands[0]));
});

test('blocks documented finding exit 1 and stops before later phases', async () => {
  const commands = [];
  await assert.rejects(
    runSnykCi({
      env: configuredEnv,
      runCommand: async (command) => {
        commands.push(command.args[0]);
        return commandResult(1, 'high severity vulnerability found');
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING,
  );
  assert.deepEqual(commands, ['test']);
});

test('warns for documented temporary exits, timeouts, and transient service failures', async () => {
  for (const scanResult of [
    commandResult(69),
    commandResult(75),
    commandResult(null, '', true),
    commandResult(2, 'HTTP 429 rate limit reached'),
    commandResult(2, 'request failed with ECONNRESET'),
  ]) {
    const reports = [];
    const result = await runSnykCi({
      env: configuredEnv,
      runCommand: async () => scanResult,
      reportUnavailable: (report) => reports.push(report),
    });
    assert.equal(result.outcome, SCANNER_OUTCOME.UNAVAILABLE);
    assert.equal(reports.length, 1);
    assert.equal(reports[0].reason.includes(configuredEnv.SNYK_TOKEN), false);
  }
});

test('keeps unknown and documented configuration exits blocking', async () => {
  for (const scanResult of [
    commandResult(2, 'generic scanner failure'),
    commandResult(3, 'HTTP 503 but no supported projects detected'),
    commandResult(77, 'service unavailable but permission denied'),
    commandResult(null, 'scanner configuration failed'),
  ]) {
    await assert.rejects(
      runSnykCi({
        env: configuredEnv,
        runCommand: async () => scanResult,
      }),
      (error) =>
        error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
    );
  }
});

test('treats monitor availability as warning success but monitor exit 1 as configuration', async () => {
  const pushEnv = {
    ...configuredEnv,
    GITHUB_EVENT_NAME: 'push',
    GITHUB_REF: 'refs/heads/test',
  };
  const reports = [];
  let call = 0;
  const unavailable = await runSnykCi({
    env: pushEnv,
    runCommand: async () => {
      call += 1;
      return call === 3 ? commandResult(75) : commandResult(0);
    },
    reportUnavailable: (report) => reports.push(report),
  });
  assert.equal(unavailable.outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.equal(reports.length, 1);

  call = 0;
  await assert.rejects(
    runSnykCi({
      env: pushEnv,
      runCommand: async () => {
        call += 1;
        return call === 3 ? commandResult(1, 'monitor rejected project') : commandResult(0);
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
  );
});

test('uses one aggregate deadline across sequential Snyk phases', async () => {
  let clock = 0;
  const commands = [];
  const reports = [];
  const result = await runSnykCi({
    env: {
      ...configuredEnv,
      GITHUB_EVENT_NAME: 'push',
      GITHUB_REF: 'refs/heads/test',
    },
    now: () => clock,
    runCommand: async (command) => {
      commands.push(command);
      clock += commands.length === 1 ? 600_000 : 480_000;
      return commandResult(0);
    },
    reportUnavailable: (report) => reports.push(report),
  });

  assert.equal(result.outcome, SCANNER_OUTCOME.UNAVAILABLE);
  assert.equal(commands.length, 2);
  assert.equal(commands[0].timeoutMs, 600_000);
  assert.equal(commands[1].timeoutMs, 480_000);
  assert.equal(reports.length, 1);
});

test('rejects missing credentials and unsupported GitHub context before scanning', async () => {
  for (const env of [
    { ...configuredEnv, SNYK_TOKEN: '' },
    { ...configuredEnv, SNYK_ORG: '' },
    { ...configuredEnv, GITHUB_EVENT_NAME: 'workflow_dispatch' },
    { ...configuredEnv, GITHUB_EVENT_NAME: 'push', GITHUB_REF: 'refs/heads/main' },
    { ...configuredEnv, GITHUB_REPOSITORY: '../other' },
    {
      ...configuredEnv,
      GITHUB_SERVER_URL: ['http:', '//github.invalid'].join(''),
    },
  ]) {
    let scanned = false;
    await assert.rejects(
      runSnykCi({
        env,
        runCommand: async () => {
          scanned = true;
          return commandResult(0);
        },
      }),
      (error) =>
        error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
    );
    assert.equal(scanned, false);
  }
});
