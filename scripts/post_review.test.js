'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const lib = require('./post_review.js');

const PATCH = [
  '@@ -1,4 +1,5 @@',
  ' line one',
  '-old two',
  '+new two',
  '+new three',
  ' line four',
  '\\ No newline at end of file',
  '@@ -20,2 +21,3 @@ def f():',
  ' ctx',
  '+added',
  ' ctx2',
].join('\n');

function writeResult(data) {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'llm-')), 'result.json');
  fs.writeFileSync(file, typeof data === 'string' ? data : JSON.stringify(data));
  return file;
}

function makeGithub({ comments = [], files = [], reviewComments = [], failOn = {} } = {}) {
  const calls = { create: [], update: [], review: [] };
  const maybeFail = (name) => {
    if (failOn[name]) throw new Error(`${name} failed`);
  };
  const rest = {
    issues: {
      listComments: 'listComments',
      createComment: async (a) => (maybeFail('createComment'), calls.create.push(a)),
      updateComment: async (a) => (maybeFail('updateComment'), calls.update.push(a)),
    },
    pulls: {
      listFiles: 'listFiles',
      listReviewComments: 'listReviewComments',
      createReview: async (a) => (maybeFail('createReview'), calls.review.push(a)),
    },
  };
  const data = { listComments: comments, listFiles: files, listReviewComments: reviewComments };
  return {
    rest,
    calls,
    paginate: async (fn) => {
      maybeFail(fn);
      return data[fn];
    },
  };
}

function makeCore() {
  const log = { info: [], warning: [] };
  return { log, info: (m) => log.info.push(m), warning: (m) => log.warning.push(m) };
}

const context = { repo: { owner: 'o', repo: 'r' }, issue: { number: 7 } };

function env(result, extra = {}) {
  return {
    RESULT_FILE: writeResult(result),
    REVIEW_STATUS: 'success',
    REVIEW_OUTCOME: 'warnings',
    REVIEW_ENGINE: 'agent',
    REVIEW_ERROR: '',
    HEAD_SHA: 'abc123',
    ...extra,
  };
}

// ---------------------------------------------------------------- helpers

test('neutralize stops mentions', () => {
  assert.equal(lib.neutralize('ask @alice and @org/team'), 'ask @​alice and @​org/team');
  assert.equal(lib.neutralize('no mention @ here'), 'no mention @ here');
});

test('patchRightLines follows the new file numbers', () => {
  const lines = lib.patchRightLines(PATCH);
  assert.deepEqual([...lines].sort((a, b) => a - b), [1, 2, 3, 4, 21, 22, 23]);
  assert.equal(lines.has(5), false);
  assert.equal(lib.patchRightLines(undefined).size, 0);
  assert.equal(lib.patchRightLines('').size, 0);
});

test('collectComments reads locations, ranges and code suggestions', () => {
  const comments = lib.collectComments({
    critical_issues: ['app/db.py:12: bad query'],
    warnings: ['./a.py:3-5: range text: with colon', '- `src/lib.rs`:9: unwrap', 'no location here'],
    suggestions: ['b.go:7: nice'],
    code_suggestions: [{ file: 'c.py', line_start: 4, line_end: 6, description: 'd', suggested_code: 'x = 1' }],
  });
  assert.deepEqual(
    comments.map((c) => [c.path, c.start, c.end]),
    [['app/db.py', 12, 12], ['a.py', 3, 5], ['src/lib.rs', 9, 9], ['b.go', 7, 7], ['c.py', 4, 6]]
  );
  assert.ok(comments[1].body.endsWith('range text: with colon'));
  assert.ok(comments[4].body.includes('```suggestion\nx = 1\n```'));
  assert.equal(comments[4].isSuggestion, true);
  assert.deepEqual(lib.collectComments(null), []);
});

