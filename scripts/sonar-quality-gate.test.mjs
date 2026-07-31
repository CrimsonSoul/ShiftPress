import assert from 'node:assert/strict';
import {
  parseReportTask,
  parseSonarGateArgs,
  runSonarQualityGate,
  waitForComputeTask,
  waitForQualityGate,
} from './sonar-quality-gate.mjs';
import { SCANNER_OUTCOME, ScannerGateError } from './scanner-gate-policy.mjs';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');
const TOKEN = 'sonar-quality-token-sentinel-never-print';
const PROJECT_KEY = 'CrimsonSoul_ShiftPrint';
const HOST_URL = 'https://sonarcloud.io';
const CE_TASK_ID = 'ce-task_123';
const ANALYSIS_ID = 'analysis_456';

function response(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

function reportTask(overrides = {}) {
  const values = {
    projectKey: PROJECT_KEY,
    serverUrl: HOST_URL,
    ceTaskId: CE_TASK_ID,
    ceTaskUrl: `${HOST_URL}/api/ce/task?id=${CE_TASK_ID}`,
    dashboardUrl: `${HOST_URL}/dashboard?id=${PROJECT_KEY}&branch=test`,
    ...overrides,
  };
  return Object.entries(values)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
}

function successfulBranchTask(overrides = {}) {
  return {
    task: {
      id: CE_TASK_ID,
      status: 'SUCCESS',
      componentKey: PROJECT_KEY,
      branch: 'test',
      branchType: 'LONG',
      analysisId: ANALYSIS_ID,
      ...overrides,
    },
  };
}

function latestAnalyses(key = ANALYSIS_ID, overrides = {}) {
  return {
    paging: {
      pageIndex: 1,
      pageSize: 1,
      total: 8,
    },
    analyses: [
      {
        key,
        date: '2026-07-26T21:54:03+0000',
        events: [],
        projectVersion: '1.0.0',
        manualNewCodePeriodBaseline: false,
        revision: 'd0b0d12c52a8aacea6286828a8667d287fd42f95',
      },
    ],
    ...overrides,
  };
}

function fakeClock() {
  let time = 0;
  return {
    now: () => time,
    sleep: async (milliseconds) => {
      time += milliseconds;
    },
  };
}

test('requires one action and one bounded branch or pull-request scope', () => {
  assert.deepEqual(parseSonarGateArgs(['wait-analysis', '--branch=test']), {
    action: 'wait-analysis',
    scope: { branch: 'test' },
  });
  assert.deepEqual(parseSonarGateArgs(['check-quality-gate', '--pull-request', '42']), {
    action: 'check-quality-gate',
    scope: { pullRequest: '42' },
  });
  assert.throws(() => parseSonarGateArgs([]), /action/i);
  assert.throws(() => parseSonarGateArgs(['unknown', '--branch=test']), /action/i);
  assert.throws(() => parseSonarGateArgs(['wait-analysis']), /exactly one/i);
  assert.throws(
    () => parseSonarGateArgs(['check-quality-gate', '--branch=test', '--pull-request=42']),
    /exactly one/i,
  );
});

test('accepts only the scanner report for the configured HTTPS host and project', () => {
  assert.deepEqual(
    parseReportTask({
      report: reportTask(),
      configuredHostUrl: HOST_URL,
      expectedProjectKey: PROJECT_KEY,
    }),
    {
      ceTaskId: CE_TASK_ID,
      projectKey: PROJECT_KEY,
      serverUrl: `${HOST_URL}/`,
    },
  );

  assert.throws(
    () =>
      parseReportTask({
        // eslint-disable-next-line sonarjs/no-clear-text-protocols -- Deliberately insecure fixture verifies fail-closed host validation.
        report: reportTask({ serverUrl: 'http://sonarcloud.io' }),
        // eslint-disable-next-line sonarjs/no-clear-text-protocols -- Deliberately insecure fixture verifies fail-closed host validation.
        configuredHostUrl: 'http://sonarcloud.io',
        expectedProjectKey: PROJECT_KEY,
      }),
    /HTTPS/i,
  );
  assert.throws(
    () =>
      parseReportTask({
        report: reportTask(),
        configuredHostUrl: 'https://sonar.example.test',
        expectedProjectKey: PROJECT_KEY,
      }),
    /configured Sonar host/i,
  );
  assert.throws(
    () =>
      parseReportTask({
        report: reportTask({ projectKey: 'other_project' }),
        configuredHostUrl: HOST_URL,
        expectedProjectKey: PROJECT_KEY,
      }),
    /project key/i,
  );
  assert.throws(
    () =>
      parseReportTask({
        report: reportTask({
          ceTaskUrl: `${HOST_URL}/api/ce/task?id=some-other-task`,
        }),
        configuredHostUrl: HOST_URL,
        expectedProjectKey: PROJECT_KEY,
      }),
    /task URL/i,
  );
  assert.throws(
    () =>
      parseReportTask({
        report: `${reportTask()}\nceTaskId=duplicate`,
        configuredHostUrl: HOST_URL,
        expectedProjectKey: PROJECT_KEY,
      }),
    /duplicate/i,
  );
});

test('rejects invalid compute-task timing dependencies with TypeError', async () => {
  const options = {
    fetcher: async () => response(successfulBranchTask()),
    serverUrl: `${HOST_URL}/`,
    taskId: CE_TASK_ID,
    projectKey: PROJECT_KEY,
    scope: { branch: 'test' },
    token: TOKEN,
  };

  await assert.rejects(waitForComputeTask({ ...options, now: null }), TypeError);
  await assert.rejects(waitForComputeTask({ ...options, sleep: null }), TypeError);
});

test('rejects invalid quality-gate timing dependencies with TypeError', async () => {
  const options = {
    fetcher: async () => response({ projectStatus: { status: 'OK', conditions: [] } }),
    serverUrl: `${HOST_URL}/`,
    analysisId: ANALYSIS_ID,
    projectKey: PROJECT_KEY,
    scope: { pullRequest: '42' },
    token: TOKEN,
  };

  await assert.rejects(waitForQualityGate({ ...options, now: null }), TypeError);
  await assert.rejects(waitForQualityGate({ ...options, sleep: null }), TypeError);
});

test('waits for the exact branch compute task and never sends its token off-host', async () => {
  const statuses = ['PENDING', 'IN_PROGRESS', 'SUCCESS'];
  const requests = [];
  const clock = fakeClock();
  const result = await waitForComputeTask({
    fetcher: async (url, options) => {
      requests.push({ url: new URL(url), options });
      const status = statuses.shift();
      return response(
        status === 'SUCCESS'
          ? successfulBranchTask()
          : successfulBranchTask({ status, analysisId: undefined }),
      );
    },
    serverUrl: `${HOST_URL}/`,
    taskId: CE_TASK_ID,
    projectKey: PROJECT_KEY,
    scope: { branch: 'test' },
    token: TOKEN,
    now: clock.now,
    sleep: clock.sleep,
    timeoutMs: 10_000,
    pollIntervalMs: 100,
  });

  assert.equal(result.analysisId, ANALYSIS_ID);
  assert.equal(requests.length, 3);
  for (const { url, options } of requests) {
    assert.equal(url.origin, HOST_URL);
    assert.equal(url.pathname, '/api/ce/task');
    assert.equal(url.searchParams.get('id'), CE_TASK_ID);
    assert.equal(url.searchParams.size, 1);
    assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
    assert.ok(options.signal instanceof AbortSignal);
  }
});

test('rejects a completed compute task from a different project or scope', async () => {
  const options = {
    fetcher: async () => response(successfulBranchTask()),
    serverUrl: `${HOST_URL}/`,
    taskId: CE_TASK_ID,
    projectKey: PROJECT_KEY,
    token: TOKEN,
    timeoutMs: 1_000,
    pollIntervalMs: 10,
  };
  await assert.rejects(
    waitForComputeTask({
      ...options,
      fetcher: async () => response(successfulBranchTask({ componentKey: 'other_project' })),
      scope: { branch: 'test' },
    }),
    /project/i,
  );
  await assert.rejects(
    waitForComputeTask({
      ...options,
      fetcher: async () => response(successfulBranchTask({ branch: 'main' })),
      scope: { branch: 'test' },
    }),
    /branch/i,
  );
  await assert.rejects(
    waitForComputeTask({
      ...options,
      fetcher: async () =>
        response(
          successfulBranchTask({
            branch: undefined,
            branchType: 'PULL_REQUEST',
            pullRequest: '41',
          }),
        ),
      scope: { pullRequest: '42' },
    }),
    /pull request/i,
  );
  await assert.rejects(
    waitForComputeTask({
      ...options,
      fetcher: async () =>
        response(
          successfulBranchTask({
            branch: 'feature/quality-gate',
            branchType: 'BRANCH',
            pullRequest: '42',
          }),
        ),
      scope: { pullRequest: '42' },
    }),
    /pull request/i,
  );
});

test('accepts the exact SonarCloud pull-request task schema', async () => {
  const result = await waitForComputeTask({
    fetcher: async () =>
      response(
        successfulBranchTask({
          branch: undefined,
          branchType: undefined,
          pullRequest: '42',
        }),
      ),
    serverUrl: `${HOST_URL}/`,
    taskId: CE_TASK_ID,
    projectKey: PROJECT_KEY,
    scope: { pullRequest: '42' },
    token: TOKEN,
    timeoutMs: 1_000,
    pollIntervalMs: 10,
  });

  assert.equal(result.analysisId, ANALYSIS_ID);
});

test('fails closed when the exact compute task fails, is malformed, or times out', async () => {
  const base = {
    serverUrl: `${HOST_URL}/`,
    taskId: CE_TASK_ID,
    projectKey: PROJECT_KEY,
    scope: { branch: 'test' },
    token: TOKEN,
    timeoutMs: 100,
    pollIntervalMs: 50,
  };
  await assert.rejects(
    waitForComputeTask({
      ...base,
      fetcher: async () => response(successfulBranchTask({ status: 'FAILED' })),
    }),
    /FAILED/i,
  );
  await assert.rejects(
    waitForComputeTask({
      ...base,
      fetcher: async () => response({ task: { id: CE_TASK_ID, status: 'SUCCESS' } }),
    }),
    /invalid.*task/i,
  );

  const clock = fakeClock();
  await assert.rejects(
    waitForComputeTask({
      ...base,
      fetcher: async () =>
        response(successfulBranchTask({ status: 'PENDING', analysisId: undefined })),
      now: clock.now,
      sleep: clock.sleep,
    }),
    /timed out/i,
  );
});

test('polls the live branch gate only while the exact task analysis remains latest', async () => {
  const statuses = ['ERROR', 'ERROR', 'OK'];
  const requests = [];
  const clock = fakeClock();
  const result = await waitForQualityGate({
    fetcher: async (url, options) => {
      const requested = new URL(url);
      requests.push({ url: requested, options });
      if (requested.pathname === '/api/project_analyses/search') {
        return response(latestAnalyses());
      }
      return response({ projectStatus: { status: statuses.shift(), conditions: [] } });
    },
    serverUrl: `${HOST_URL}/`,
    analysisId: ANALYSIS_ID,
    projectKey: PROJECT_KEY,
    scope: { branch: 'test' },
    token: TOKEN,
    now: clock.now,
    sleep: clock.sleep,
    timeoutMs: 10_000,
    pollIntervalMs: 100,
  });

  assert.equal(result.status, 'OK');
  assert.deepEqual(
    requests.map(({ url }) => url.pathname),
    [
      '/api/project_analyses/search',
      '/api/qualitygates/project_status',
      '/api/project_analyses/search',
      '/api/qualitygates/project_status',
      '/api/project_analyses/search',
      '/api/qualitygates/project_status',
      '/api/project_analyses/search',
    ],
  );
  for (const { url, options } of requests) {
    assert.equal(url.origin, HOST_URL);
    assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
    if (url.pathname === '/api/project_analyses/search') {
      assert.equal(url.searchParams.get('project'), PROJECT_KEY);
      assert.equal(url.searchParams.get('branch'), 'test');
      assert.equal(url.searchParams.get('p'), '1');
      assert.equal(url.searchParams.get('ps'), '1');
      assert.equal(url.searchParams.size, 4);
    } else {
      assert.equal(url.pathname, '/api/qualitygates/project_status');
      assert.equal(url.searchParams.get('projectKey'), PROJECT_KEY);
      assert.equal(url.searchParams.get('branch'), 'test');
      assert.equal(url.searchParams.has('analysisId'), false);
      assert.equal(url.searchParams.size, 2);
    }
  }
});

test('fails closed when a newer branch analysis supersedes the exact compute task', async () => {
  const requests = [];
  const latestKeys = [ANALYSIS_ID, 'newer_analysis'];
  const clock = fakeClock();
  await assert.rejects(
    waitForQualityGate({
      fetcher: async (url) => {
        const requested = new URL(url);
        requests.push(requested);
        if (requested.pathname === '/api/project_analyses/search') {
          return response(latestAnalyses(latestKeys.shift()));
        }
        return response({ projectStatus: { status: 'ERROR', conditions: [] } });
      },
      serverUrl: `${HOST_URL}/`,
      analysisId: ANALYSIS_ID,
      projectKey: PROJECT_KEY,
      scope: { branch: 'test' },
      token: TOKEN,
      now: clock.now,
      sleep: clock.sleep,
      timeoutMs: 10_000,
      pollIntervalMs: 100,
    }),
    /no longer the latest.*branch test/i,
  );
  assert.deepEqual(
    requests.map((url) => url.pathname),
    [
      '/api/project_analyses/search',
      '/api/qualitygates/project_status',
      '/api/project_analyses/search',
    ],
  );
});

test('rejects malformed latest-analysis responses without exposing response data', async () => {
  const invalidResponses = [
    null,
    {},
    { paging: { pageIndex: 2, pageSize: 1, total: 1 }, analyses: latestAnalyses().analyses },
    { paging: { pageIndex: 1, pageSize: 2, total: 1 }, analyses: latestAnalyses().analyses },
    { paging: { pageIndex: 1, pageSize: 1, total: 0 }, analyses: [] },
    {
      paging: { pageIndex: 1, pageSize: 1, total: 1 },
      analyses: [{ key: TOKEN }],
    },
  ];

  for (const payload of invalidResponses) {
    await assert.rejects(
      waitForQualityGate({
        fetcher: async () => response(payload),
        serverUrl: `${HOST_URL}/`,
        analysisId: ANALYSIS_ID,
        projectKey: PROJECT_KEY,
        scope: { branch: 'test' },
        token: TOKEN,
        timeoutMs: 1_000,
        pollIntervalMs: 10,
      }),
      (error) => {
        assert.match(String(error), /(invalid latest-analysis response|no longer the latest)/i);
        assert.equal(String(error).includes(TOKEN), false);
        return true;
      },
    );
  }
});

test('preserves pull-request analysis-ID behavior and fails a non-passing gate immediately', async () => {
  const requests = [];
  const clock = fakeClock();
  await assert.rejects(
    waitForQualityGate({
      fetcher: async (url) => {
        requests.push(new URL(url));
        return response({ projectStatus: { status: 'ERROR', conditions: [] } });
      },
      serverUrl: `${HOST_URL}/`,
      analysisId: ANALYSIS_ID,
      projectKey: PROJECT_KEY,
      scope: { pullRequest: '42' },
      token: TOKEN,
      now: clock.now,
      sleep: clock.sleep,
      timeoutMs: 10_000,
      pollIntervalMs: 100,
    }),
    /failed.*pull request 42/i,
  );
  assert.equal(requests.length, 1);
  assert.equal(requests[0].pathname, '/api/qualitygates/project_status');
  assert.equal(requests[0].searchParams.get('analysisId'), ANALYSIS_ID);
  assert.equal(requests[0].searchParams.size, 1);
  assert.equal(clock.now(), 0);
});

test('types Sonar quality findings, availability, and authentication separately', async () => {
  const options = {
    serverUrl: `${HOST_URL}/`,
    analysisId: ANALYSIS_ID,
    projectKey: PROJECT_KEY,
    scope: { pullRequest: '42' },
    token: TOKEN,
    timeoutMs: 1_000,
    pollIntervalMs: 10,
  };

  await assert.rejects(
    waitForQualityGate({
      ...options,
      fetcher: async () => response({ projectStatus: { status: 'ERROR', conditions: [] } }),
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING,
  );
  for (const status of [429, 503]) {
    await assert.rejects(
      waitForQualityGate({
        ...options,
        fetcher: async () => response({}, { ok: false, status }),
      }),
      (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
    );
  }
  await assert.rejects(
    waitForQualityGate({
      ...options,
      fetcher: async () => response({}, { ok: false, status: 401 }),
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
  );
  await assert.rejects(
    waitForQualityGate({
      ...options,
      fetcher: async () => {
        throw new Error('network offline');
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
});

test('types bounded Sonar polling timeouts as unavailable', async () => {
  const clock = fakeClock();
  await assert.rejects(
    waitForComputeTask({
      fetcher: async () =>
        response(successfulBranchTask({ status: 'PENDING', analysisId: undefined })),
      serverUrl: `${HOST_URL}/`,
      taskId: CE_TASK_ID,
      projectKey: PROJECT_KEY,
      scope: { branch: 'test' },
      token: TOKEN,
      now: clock.now,
      sleep: clock.sleep,
      timeoutMs: 100,
      pollIntervalMs: 50,
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
});

test('shares one deadline across compute and final quality-gate polling', async () => {
  const clock = fakeClock();
  let computeRequests = 0;
  await assert.rejects(
    runSonarQualityGate({
      argv: ['check-quality-gate', '--branch=test'],
      env: { SONAR_HOST_URL: HOST_URL, SONAR_TOKEN: TOKEN },
      readProjectProperties: () => `sonar.projectKey=${PROJECT_KEY}\n`,
      readReportTask: () => reportTask(),
      fetcher: async (url) => {
        const requested = new URL(url);
        if (requested.pathname === '/api/ce/task') {
          computeRequests += 1;
          return response(
            successfulBranchTask({
              status: computeRequests === 1 ? 'PENDING' : 'SUCCESS',
              analysisId: computeRequests === 1 ? undefined : ANALYSIS_ID,
            }),
          );
        }
        if (requested.pathname === '/api/project_analyses/search') {
          return response(latestAnalyses());
        }
        return response({ projectStatus: { status: 'ERROR', conditions: [] } });
      },
      now: clock.now,
      sleep: clock.sleep,
      timeoutMs: 100,
      pollIntervalMs: 60,
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING,
  );
  assert.equal(clock.now(), 100);
});

test('runs both phases from the fixed scanner report without exposing the token', async () => {
  const output = [];
  const requests = [];
  const common = {
    env: { SONAR_HOST_URL: HOST_URL, SONAR_TOKEN: TOKEN },
    readProjectProperties: () => `sonar.projectKey=${PROJECT_KEY}\n`,
    readReportTask: () => reportTask(),
    fetcher: async (url) => {
      const requested = new URL(url);
      requests.push(requested);
      if (requested.pathname === '/api/ce/task') {
        return response(successfulBranchTask());
      }
      if (requested.pathname === '/api/project_analyses/search') {
        return response(latestAnalyses());
      }
      return response({ projectStatus: { status: 'OK', conditions: [] } });
    },
    write: (line) => output.push(line),
  };

  await runSonarQualityGate({
    ...common,
    argv: ['wait-analysis', '--branch=test'],
  });
  await runSonarQualityGate({
    ...common,
    argv: ['check-quality-gate', '--branch=test'],
  });

  assert.deepEqual(
    requests.map((url) => url.pathname),
    [
      '/api/ce/task',
      '/api/ce/task',
      '/api/project_analyses/search',
      '/api/qualitygates/project_status',
      '/api/project_analyses/search',
    ],
  );
  assert.match(output.join('\n'), /quality gate passed.*branch test/i);
  assert.equal(output.join('\n').includes(TOKEN), false);

  await assert.rejects(
    runSonarQualityGate({
      ...common,
      env: {},
      argv: ['wait-analysis', '--branch=test'],
    }),
    /SONAR_TOKEN/,
  );
});

test('redacts a token echoed by a hostile network error', async () => {
  const output = [];
  await assert.rejects(
    runSonarQualityGate({
      argv: ['wait-analysis', '--branch=test'],
      env: { SONAR_HOST_URL: HOST_URL, SONAR_TOKEN: TOKEN },
      readProjectProperties: () => `sonar.projectKey=${PROJECT_KEY}\n`,
      readReportTask: () => reportTask(),
      fetcher: async () => {
        throw new Error(`request failed with ${TOKEN}`);
      },
      write: (line) => output.push(line),
    }),
    (error) => {
      assert.equal(String(error).includes(TOKEN), false);
      return true;
    },
  );
  assert.equal(output.join('\n').includes(TOKEN), false);
});
