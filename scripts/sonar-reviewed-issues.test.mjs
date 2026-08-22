import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  REVIEWED_ISSUES,
  fetchCurrentSonarIssues,
  formatReconciliationSummary,
  parseProjectKey,
  parseReviewedArgs,
  planReviewedIssueReconciliation,
  reconcileReviewedSonarIssues,
  runSonarReviewedIssues,
  safeMessage,
  validateReviewedIssueManifest,
} from './sonar-reviewed-issues.mjs';
import { SCANNER_OUTCOME, ScannerGateError } from './scanner-gate-policy.mjs';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');
const TOKEN = 'sonar-reviewed-token-sentinel-never-print';
const HOST_URL = 'https://sonarcloud.io';
const PROJECT_KEY = 'CrimsonSoul_ShiftPrint';

function response(body, { ok = true, status = 200, jsonError } = {}) {
  return {
    ok,
    status,
    json: async () => {
      if (jsonError) throw jsonError;
      return body;
    },
  };
}

function issueFromManifest(expected, status = 'OPEN', overrides = {}) {
  return {
    key: expected.key,
    rule: expected.rule,
    component: expected.component,
    status,
    ...overrides,
  };
}

function page(issues, { pageIndex = 1, total = issues.length } = {}) {
  return {
    paging: {
      pageIndex,
      pageSize: 500,
      total,
    },
    issues,
  };
}

test('starts ShiftPrint with an exact empty reviewed inventory', () => {
  assert.equal(validateReviewedIssueManifest(), REVIEWED_ISSUES);
  assert.deepEqual(REVIEWED_ISSUES, []);
  assert.equal(Object.isFrozen(REVIEWED_ISSUES), true);
});

test('rejects any inherited or unreviewed exception metadata', () => {
  assert.throws(
    () => validateReviewedIssueManifest([{ key: 'relay-exception' }]),
    /exactly 0 issues/i,
  );
  assert.throws(() => validateReviewedIssueManifest(null), /exactly 0 issues/i);
});

test('reads one exact project key and requires an explicit apply latch on branch test', () => {
  assert.equal(
    parseProjectKey('sonar.projectName=ShiftPrint\nsonar.projectKey=CrimsonSoul_ShiftPrint\n'),
    PROJECT_KEY,
  );
  assert.throws(() => parseProjectKey('sonar.projectName=ShiftPrint\n'), /sonar\.projectKey/);
  assert.throws(
    () => parseProjectKey('sonar.projectKey=one\nsonar.projectKey=two\n'),
    /exactly one/i,
  );

  assert.deepEqual(parseReviewedArgs(['--branch=test', '--apply']), {
    apply: true,
    branch: 'test',
  });
  assert.deepEqual(parseReviewedArgs(['--apply', '--branch', 'test']), {
    apply: true,
    branch: 'test',
  });
  assert.throws(() => parseReviewedArgs([]), /restricted to branch test/i);
  assert.throws(() => parseReviewedArgs(['--branch=test']), /requires the explicit --apply latch/i);
  assert.throws(
    () => parseReviewedArgs(['--branch=main', '--apply']),
    /restricted to branch test/i,
  );
  assert.throws(
    () => parseReviewedArgs(['--branch=test', '--branch=test', '--apply']),
    /duplicate --branch/i,
  );
  assert.throws(
    () => parseReviewedArgs(['--branch=test', '--apply', '--apply']),
    /duplicate --apply/i,
  );
  assert.throws(() => parseReviewedArgs(['--pull-request=42']), /unknown argument/i);
  assert.throws(() => parseReviewedArgs(['--branch']), /missing value/i);
});

test('paginates current issue states with an exact project and test branch scope', async () => {
  const requests = [];
  const firstPage = Array.from({ length: 500 }, (_, index) => ({
    key: `reviewed-history-${String(index).padStart(3, '0')}`,
    rule: 'typescript:S0000',
    component: `${PROJECT_KEY}:src/history-${index}.ts`,
    status: 'RESOLVED',
    resolution: 'WONTFIX',
    issueStatus: 'ACCEPTED',
  }));
  const fetcher = async (url, options) => {
    requests.push({ url: new URL(url), options });
    const currentPage = Number(new URL(url).searchParams.get('p'));
    return currentPage === 1
      ? response(page(firstPage, { total: 501 }))
      : response(
          page(
            [
              {
                key: 'reviewed-history-last',
                rule: 'typescript:S0000',
                component: `${PROJECT_KEY}:src/history-last.ts`,
                status: 'RESOLVED',
                resolution: 'FALSE-POSITIVE',
                issueStatus: 'FALSE_POSITIVE',
              },
            ],
            { pageIndex: 2, total: 501 },
          ),
        );
  };

  const issues = await fetchCurrentSonarIssues({
    fetcher,
    hostUrl: HOST_URL,
    projectKey: PROJECT_KEY,
    token: TOKEN,
  });

  assert.equal(issues.length, 501);
  assert.equal(issues[0].status, 'ACCEPTED');
  assert.equal(issues.at(-1).status, 'FALSE_POSITIVE');
  assert.equal(requests.length, 2);
  for (const { url, options } of requests) {
    assert.equal(url.pathname, '/api/issues/search');
    assert.equal(url.searchParams.get('componentKeys'), PROJECT_KEY);
    assert.equal(url.searchParams.get('issueStatuses'), 'OPEN,CONFIRMED,ACCEPTED,FALSE_POSITIVE');
    assert.equal(url.searchParams.get('branch'), 'test');
    assert.equal(url.searchParams.get('ps'), '500');
    assert.equal(url.searchParams.has('pullRequest'), false);
    assert.equal(url.searchParams.has('token'), false);
    assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
  }
});