test('selectInline keeps lines that the diff shows', () => {
  const patches = new Map([['a.py', PATCH]]);
  const make = (start, end, extra = {}) => ({ path: 'a.py', start, end, body: 'b', ...extra });
  const { inline, skipped } = lib.selectInline(
    [make(2, 2), make(50, 50), make(3, 4), make(3, 9), make(22, 22, { body: 'c' })],
    patches
  );
  assert.deepEqual(inline.map((c) => [c.line, c.start_line]), [[2, undefined], [4, 3], [3, undefined], [22, undefined]]);
  assert.deepEqual(skipped.map((c) => c.start), [50]);
  assert.ok(inline.every((c) => c.side === 'RIGHT'));
});

test('selectInline does not post a suggestion that leaves the diff', () => {
  const patches = new Map([['a.py', PATCH]]);
  const part = { path: 'a.py', start: 3, end: 9, body: 'b', isSuggestion: true };
  const whole = { path: 'a.py', start: 3, end: 4, body: 'b2', isSuggestion: true };
  const { inline, skipped } = lib.selectInline([part, whole], patches);
  assert.equal(skipped.length, 1);
  assert.equal(inline.length, 1);
  assert.equal(inline[0].start_line, 3);
});

test('selectInline skips files without a patch and removes duplicates', () => {
  const patches = new Map([['a.py', PATCH], ['big.bin', undefined]]);
  const c = { path: 'a.py', start: 2, end: 2, body: 'same' };
  const { inline, skipped } = lib.selectInline(
    [c, { ...c }, { path: 'big.bin', start: 1, end: 1, body: 'x' }, { path: 'none.py', start: 1, end: 1, body: 'x' }],
    patches
  );
  assert.equal(inline.length, 1);
  assert.equal(skipped.length, 2);
});

test('selectInline refuses a huge range', () => {
  const patches = new Map([['a.py', PATCH]]);
  const { inline } = lib.selectInline([{ path: 'a.py', start: 1, end: 100000, body: 'x', isSuggestion: true }], patches);
  assert.equal(inline.length, 0);
});

// ---------------------------------------------------------------- summary text

test('buildSummary shows counts, items and the engine', () => {
  const text = lib.buildSummary(
    {
      critical_issues: ['a.py:1: crit'],
      warnings: ['a.py:2: warn'],
      suggestions: ['a.py:3: sug'],
      code_suggestions: [{ file: 'a.py', line_start: 4, line_end: 5, description: 'cs', suggested_code: 'x' }],
      agent_stats: { steps: 5, tokens: 12000, duration_sec: 20.4 },
    },
    { status: 'success', outcome: 'critical', engine: 'agent', error: '' }
  );
  assert.ok(text.startsWith(lib.MARKER));
  assert.ok(text.includes('Critical issues found'));
  assert.ok(text.includes('| Suggestions | 2 |'));
  assert.ok(text.includes('a.py:1: crit') && text.includes('`a.py:4-5`: cs'));
  assert.ok(text.includes('Engine: agent, 5 steps, 12k tokens, 20 s'));
  assert.ok(text.includes('advisory'));
});

test('buildSummary reports an error in one place and no counts', () => {
  const text = lib.buildSummary(null, { status: 'error', outcome: 'none', engine: 'unknown', error: 'exit 4: no key' });
  assert.ok(text.includes('The review did not run'));
  assert.ok(text.includes('exit 4: no key'));
  assert.ok(!text.includes('| Category |'));
});

test('buildSummary handles every status', () => {
  const base = { critical_issues: [], warnings: [], suggestions: [] };
  const run = (status, outcome) => lib.buildSummary(base, { status, outcome, engine: 'classic', error: '' });
  assert.ok(run('success', 'success').includes('No issues found'));
  assert.ok(run('success', 'warnings').includes('Warnings found'));
  assert.ok(run('model_unavailable', 'none').includes('Model unavailable'));
  assert.ok(run('skipped', 'none').includes('Skipped'));
  assert.ok(run('weird', 'none').includes('weird'));
});

