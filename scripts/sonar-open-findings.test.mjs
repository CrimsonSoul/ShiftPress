import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  classifyIssue,
  fetchSonarIssues,
  formatSonarSummary,
  parseProjectKey,
  parseScopeArgs,
  runSonarOpenFindings,
  sonarGateExitCode,
} from './sonar-open-findings.mjs';
import { SCANNER_OUTCOME, ScannerGateError } from './scanner-gate-policy.mjs';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');
const TOKEN = 'sonar-token-sentinel-never-print';

function response(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

test('parses one exact sonar.projectKey from the project properties', () => {
  assert.equal(
    parseProjectKey('sonar.projectName=ShiftPress\nsonar.projectKey=CrimsonSoul_ShiftPrint\n'),
    'CrimsonSoul_ShiftPrint',
  );
  assert.throws(() => parseProjectKey('sonar.projectName=ShiftPress\n'), /sonar\.projectKey/);
  assert.throws(
    () => parseProjectKey('sonar.projectKey=one\nsonar.projectKey=two\n'),
    /exactly one/,
  );
});

test('requires exactly one branch or pull-request scope', () => {
  assert.deepEqual(parseScopeArgs(['--branch=test']), { branch: 'test' });
  assert.deepEqual(parseScopeArgs(['--pull-request', '42']), { pullRequest: '42' });
  assert.throws(() => parseScopeArgs([]), /exactly one/i);
  assert.throws(() => parseScopeArgs(['--branch=test', '--pull-request=42']), /exactly one/i);
  assert.throws(() => parseScopeArgs(['--branch=test', '--branch=other']), /duplicate/i);
  assert.throws(() => parseScopeArgs(['--pull-request=41', '--pull-request=42']), /duplicate/i);
  assert.throws(() => parseScopeArgs(['--pull-request=not-a-number']), /pull request/i);
  assert.throws(() => parseScopeArgs(['--branch=test', '--unknown=value']), /unknown argument/i);
  assert.throws(() => parseScopeArgs(['--branch']), /missing value/i);
  assert.throws(() => parseScopeArgs(['--branch', '--pull-request=42']), /missing value/i);
});

test('paginates current Sonar issue statuses and scopes every request to the branch', async () => {
  const requests = [];
  const fetcher = async (url, options) => {
    requests.push({ url: new URL(url), options });
    const page = Number(new URL(url).searchParams.get('p'));
    return page === 1
      ? response({
          paging: { pageIndex: 1, pageSize: 500, total: 501 },
          issues: [
            ...Array.from({ length: 498 }, (_, index) => ({
              key: `fixed-${String(index).padStart(3, '0')}`,
              status: 'FIXED',
              resolution: 'FIXED',
            })),
            { key: 'open-b', status: 'CONFIRMED', resolution: null },
            {
              key: 'accepted-a',
              status: 'RESOLVED',
              resolution: 'WONTFIX',
              issueStatus: 'ACCEPTED',
            },
          ],
        })
      : response({
          paging: { pageIndex: 2, pageSize: 500, total: 501 },
          issues: [
            {
              key: 'false-positive-a',
              status: 'RESOLVED',
              resolution: 'FALSE-POSITIVE',
              issueStatus: 'FALSE_POSITIVE',
            },
          ],
        });
  };

  const issues = await fetchSonarIssues({
    fetcher,
    hostUrl: 'https://sonarcloud.io',
    projectKey: 'CrimsonSoul_ShiftPrint',
    scope: { branch: 'test' },
    token: TOKEN,
  });

  assert.equal(requests.length, 2);
  for (const { url, options } of requests) {
    assert.equal(url.pathname, '/api/issues/search');
    assert.equal(url.searchParams.get('componentKeys'), 'CrimsonSoul_ShiftPrint');
    assert.equal(url.searchParams.get('issueStatuses'), 'OPEN,CONFIRMED,ACCEPTED,FALSE_POSITIVE');
    assert.equal(url.searchParams.get('branch'), 'test');
    assert.equal(url.searchParams.has('pullRequest'), false);
    assert.equal(url.searchParams.get('ps'), '500');
    assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
  }
  assert.equal(issues.length, 501);
  assert.deepEqual(
    issues.slice(-3).map((issue) => issue.key),
    ['open-b', 'accepted-a', 'false-positive-a'],
  );
});

test('uses pullRequest without leaking a branch selector', async () => {
  let requested;
  await fetchSonarIssues({
    fetcher: async (url) => {
      requested = new URL(url);
      return response({ paging: { pageIndex: 1, pageSize: 500, total: 0 }, issues: [] });
    },
    hostUrl: 'https://sonarcloud.io/',
    projectKey: 'CrimsonSoul_ShiftPrint',
    scope: { pullRequest: '99' },
    token: TOKEN,
  });

  assert.equal(requested.searchParams.get('pullRequest'), '99');
  assert.equal(requested.searchParams.has('branch'), false);
});

test('rejects an insecure Sonar host before sending the bearer token', async () => {
  let requested = false;
  await assert.rejects(
    fetchSonarIssues({
      fetcher: async () => {
        requested = true;
        return response({ paging: { pageIndex: 1, pageSize: 500, total: 0 }, issues: [] });
      },
      hostUrl: 'http://sonar.example.test',
      projectKey: 'CrimsonSoul_ShiftPrint',
      scope: { branch: 'test' },
      token: TOKEN,
    }),
    /HTTPS/i,
  );
  assert.equal(requested, false);
});

test('the security workflow delegates HTTPS validation to the Sonar CI gate', async () => {
  const [workflow, runner] = await Promise.all([
    readFile(new URL('../.github/workflows/security.yml', import.meta.url), 'utf8'),
    readFile(new URL('./run-sonar-ci.mjs', import.meta.url), 'utf8'),
  ]);
  assert.match(workflow, /node scripts\/run-sonar-ci\.mjs "\$\{SONAR_SCOPE\[@\]\}"/u);
  assert.match(runner, /SONAR_HOST_URL must be a credential-free HTTPS URL/u);
});

test('the Sonar CI gate reconciles only after the exact analysis and gates it last', async () => {
  const runner = await readFile(new URL('./run-sonar-ci.mjs', import.meta.url), 'utf8');
  const scanner = runner.indexOf('const upload = await runCommand');
  const waitForAnalysis = runner.indexOf('await waitAnalysis');
  const reconcileReviewed = runner.indexOf('await reconcile');
  const openFindings = runner.indexOf('await waitForSettledIssues');
  const qualityGate = runner.indexOf('await checkGate');

  assert.ok(scanner >= 0, 'missing Sonar scanner invocation');
  assert.match(runner, /-Dsonar\.qualitygate\.wait=false/u);
  assert.doesNotMatch(runner, /-Dsonar\.qualitygate\.wait=true/u);
  assert.ok(waitForAnalysis > scanner, 'the exact analysis must finish after scanner upload');
  assert.ok(
    reconcileReviewed > waitForAnalysis,
    'reviewed issues must reconcile only after the exact analysis finishes',
  );
  assert.ok(
    openFindings > reconcileReviewed,
    'unresolved issues must be checked after main-branch reconciliation',
  );
  assert.ok(qualityGate > openFindings, 'the exact quality gate must be evaluated last');
  assert.match(runner, /--pull-request=/u);
  assert.match(runner, /--branch=main/u);
});

test('maps canonical and legacy reviewed states without hiding reopened findings', () => {
  assert.equal(classifyIssue({ key: 'a', status: 'OPEN', resolution: null }), 'open');
  assert.equal(classifyIssue({ key: 'b', status: 'CONFIRMED', resolution: null }), 'open');
  assert.equal(classifyIssue({ key: 'c', status: 'REOPENED', resolution: null }), 'open');
  assert.equal(classifyIssue({ key: 'd', status: 'ACCEPTED', resolution: null }), 'accepted');
  assert.equal(
    classifyIssue({
      key: 'e',
      status: 'RESOLVED',
      resolution: 'WONTFIX',
      issueStatus: 'ACCEPTED',
    }),
    'accepted',
  );
  assert.equal(
    classifyIssue({ key: 'f', status: 'FALSE_POSITIVE', resolution: null }),
    'falsePositive',
  );
  assert.equal(
    classifyIssue({
      key: 'g',
      status: 'RESOLVED',
      resolution: 'FALSE-POSITIVE',
      issueStatus: 'FALSE_POSITIVE',
    }),
    'falsePositive',
  );
  assert.equal(classifyIssue({ key: 'h', status: 'FIXED', resolution: 'FIXED' }), 'resolved');
});

test('fails closed when canonical and legacy Sonar issue states conflict', () => {
  assert.throws(
    () =>
      classifyIssue({
        key: 'conflict-a',
        status: 'RESOLVED',
        resolution: 'WONTFIX',
        issueStatus: 'FALSE_POSITIVE',
      }),
    /conflicting.*status/i,
  );
  assert.throws(
    () =>
      classifyIssue({
        key: 'unsupported-a',
        status: 'RESOLVED',
        resolution: 'REMOVED',
      }),
    /unsupported.*status/i,
  );
  assert.throws(
    () =>
      classifyIssue({
        key: 'unsupported-b',
        status: '__proto__',
        resolution: null,
      }),
    /unsupported.*status/i,
  );
});

test('formats deterministic counts and sorted issue keys', () => {
  assert.equal(
    formatSonarSummary(
      [
        { key: 'open-z', status: 'OPEN', resolution: null },
        { key: 'accepted-b', status: 'ACCEPTED', resolution: null },
        { key: 'open-a', status: 'REOPENED', resolution: null },
        { key: 'false-a', status: 'FALSE_POSITIVE', resolution: null },
      ],
      { branch: 'test' },
    ),
    [
      'Sonar issues for branch test: open=2 accepted=1 false_positive=1',
      'Open/confirmed: open-a, open-z',
      'Accepted: accepted-b',
      'False positive: false-a',
    ].join('\n'),
  );
});

test('fails the command whenever an open, confirmed, or reopened issue remains', () => {
  assert.equal(sonarGateExitCode({ open: [], accepted: [], falsePositive: [], resolved: [] }), 0);
  assert.equal(
    sonarGateExitCode({
      open: ['open-a'],
      accepted: ['accepted-a'],
      falsePositive: ['false-a'],
      resolved: [],
    }),
    1,
  );
});

test('fails closed on malformed API data, duplicate keys, and HTTP errors', async () => {
  const options = {
    hostUrl: 'https://sonarcloud.io',
    projectKey: 'CrimsonSoul_ShiftPrint',
    scope: { branch: 'test' },
    token: TOKEN,
  };
  await assert.rejects(
    fetchSonarIssues({
      ...options,
      fetcher: async () => response({ paging: { total: 1 }, issues: 'not-an-array' }),
    }),
    /invalid issue response/i,
  );
  await assert.rejects(
    fetchSonarIssues({
      ...options,
      fetcher: async () =>
        response({
          paging: { pageIndex: 1, pageSize: 500, total: 2 },
          issues: [
            { key: 'duplicate', status: 'OPEN', resolution: null },
            { key: 'duplicate', status: 'OPEN', resolution: null },
          ],
        }),
    }),
    /duplicate issue key/i,
  );
  await assert.rejects(
    fetchSonarIssues({
      ...options,
      fetcher: async () => response({}, { ok: false, status: 503 }),
    }),
    /HTTP 503/,
  );
});

test('types Sonar availability separately from authentication and contract failures', async () => {
  const options = {
    hostUrl: 'https://sonarcloud.io',
    projectKey: 'CrimsonSoul_ShiftPrint',
    scope: { branch: 'test' },
    token: TOKEN,
  };
  for (const status of [429, 503]) {
    await assert.rejects(
      fetchSonarIssues({
        ...options,
        fetcher: async () => response({}, { ok: false, status }),
      }),
      (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
    );
  }
  for (const status of [400, 401, 403]) {
    await assert.rejects(
      fetchSonarIssues({
        ...options,
        fetcher: async () => response({}, { ok: false, status }),
      }),
      (error) =>
        error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
    );
  }
  await assert.rejects(
    fetchSonarIssues({
      ...options,
      fetcher: async () => {
        throw new Error('network offline');
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
});

test('bounds each Sonar issue-search request with an abort signal', async () => {
  let receivedSignal = false;
  await assert.rejects(
    fetchSonarIssues({
      hostUrl: 'https://sonarcloud.io',
      projectKey: 'CrimsonSoul_ShiftPrint',
      scope: { branch: 'test' },
      token: TOKEN,
      requestTimeoutMs: 10,
      fetcher: async (_url, options) => {
        receivedSignal = options.signal instanceof AbortSignal;
        if (!receivedSignal) throw new Error('missing abort signal');
        return new Promise((_resolve, reject) => {
          const watchdog = setTimeout(() => reject(new Error('abort signal did not fire')), 1_000);
          options.signal.addEventListener(
            'abort',
            () => {
              clearTimeout(watchdog);
              reject(options.signal.reason);
            },
            { once: true },
          );
        });
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(receivedSignal, true);
});

test('uses one aggregate deadline across Sonar issue-search pages', async () => {
  let clock = 0;
  let requests = 0;
  await assert.rejects(
    fetchSonarIssues({
      hostUrl: 'https://sonarcloud.io',
      projectKey: 'CrimsonSoul_ShiftPrint',
      scope: { branch: 'test' },
      token: TOKEN,
      timeoutMs: 50,
      now: () => clock,
      fetcher: async () => {
        requests += 1;
        clock += 50;
        return response({
          paging: { pageIndex: requests, pageSize: 500, total: 501 },
          issues:
            requests === 1
              ? Array.from({ length: 500 }, (_, index) => ({
                  key: `issue-${index}`,
                  status: 'ACCEPTED',
                }))
              : [{ key: 'issue-500', status: 'ACCEPTED' }],
        });
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(requests, 1);
});

test('requires environment authentication and never emits the token sentinel', async () => {
  const output = [];
  await assert.rejects(
    runSonarOpenFindings({
      argv: ['--branch=test'],
      env: {},
      readProperties: () => 'sonar.projectKey=CrimsonSoul_ShiftPrint\n',
      write: (line) => output.push(line),
    }),
    /SONAR_TOKEN/,
  );

  const hostileError = new Error(`network failed while using ${TOKEN}`);
  await assert.rejects(
    runSonarOpenFindings({
      argv: ['--branch=test'],
      env: { SONAR_TOKEN: TOKEN },
      fetcher: async () => {
        throw hostileError;
      },
      readProperties: () => 'sonar.projectKey=CrimsonSoul_ShiftPrint\n',
      write: (line) => output.push(line),
    }),
    (error) => {
      assert.equal(String(error).includes(TOKEN), false);
      return true;
    },
  );
  assert.equal(output.join('\n').includes(TOKEN), false);
});
