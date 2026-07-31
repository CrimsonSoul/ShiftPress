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

test('pins the exact reviewed inventory and intended dispositions', () => {
  assert.equal(validateReviewedIssueManifest(), REVIEWED_ISSUES);
  assert.equal(REVIEWED_ISSUES.length, 49);
  assert.equal(new Set(REVIEWED_ISSUES.map((issue) => issue.key)).size, 49);
  assert.equal(REVIEWED_ISSUES.filter((issue) => issue.transition === 'accept').length, 43);
  assert.equal(REVIEWED_ISSUES.filter((issue) => issue.transition === 'falsepositive').length, 6);

  const falsePositiveRules = REVIEWED_ISSUES.filter((issue) => issue.transition === 'falsepositive')
    .map((issue) => issue.rule)
    .sort();
  assert.deepEqual(falsePositiveRules, [
    'css:S7924',
    'css:S7924',
    'css:S7924',
    'tssecurity:S5144',
    'typescript:S7758',
    'typescript:S7758',
  ]);
  assert.deepEqual(
    REVIEWED_ISSUES.filter((issue) => issue.rule === 'typescript:S8980').map((issue) => issue.key),
    ['AZ-alMl2TAUVQ8sYgoiA'],
  );
  assert.deepEqual(
    REVIEWED_ISSUES.filter((issue) => issue.rule === 'tssecurity:S5144').map(
      ({ key, transition }) => ({ key, transition }),
    ),
    [{ key: 'AZ-gb17s7Nsapz3kouHt', transition: 'falsepositive' }],
  );
  assert.deepEqual(
    REVIEWED_ISSUES.filter((issue) => issue.rule === 'typescript:S7785').map(
      ({ key, transition }) => ({ key, transition }),
    ),
    [{ key: 'AZ-gb19K7Nsapz3kouHu', transition: 'accept' }],
  );
  assert.deepEqual(
    REVIEWED_ISSUES.filter((issue) => ['Web:S6819', 'typescript:S6478'].includes(issue.rule)).map(
      ({ key, transition }) => ({ key, transition }),
    ),
    [
      { key: 'AZ-alMTTTAUVQ8sYgog2', transition: 'accept' },
      { key: 'AZ-alM5ATAUVQ8sYgoiw', transition: 'accept' },
    ],
  );
  assert.deepEqual(
    REVIEWED_ISSUES.filter((issue) => issue.key === 'AZytnJJ1sZaVqOVfTofc').map(
      ({ rule, transition }) => ({ rule, transition }),
    ),
    [{ rule: 'typescript:S6819', transition: 'accept' }],
  );
});