test('buildSummary neutralizes mentions and cuts a long text', () => {
  const text = lib.buildSummary(
    { warnings: ['a.py:1: ping @alice'], critical_issues: [], suggestions: [] },
    { status: 'success', outcome: 'warnings', engine: 'classic', error: 'by @bob' }
  );
  assert.ok(!text.includes('@alice') && !text.includes('@bob'));
  const long = lib.buildSummary(
    { warnings: Array(5000).fill('a.py:1: ' + 'x'.repeat(50)), critical_issues: [], suggestions: [] },
    { status: 'success', outcome: 'warnings', engine: 'classic', error: '' }
  );
  assert.ok(long.length <= 60100);
  assert.ok(long.includes('is cut because it is too long'));
});

test('buildSummary says that the static analysis was used', () => {
  const text = lib.buildSummary(
    { critical_issues: [], warnings: [], suggestions: [], fallback_used: true },
    { status: 'model_unavailable', outcome: 'none', engine: 'classic', error: '' }
  );
  assert.ok(text.includes('Static analysis was used'));
});

// ---------------------------------------------------------------- postSummary

const RESULT = { critical_issues: [], warnings: ['a.py:2: warn'], suggestions: [], code_suggestions: [] };

test('postSummary creates one comment', async () => {
  const github = makeGithub();
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT) });
  assert.equal(github.calls.create.length, 1);
  assert.equal(github.calls.create[0].issue_number, 7);
  assert.equal(github.calls.update.length, 0);
});

test('postSummary updates the comment of the bot', async () => {
  const github = makeGithub({
    comments: [
      { id: 1, user: { type: 'User' }, body: `${lib.MARKER} fake from a person` },
      { id: 2, user: { type: 'Bot' }, body: `${lib.MARKER}\nold text` },
    ],
  });
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT) });
  assert.equal(github.calls.update.length, 1);
  assert.equal(github.calls.update[0].comment_id, 2);
  assert.equal(github.calls.create.length, 0);
});

test('postSummary finds the comment of an older version', async () => {
  const github = makeGithub({ comments: [{ id: 5, user: { type: 'Bot' }, body: '## :x: LLM Code Review\nold' }] });
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT) });
  assert.equal(github.calls.update[0].comment_id, 5);
});

test('postSummary does not take the comment of another bot', async () => {
  const github = makeGithub({ comments: [{ id: 8, user: { type: 'Bot' }, body: 'Thanks. LLM Code Review is a nice tool.' }] });
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT) });
  assert.equal(github.calls.update.length, 0);
  assert.equal(github.calls.create.length, 1);
});

test('a suggestion with backticks gets a longer fence', () => {
  const [c] = lib.collectComments({
    code_suggestions: [{ file: 'a.md', line_start: 1, line_end: 1, description: 'd', suggested_code: 'x\n```js\ny\n```' }],
  });
  assert.ok(c.body.includes('````suggestion\nx\n```js\ny\n```\n````'));
});

test('the summary does not let a file name break the code span', () => {
  const text = lib.buildSummary(
    { code_suggestions: [{ file: 'a`b.py', line_start: 1, line_end: 1, description: 'd', suggested_code: 'x' }] },
    { status: 'success', outcome: 'success', engine: 'classic' }
  );
  assert.ok(text.includes('`ab.py:1`'));
});

test('postSummary shows the error text when the result file is missing', async () => {
  const github = makeGithub();
  await lib.postSummary({
    github,
    context,
    core: makeCore(),
    env: env(RESULT, { RESULT_FILE: '/no/such/file.json', REVIEW_STATUS: 'error', REVIEW_OUTCOME: 'none' }),
  });
  assert.ok(github.calls.create[0].body.includes('The review did not run'));
});

