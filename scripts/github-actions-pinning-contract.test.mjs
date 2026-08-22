import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';

const { test } = await import('node:test');
const workflowsUrl = new URL('../.github/workflows/', import.meta.url);

test('every external GitHub Action is pinned to a full commit SHA', async () => {
  const files = (await readdir(workflowsUrl)).filter((name) => /\.ya?ml$/u.test(name));

  for (const file of files) {
    const workflow = await readFile(new URL(file, workflowsUrl), 'utf8');
    for (const line of workflow.split(/\r?\n/u)) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('uses:')) continue;
      const action = trimmed.slice('uses:'.length).trim().split(/\s+/u, 1)[0];
      if (action.startsWith('./')) continue;
      const separator = action.lastIndexOf('@');
      assert.notEqual(separator, -1, `${file}: missing action revision for ${action}`);
      assert.match(
        action.slice(separator + 1),
        /^[0-9a-f]{40}$/u,
        `${file}: external action must use a full commit SHA: ${action}`,
      );
    }
  }
});