test('rejects malformed reviewed manifests', () => {
  assert.throws(() => validateReviewedIssueManifest(REVIEWED_ISSUES.slice(1)), /exactly 49/i);
  assert.throws(
    () => validateReviewedIssueManifest([...REVIEWED_ISSUES.slice(0, -1), REVIEWED_ISSUES[0]]),
    /repeats key/i,
  );
  assert.throws(
    () =>
      validateReviewedIssueManifest([
        ...REVIEWED_ISSUES.slice(0, -1),
        {
          ...REVIEWED_ISSUES.at(-1),
          transition: 'wontfix',
        },
      ]),
    /invalid metadata/i,
  );
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

test('preflights all metadata before applying exact sorted transitions', async () => {
  const acceptOpen = REVIEWED_ISSUES.find((issue) => issue.transition === 'accept');
  const acceptReviewed = REVIEWED_ISSUES.find(
    (issue) => issue.transition === 'accept' && issue.key !== acceptOpen.key,
  );
  const falsePositiveOpen = REVIEWED_ISSUES.find((issue) => issue.transition === 'falsepositive');
  const falsePositiveReviewed = REVIEWED_ISSUES.find(
    (issue) => issue.transition === 'falsepositive' && issue.key !== falsePositiveOpen.key,
  );
  const current = [
    issueFromManifest(falsePositiveReviewed, 'RESOLVED', {
      resolution: 'FALSE-POSITIVE',
      issueStatus: 'FALSE_POSITIVE',
    }),
    issueFromManifest(acceptOpen, 'OPEN'),
    issueFromManifest(acceptReviewed, 'RESOLVED', {
      resolution: 'WONTFIX',
      issueStatus: 'ACCEPTED',
    }),
    issueFromManifest(falsePositiveOpen, 'CONFIRMED'),
    {
      key: 'historical-reviewed-issue',
      rule: 'typescript:S0001',
      component: `${PROJECT_KEY}:src/historical.ts`,
      status: 'RESOLVED',
      resolution: 'WONTFIX',
      issueStatus: 'ACCEPTED',
    },
  ];
  const requests = [];
  const fetcher = async (url, options = {}) => {
    requests.push({ url: new URL(url), options });
    if (!options.method) return response(page(current));
    return response({});
  };

  const result = await reconcileReviewedSonarIssues({
    fetcher,
    hostUrl: HOST_URL,
    projectKey: PROJECT_KEY,
    token: TOKEN,
  });

  const expectedTransitions = [
    { key: acceptOpen.key, transition: 'accept' },
    { key: falsePositiveOpen.key, transition: 'falsepositive' },
  ].sort((left, right) => left.key.localeCompare(right.key, 'en'));
  assert.deepEqual(
    result.transitions.map(({ key, transition }) => ({ key, transition })),
    expectedTransitions,
  );
  assert.deepEqual(
    result.transitioned,
    expectedTransitions.map((item) => item.key),
  );
  assert.deepEqual(
    result.alreadyReviewed,
    [acceptReviewed.key, falsePositiveReviewed.key].sort((left, right) =>
      left.localeCompare(right, 'en'),
    ),
  );
  assert.equal(result.fixedOrMissing.length, 45);
  assert.deepEqual(result.ignoredReviewed, ['historical-reviewed-issue']);

  assert.equal(requests.length, 3);
  for (const [index, item] of expectedTransitions.entries()) {
    const request = requests[index + 1];
    assert.equal(request.url.pathname, '/api/issues/do_transition');
    assert.equal(request.url.search, '');
    assert.equal(request.options.method, 'POST');
    assert.equal(request.options.headers.Authorization, `Bearer ${TOKEN}`);
    assert.equal(request.options.headers['Content-Type'], 'application/x-www-form-urlencoded');
    assert.equal(request.options.body.get('issue'), item.key);
    assert.equal(request.options.body.get('transition'), item.transition);
    assert.match(request.options.body.get('comment'), /^ShiftPrint reviewed exception:/);
    if (item.transition === 'falsepositive') {
      assert.match(request.options.body.get('comment'), /(compatibility|contrast|openExternal)/i);
    } else {
      assert.match(
        request.options.body.get('comment'),
        /(ARIA|test|Electron|ErrorBoundary|live-region)/i,
      );
    }
  }
});

test('skips fixed or missing and already-reviewed allowlisted issues', () => {
  const accepted = REVIEWED_ISSUES.find((issue) => issue.transition === 'accept');
  const falsePositive = REVIEWED_ISSUES.find((issue) => issue.transition === 'falsepositive');
  const result = planReviewedIssueReconciliation([
    issueFromManifest(accepted, 'ACCEPTED'),
    issueFromManifest(falsePositive, 'FALSE_POSITIVE'),
    {
      key: 'historical-reviewed-issue',
      rule: 'typescript:S0001',
      component: `${PROJECT_KEY}:src/historical.ts`,
      status: 'ACCEPTED',
    },
  ]);

  assert.deepEqual(result.transitions, []);
  assert.deepEqual(
    result.alreadyReviewed,
    [accepted.key, falsePositive.key].sort((left, right) => left.localeCompare(right, 'en')),
  );
  assert.deepEqual(result.ignoredReviewed, ['historical-reviewed-issue']);
  assert.equal(result.fixedOrMissing.length, 47);
});

test('fails closed before mutation on rule or component drift', async () => {
  const expected = REVIEWED_ISSUES[0];
  for (const overrides of [
    { rule: 'typescript:S9999' },
    { component: `${PROJECT_KEY}:src/different.ts` },
  ]) {
    let requestCount = 0;
    await assert.rejects(
      reconcileReviewedSonarIssues({
        fetcher: async (_url, options = {}) => {
          requestCount += 1;
          assert.equal(options.method, undefined);
          return response(page([issueFromManifest(expected, 'OPEN', overrides)]));
        },
        hostUrl: HOST_URL,
        projectKey: PROJECT_KEY,
        token: TOKEN,
      }),
      /no longer matches its expected (rule|component)/i,
    );
    assert.equal(requestCount, 1);
  }
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
            issueFromManifest(REVIEWED_ISSUES[0], 'OPEN'),
            {
              key: 'new-unreviewed-issue',
              rule: 'typescript:S9999',
              component: `${PROJECT_KEY}:src/new-behavior.ts`,
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

test('rejects an allowlisted issue reviewed with the wrong disposition', () => {
  const accepted = REVIEWED_ISSUES.find((issue) => issue.transition === 'accept');
  const falsePositive = REVIEWED_ISSUES.find((issue) => issue.transition === 'falsepositive');
  assert.throws(
    () => planReviewedIssueReconciliation([issueFromManifest(accepted, 'FALSE_POSITIVE')]),
    /unexpected reviewed status/i,
  );
  assert.throws(
    () => planReviewedIssueReconciliation([issueFromManifest(falsePositive, 'ACCEPTED')]),
    /unexpected reviewed status/i,
  );
});

test('fails closed when canonical and legacy Sonar issue states conflict', () => {
  const expected = REVIEWED_ISSUES[0];
  assert.throws(
    () =>
      planReviewedIssueReconciliation([
        issueFromManifest(expected, 'RESOLVED', {
          resolution: 'WONTFIX',
          issueStatus: 'FALSE_POSITIVE',
        }),
      ]),
    /conflicting.*status/i,
  );
  assert.throws(
    () =>
      planReviewedIssueReconciliation([
        issueFromManifest(expected, 'RESOLVED', {
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
      fetcher: async () =>
        response(
          page([issueFromManifest(REVIEWED_ISSUES[0]), issueFromManifest(REVIEWED_ISSUES[0])]),
        ),
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

test('bounds reviewed-issue searches and transitions with abort signals', async () => {
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
          options.signal.addEventListener('abort', () => reject(options.signal.reason), {
            once: true,
          });
        });
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(searchSignal, true);

  let transitionSignal = false;
  await assert.rejects(
    reconcileReviewedSonarIssues({
      hostUrl: HOST_URL,
      projectKey: PROJECT_KEY,
      token: TOKEN,
      requestTimeoutMs: 10,
      fetcher: async (_url, options = {}) => {
        if (!options.method) {
          return response(page([issueFromManifest(REVIEWED_ISSUES[0], 'OPEN')]));
        }
        transitionSignal = options.signal instanceof AbortSignal;
        if (!transitionSignal) throw new Error('missing transition abort signal');
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener('abort', () => reject(options.signal.reason), {
            once: true,
          });
        });
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(transitionSignal, true);
});

test('uses one aggregate deadline across reviewed-issue search and transitions', async () => {
  let clock = 0;
  let transitions = 0;
  await assert.rejects(
    reconcileReviewedSonarIssues({
      hostUrl: HOST_URL,
      projectKey: PROJECT_KEY,
      token: TOKEN,
      timeoutMs: 80,
      now: () => clock,
      fetcher: async (_url, options = {}) => {
        clock += 40;
        if (!options.method) {
          return response(
            page(REVIEWED_ISSUES.slice(0, 2).map((issue) => issueFromManifest(issue, 'OPEN'))),
          );
        }
        transitions += 1;
        return response({});
      },
    }),
    (error) => error instanceof ScannerGateError && error.outcome === SCANNER_OUTCOME.UNAVAILABLE,
  );
  assert.equal(transitions, 1);
});

test('transition failures are deterministic, resumable, and token-safe', async () => {
  const openIssues = REVIEWED_ISSUES.slice(0, 2).map((issue) => issueFromManifest(issue, 'OPEN'));
  const sortedKeys = openIssues
    .map((issue) => issue.key)
    .sort((left, right) => left.localeCompare(right, 'en'));
  const transitioned = [];
  await assert.rejects(
    reconcileReviewedSonarIssues({
      fetcher: async (_url, options = {}) => {
        if (!options.method) return response(page(openIssues));
        const key = options.body.get('issue');
        if (key === sortedKeys[1]) throw new Error(`hostile failure containing ${TOKEN}`);
        transitioned.push(key);
        return response({});
      },
      hostUrl: HOST_URL,
      projectKey: PROJECT_KEY,
      token: TOKEN,
    }),
    (error) => {
      assert.match(error.message, new RegExp(sortedKeys[1]));
      assert.equal(error.message.includes(TOKEN), false);
      return true;
    },
  );
  assert.deepEqual(transitioned, [sortedKeys[0]]);
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

test('the Sonar CI runner reconciles reviewed issues only on test-branch pushes', async () => {
  const [workflow, packageText, runner] = await Promise.all([
    readFile(new URL('../.github/workflows/security.yml', import.meta.url), 'utf8'),
    readFile(new URL('../package.json', import.meta.url), 'utf8'),
    readFile(new URL('./run-sonar-ci.mjs', import.meta.url), 'utf8'),
  ]);
  const packageJson = JSON.parse(packageText);
  assert.equal(
    packageJson.scripts['security:sonar:reviewed'],
    'node scripts/sonar-reviewed-issues.mjs',
  );

  assert.doesNotMatch(workflow, /workflow_dispatch:/);
  assert.match(workflow, /npm run security:sonar:ci --/u);
  const branchGuard = runner.indexOf("if ('branch' in scope)");
  const reconcileStep = runner.indexOf('await reconcile({');
  const openFindingGate = runner.indexOf('await waitForSettledIssues');
  assert.ok(branchGuard >= 0, 'missing branch-only guard');
  assert.ok(reconcileStep > branchGuard, 'reviewed reconciliation must follow branch-only guard');
  assert.ok(openFindingGate > reconcileStep, 'reviewed reconciliation must precede the open gate');
});