test('rejects insecure or credential-bearing hosts before sending the token', async () => {
  for (const hostUrl of [
    'http://sonar.example.test',
    'https://user:password@sonar.example.test',
    'https://sonar.example.test?token=unsafe',
  ]) {
    let requested = false;
    await assert.rejects(
      fetchCurrentSonarIssues({
        fetcher: async () => {
          requested = true;
          return response(page([]));
        },
        hostUrl,
        projectKey: PROJECT_KEY,
        token: TOKEN,
      }),
      /credential-free HTTPS/i,
    );
    assert.equal(requested, false);
  }
});

test('reconciles the empty inventory without mutating Sonar', async () => {
  const requests = [];
  const fetcher = async (url, options = {}) => {
    requests.push({ url: new URL(url), options });
    return response(page([]));
  };

  const result = await reconcileReviewedSonarIssues({
    fetcher,
    hostUrl: HOST_URL,
    projectKey: PROJECT_KEY,
    token: TOKEN,
  });

  assert.deepEqual(result.transitions, []);
  assert.deepEqual(result.transitioned, []);
  assert.deepEqual(result.alreadyReviewed, []);
  assert.deepEqual(result.fixedOrMissing, []);
  assert.deepEqual(result.ignoredReviewed, []);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.method, undefined);
});

test('ignores historical reviewed issues without inheriting them as exceptions', () => {
  const result = planReviewedIssueReconciliation([
    {
      key: 'historical-reviewed-issue',
      rule: 'typescript:S0001',
      component: `${PROJECT_KEY}:src/historical.ts`,
      status: 'ACCEPTED',
    },
  ]);

  assert.deepEqual(result.transitions, []);
  assert.deepEqual(result.alreadyReviewed, []);
  assert.deepEqual(result.ignoredReviewed, ['historical-reviewed-issue']);
  assert.deepEqual(result.fixedOrMissing, []);
});

test('fails closed before mutation when an unreviewed open issue appears', async () => {
  let requestCount = 0;
  await assert.rejects(
    reconcileReviewedSonarIssues({
      fetcher: async (_url, options = {}) => {
        requestCount += 1;
        assert.equal(options.method, undefined);
        return response(
          page([
            {
              key: 'new-unreviewed-issue',
              rule: 'python:S9999',
              component: `${PROJECT_KEY}:src/new_behavior.py`,
              status: 'OPEN',
            },
          ]),
        );
      },
      hostUrl: HOST_URL,
      projectKey: PROJECT_KEY,
      token: TOKEN,
    }),
    (error) => {
      assert.match(error.message, /unreviewed open or confirmed issues: new-unreviewed-issue/i);
      return error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.FINDING;
    },
  );
  assert.equal(requestCount, 1);
});

test('fails closed when canonical and legacy Sonar issue states conflict', () => {
  const issue = {
    key: 'historical-reviewed-issue',
    rule: 'python:S0001',
    component: `${PROJECT_KEY}:src/historical.py`,
  };
  assert.throws(
    () =>
      planReviewedIssueReconciliation([
        issueFromManifest(issue, 'RESOLVED', {
          resolution: 'WONTFIX',
          issueStatus: 'FALSE_POSITIVE',
        }),
      ]),
    /conflicting.*status/i,
  );
  assert.throws(
    () =>
      planReviewedIssueReconciliation([
        issueFromManifest(issue, 'RESOLVED', {
          resolution: 'REMOVED',
        }),
      ]),
    /unsupported.*status/i,
  );
});