test('postSummary never throws', async () => {
  const core = makeCore();
  const github = makeGithub({ failOn: { listComments: true } });
  await lib.postSummary({ github, context, core, env: env(RESULT) });
  assert.equal(core.log.warning.length, 1);
  const github2 = makeGithub({ failOn: { createComment: true } });
  await lib.postSummary({ github: github2, context, core, env: env(RESULT) });
  assert.equal(core.log.warning.length, 2);
});

// ---------------------------------------------------------------- postInlineReview

const FILES = [{ filename: 'a.py', patch: PATCH }];
const FINDINGS = {
  critical_issues: ['a.py:2: crit'],
  warnings: ['a.py:22: warn', 'a.py:99: outside'],
  suggestions: [],
  code_suggestions: [],
};

test('postInlineReview creates one review with all comments and never requests changes', async () => {
  const github = makeGithub({ files: FILES });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(FINDINGS) });
  assert.equal(github.calls.review.length, 1);
  const review = github.calls.review[0];
  assert.equal(review.event, 'COMMENT');
  assert.equal(review.commit_id, 'abc123');
  assert.equal(review.pull_number, 7);
  assert.deepEqual(review.comments.map((c) => c.line), [2, 22]);
  assert.ok(review.comments.every((c) => c.path === 'a.py' && c.side === 'RIGHT'));
});

test('postInlineReview does not repeat known comments', async () => {
  const known = [{ path: 'a.py', line: 2, body: '🚨 crit' }];
  const github = makeGithub({ files: FILES, reviewComments: known });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(FINDINGS) });
  assert.deepEqual(github.calls.review[0].comments.map((c) => c.line), [22]);
  const github2 = makeGithub({
    files: FILES,
    reviewComments: [...known, { path: 'a.py', line: 22, body: '⚠️ warn' }],
  });
  await lib.postInlineReview({ github: github2, context, core: makeCore(), env: env(FINDINGS) });
  assert.equal(github2.calls.review.length, 0);
});

test('postInlineReview posts nothing when no line is in the diff', async () => {
  const github = makeGithub({ files: [{ filename: 'other.py', patch: PATCH }] });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(FINDINGS) });
  assert.equal(github.calls.review.length, 0);
});

test('postInlineReview posts nothing for an error, an empty result or a missing file', async () => {
  const github = makeGithub({ files: FILES });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(FINDINGS, { REVIEW_ERROR: 'boom' }) });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env({ critical_issues: [], warnings: [], suggestions: [] }) });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(FINDINGS, { RESULT_FILE: '/no/file' }) });
  assert.equal(github.calls.review.length, 0);
});

test('postInlineReview limits the number of comments', async () => {
  const patch = '@@ -1,0 +1,100 @@\n' + Array.from({ length: 100 }, (_, i) => `+l${i}`).join('\n');
  const result = { critical_issues: [], warnings: Array.from({ length: 80 }, (_, i) => `a.py:${i + 1}: w${i}`), suggestions: [] };
  const github = makeGithub({ files: [{ filename: 'a.py', patch }] });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(result) });
  assert.equal(github.calls.review[0].comments.length, 50);
});

test('postInlineReview never throws', async () => {
  for (const name of ['listFiles', 'listReviewComments', 'createReview']) {
    const core = makeCore();
    const github = makeGithub({ files: FILES, failOn: { [name]: true } });
    await lib.postInlineReview({ github, context, core, env: env(FINDINGS) });
    assert.equal(core.log.warning.length, 1, name);
  }
});

test('a suggestion block is posted only when its lines are in the diff', async () => {
  const result = {
    critical_issues: [],
    warnings: [],
    suggestions: [],
    code_suggestions: [
      { file: 'a.py', line_start: 2, line_end: 3, description: 'ok', suggested_code: 'x = 1' },
      { file: 'a.py', line_start: 4, line_end: 8, description: 'out', suggested_code: 'y = 2' },
    ],
  };
  const github = makeGithub({ files: FILES });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(result) });
  const comments = github.calls.review[0].comments;
  assert.equal(comments.length, 1);
  assert.deepEqual([comments[0].start_line, comments[0].line], [2, 3]);
  assert.ok(comments[0].body.includes('```suggestion'));
});