test('fails on search API, JSON, duplicate, and pagination errors', async () => {
  const options = {
    hostUrl: HOST_URL,
    projectKey: PROJECT_KEY,
    token: TOKEN,
  };
  await assert.rejects(
    fetchCurrentSonarIssues({
      ...options,
      fetcher: async () => response({}, { ok: false, status: 503 }),
    }),
    /HTTP 503/,
  );
  await assert.rejects(
    fetchCurrentSonarIssues({
      ...options,
      fetcher: async () => response({}, { jsonError: new Error('bad JSON') }),
    }),
    /invalid JSON/i,
  );
  await assert.rejects(
    fetchCurrentSonarIssues({
      ...options,
      fetcher: async () => {
        const duplicate = {
          key: 'duplicate-issue',
          rule: 'python:S0001',
          component: `${PROJECT_KEY}:src/duplicate.py`,
          status: 'OPEN',
        };
        return response(page([duplicate, duplicate]));
      },
    }),
    /duplicate issue key/i,
  );

  let pageNumber = 0;
  await assert.rejects(
    fetchCurrentSonarIssues({
      ...options,
      fetcher: async () => {
        pageNumber += 1;
        const issues =
          pageNumber === 1
            ? Array.from({ length: 500 }, (_, index) => ({
                key: `stable-${index}`,
                rule: 'typescript:S0000',
                component: `${PROJECT_KEY}:src/stable-${index}.ts`,
                status: 'ACCEPTED',
              }))
            : [];
        return response(
          page(issues, {
            pageIndex: pageNumber,
            total: pageNumber === 1 ? 501 : 500,
          }),
        );
      },
    }),
    /pagination total changed/i,
  );
});

test('types reviewed-issue service availability separately from authentication', async () => {
  const options = {
    hostUrl: HOST_URL,
    projectKey: PROJECT_KEY,
    token: TOKEN,
  };
  for (const status of [429, 503]) {
    await assert.rejects(
      fetchCurrentSonarIssues({
        ...options,
        fetcher: async () => response({}, { ok: false, status }),
      }),
      (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
    );
  }
  await assert.rejects(
    fetchCurrentSonarIssues({
      ...options,
      fetcher: async () => response({}, { ok: false, status: 401 }),
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.CONFIGURATION,
  );
  await assert.rejects(
    fetchCurrentSonarIssues({
      ...options,
      fetcher: async () => {
        throw new Error('network offline');
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
});

test('bounds reviewed-issue searches with abort signals', async () => {
  let searchSignal = false;
  await assert.rejects(
    fetchCurrentSonarIssues({
      hostUrl: HOST_URL,
      projectKey: PROJECT_KEY,
      token: TOKEN,
      requestTimeoutMs: 10,
      fetcher: async (_url, options) => {
        searchSignal = options.signal instanceof AbortSignal;
        if (!searchSignal) throw new Error('missing search abort signal');
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
  assert.equal(searchSignal, true);
});

test('formats deterministic summaries and redacts hostile token text', () => {
  assert.equal(
    formatReconciliationSummary({
      transitioned: ['transitioned-a'],
      alreadyReviewed: ['reviewed-a'],
      fixedOrMissing: ['fixed-a'],
    }),
    [
      'Sonar reviewed issue reconciliation for branch test: transitioned=1 already_reviewed=1 fixed_or_missing=1',
      'Transitioned: transitioned-a',
      'Already reviewed: reviewed-a',
      'Fixed or missing: fixed-a',
    ].join('\n'),
  );
  assert.equal(
    safeMessage(new Error(`request failed using ${TOKEN}`), TOKEN).includes(TOKEN),
    false,
  );
});

test('requires environment authentication and never emits the token sentinel', async () => {
  const output = [];
  await assert.rejects(
    runSonarReviewedIssues({
      argv: ['--branch=test', '--apply'],
      env: {},
      readProperties: () => `sonar.projectKey=${PROJECT_KEY}\n`,
      write: (line) => output.push(line),
    }),
    /SONAR_TOKEN/,
  );
  await assert.rejects(
    runSonarReviewedIssues({
      argv: ['--branch=test', '--apply'],
      env: { SONAR_TOKEN: TOKEN },
      fetcher: async () => {
        throw new Error(`network failed while using ${TOKEN}`);
      },
      readProperties: () => `sonar.projectKey=${PROJECT_KEY}\n`,
      write: (line) => output.push(line),
    }),
    (error) => {
      assert.equal(error.message.includes(TOKEN), false);
      return true;
    },
  );
  assert.equal(output.join('\n').includes(TOKEN), false);
});

test('the Sonar CI runner reconciles reviewed issues only on main-branch pushes', async () => {
  const [workflow, runner] = await Promise.all([
    readFile(new URL('../.github/workflows/security.yml', import.meta.url), 'utf8'),
    readFile(new URL('./run-sonar-ci.mjs', import.meta.url), 'utf8'),
  ]);

  assert.doesNotMatch(workflow, /workflow_dispatch:/);
  assert.match(workflow, /node scripts\/run-sonar-ci\.mjs "\$\{SONAR_SCOPE\[@\]\}"/u);
  const branchGuard = runner.indexOf("if ('branch' in scope)");
  const reconcileStep = runner.indexOf('await reconcile({');
  const openFindingGate = runner.indexOf('await waitForSettledIssues');
  assert.ok(branchGuard >= 0, 'missing branch-only guard');
  assert.ok(reconcileStep > branchGuard, 'reviewed reconciliation must follow branch-only guard');
  assert.ok(openFindingGate > reconcileStep, 'reviewed reconciliation must precede the open gate');
});