// ---------------------------------------------------------------- comment tag

test('cleanTag accepts a short plain name only', () => {
  assert.equal(lib.cleanTag('agent'), 'agent');
  assert.equal(lib.cleanTag('v1.2_x-y'), 'v1.2_x-y');
  for (const bad of ['', undefined, 'a b', '--> <script>', 'x'.repeat(31), 'a\nb']) {
    assert.equal(lib.cleanTag(bad), '', String(bad));
  }
});

test('markerFor keeps the old marker without a tag', () => {
  assert.equal(lib.markerFor(''), lib.MARKER);
  assert.equal(lib.markerFor('agent'), '<!-- llm-code-review:agent -->');
  assert.equal(lib.markerFor('bad tag'), lib.MARKER);
});

test('buildSummary shows the tag in the marker and in the title', () => {
  const meta = { status: 'success', outcome: 'success', engine: 'agent', error: '', tag: 'agent' };
  const text = lib.buildSummary({ critical_issues: [], warnings: [], suggestions: [] }, meta);
  assert.ok(text.startsWith('<!-- llm-code-review:agent -->'));
  assert.ok(text.includes('## :white_check_mark: LLM Code Review (agent)'));
});

test('two tags keep two comments', async () => {
  const comments = [
    { id: 1, user: { type: 'Bot' }, body: '<!-- llm-code-review:classic -->\nclassic text' },
    { id: 2, user: { type: 'Bot' }, body: '<!-- llm-code-review:agent -->\nagent text' },
  ];
  const github = makeGithub({ comments });
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT, { COMMENT_TAG: 'agent' }) });
  assert.equal(github.calls.update[0].comment_id, 2);
  const github2 = makeGithub({ comments });
  await lib.postSummary({ github: github2, context, core: makeCore(), env: env(RESULT, { COMMENT_TAG: 'classic' }) });
  assert.equal(github2.calls.update[0].comment_id, 1);
});

test('a tagged run creates its own comment and does not take the untagged one', async () => {
  const github = makeGithub({ comments: [{ id: 9, user: { type: 'Bot' }, body: `${lib.MARKER}\nuntagged` }] });
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT, { COMMENT_TAG: 'agent' }) });
  assert.equal(github.calls.update.length, 0);
  assert.equal(github.calls.create.length, 1);
});

test('an untagged run does not take a tagged comment', async () => {
  const github = makeGithub({ comments: [{ id: 9, user: { type: 'Bot' }, body: '<!-- llm-code-review:agent -->\n## LLM Code Review (agent)' }] });
  await lib.postSummary({ github, context, core: makeCore(), env: env(RESULT) });
  assert.equal(github.calls.update.length, 0);
  assert.equal(github.calls.create.length, 1);
});

test('the review body names the tag', async () => {
  const github = makeGithub({ files: FILES });
  await lib.postInlineReview({ github, context, core: makeCore(), env: env(FINDINGS, { COMMENT_TAG: 'agent' }) });
  assert.ok(github.calls.review[0].body.startsWith('LLM Code Review (agent):'));
});

test('buildSummary tells that secrets are hidden', () => {
  const meta = { status: 'success', outcome: 'warnings', engine: 'agent', error: '' };
  const base = { critical_issues: [], warnings: ['a.py:1: x'], suggestions: [] };
  assert.ok(lib.buildSummary({ ...base, redacted_count: 3 }, meta).includes('3 value(s) that look like secrets are hidden'));
  assert.ok(!lib.buildSummary({ ...base, redacted_count: 0 }, meta).includes('secrets are hidden'));
  assert.ok(!lib.buildSummary(base, meta).includes('secrets are hidden'));
});
