'use strict';

/*
 * Post the result of a review to a pull request.
 *
 * The action calls these functions from actions/github-script. All values
 * come from the environment, never from text that the workflow inserts into
 * the script.
 *
 * postSummary:       one comment on the pull request. A new run updates it.
 * postInlineReview:  one review with inline comments. It posts only on lines
 *                    that the diff of the pull request shows.
 *
 * The review is advisory. This script never fails the job.
 */

const fs = require('fs');

const MARKER = '<!-- llm-code-review -->';
const TAG_PATTERN = /^[A-Za-z0-9_.-]{1,30}$/;
const LEGACY_TITLE = 'LLM Code Review';
const MAX_COMMENT_CHARS = 60000;
const MAX_INLINE_COMMENTS = 50;
const MAX_RANGE = 500;
const LOCATION = /^\W*?`?([\w./\\-]+\.\w+)`?:(\d+)(?:-(\d+))?:\s*([\s\S]*)$/;

const SEVERITIES = [
  { key: 'critical_issues', label: 'Critical issues', icon: '🚨' },
  { key: 'warnings', label: 'Warnings', icon: '⚠️' },
  { key: 'suggestions', label: 'Suggestions', icon: '💡' },
];

// A mention in the text of the model must not notify a person.
function neutralize(text) {
  return String(text).replace(/@(?=[A-Za-z0-9_-])/g, '@​');
}

// A tag lets two reviews (for example two engines) keep separate comments.
function cleanTag(tag) {
  return tag && TAG_PATTERN.test(tag) ? tag : '';
}

function markerFor(tag) {
  const clean = cleanTag(tag);
  return clean ? `<!-- llm-code-review:${clean} -->` : MARKER;
}

function readResult(file) {
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    return data && typeof data === 'object' ? data : null;
  } catch (error) {
    return null;
  }
}

function describeOutcome(meta) {
  if (meta.error) return { icon: ':x:', text: 'The review did not run' };
  if (meta.status === 'model_unavailable') {
    return { icon: ':warning:', text: 'Model unavailable (static analysis used)' };
  }
  if (meta.status === 'skipped') {
    return { icon: ':information_source:', text: 'Skipped (the change is too large)' };
  }
  if (meta.outcome === 'critical') return { icon: ':rotating_light:', text: 'Critical issues found' };
  if (meta.outcome === 'warnings') return { icon: ':warning:', text: 'Warnings found' };
  if (meta.status === 'success') return { icon: ':white_check_mark:', text: 'No issues found' };
  return { icon: ':grey_question:', text: meta.status || 'Unknown' };
}

function statsLine(result, meta) {
  const parts = [`Engine: ${meta.engine || 'unknown'}`];
  const stats = result && result.agent_stats;
  if (stats && typeof stats.steps === 'number') {
    parts.push(`${stats.steps} steps`);
    if (typeof stats.tokens === 'number') parts.push(`${Math.round(stats.tokens / 1000)}k tokens`);
    if (typeof stats.duration_sec === 'number') parts.push(`${Math.round(stats.duration_sec)} s`);
    if (stats.fallback) parts.push(`fell back to ${stats.fallback}`);
  }
  return parts.join(', ');
}

function buildSummary(result, meta) {
  const { icon, text } = describeOutcome(meta);
  const tag = cleanTag(meta.tag);
  const title = tag ? `${LEGACY_TITLE} (${tag})` : LEGACY_TITLE;
  const lines = [markerFor(tag), `## ${icon} ${title}`, '', `**Result:** ${text}`, ''];

  if (meta.error) {
    lines.push('The review could not be done. The reason:', '', '```', neutralize(meta.error), '```', '');
  } else if (result) {
    lines.push(
      '| Category | Count |',
      '|----------|-------|',
      `| Critical issues | ${(result.critical_issues || []).length} |`,
      `| Warnings | ${(result.warnings || []).length} |`,
      `| Suggestions | ${(result.suggestions || []).length + (result.code_suggestions || []).length} |`,
      ''
    );
    for (const { key, label, icon: itemIcon } of SEVERITIES) {
      const items = result[key] || [];
      if (items.length) {
        lines.push(`### ${label}`);
        for (const item of items) lines.push(`- ${itemIcon} ${neutralize(item)}`);
        lines.push('');
      }
    }
    const codeSuggestions = result.code_suggestions || [];
    if (codeSuggestions.length) {
      lines.push('### Code suggestions');
      for (const s of codeSuggestions) {
        const where = s.line_start === s.line_end ? s.line_start : `${s.line_start}-${s.line_end}`;
        lines.push(`- 🔧 \`${s.file}:${where}\`: ${neutralize(s.description)}`);
      }
      lines.push('');
    }
    if (result.fallback_used) {
      lines.push('> :information_source: *Static analysis was used because the model was not available.*', '');
    }
  }

  lines.push('---', `<sub>${statsLine(result, meta)}. This review is advisory. [${LEGACY_TITLE}](https://github.com/radetsky/llm-code-review)</sub>`);
  let body = lines.join('\n');
  if (body.length > MAX_COMMENT_CHARS) {
    body = body.slice(0, MAX_COMMENT_CHARS) + '\n\n*The comment is cut because it is too long.*';
  }
  return body;
}

// The new-file line numbers that a patch of GitHub shows (added and context lines).
function patchRightLines(patch) {
  const lines = new Set();
  if (!patch) return lines;
  let right = 0;
  for (const row of patch.split('\n')) {
    const hunk = row.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      right = parseInt(hunk[1], 10);
    } else if (row.startsWith('+')) {
      lines.add(right++);
    } else if (row.startsWith(' ')) {
      lines.add(right++);
    }
    // A "-" row and a "\ No newline" row do not move the new-file counter.
  }
  return lines;
}

function collectComments(result) {
  const comments = [];
  for (const { key, icon } of SEVERITIES) {
    for (const item of (result && result[key]) || []) {
      const match = typeof item === 'string' ? item.match(LOCATION) : null;
      if (!match) continue;
      const start = parseInt(match[2], 10);
      const end = match[3] ? parseInt(match[3], 10) : start;
      comments.push({ path: match[1].replace(/^\.\//, ''), start, end, body: `${icon} ${neutralize(match[4])}` });
    }
  }
  for (const s of (result && result.code_suggestions) || []) {
    comments.push({
      path: String(s.file).replace(/^\.\//, ''),
      start: s.line_start,
      end: s.line_end,
      body: `💡 ${neutralize(s.description)}\n\n\`\`\`suggestion\n${s.suggested_code}\n\`\`\``,
      isSuggestion: true,
    });
  }
  return comments;
}

// Keep the comments that GitHub accepts. GitHub rejects the whole review if one
// comment points to a line outside the diff, so every line must be on the right
// side of the diff. A suggestion block replaces lines, so all its lines must be there.
function selectInline(comments, patchesByPath) {
  const inline = [];
  const skipped = [];
  const seen = new Set();
  for (const c of comments) {
    const start = Math.min(c.start, c.end);
    const end = Math.max(c.start, c.end);
    const allowed = patchRightLines(patchesByPath.get(c.path));
    let comment = null;

    let rangeOk = Number.isInteger(start) && Number.isInteger(end) && end - start <= MAX_RANGE;
    for (let n = start; rangeOk && n <= end; n++) rangeOk = allowed.has(n);

    if (rangeOk) {
      comment = { path: c.path, line: end, side: 'RIGHT', body: c.body };
      if (start < end) {
        comment.start_line = start;
        comment.start_side = 'RIGHT';
      }
    } else if (!c.isSuggestion && allowed.has(end)) {
      comment = { path: c.path, line: end, side: 'RIGHT', body: c.body };
    } else if (!c.isSuggestion && allowed.has(start)) {
      comment = { path: c.path, line: start, side: 'RIGHT', body: c.body };
    }

    if (!comment) {
      skipped.push(c);
      continue;
    }
    const key = `${comment.path}:${comment.line}:${comment.body}`;
    if (!seen.has(key)) {
      seen.add(key);
      inline.push(comment);
    }
  }
  return { inline, skipped };
}

async function postSummary({ github, context, core, env }) {
  const result = readResult(env.RESULT_FILE);
  const meta = {
    status: env.REVIEW_STATUS,
    outcome: env.REVIEW_OUTCOME,
    engine: env.REVIEW_ENGINE,
    error: env.REVIEW_ERROR || (result ? '' : 'The result file could not be read.'),
    tag: env.COMMENT_TAG,
  };
  const body = buildSummary(result, meta);
  const { owner, repo } = context.repo;
  const issue_number = context.issue.number;
  try {
    const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number, per_page: 100 });
    const marker = markerFor(env.COMMENT_TAG);
    const tagged = cleanTag(env.COMMENT_TAG) !== '';
    // Without a tag the action also finds the comment of an older version.
    const existing = comments.find(
      (c) =>
        c.user &&
        c.user.type === 'Bot' &&
        c.body &&
        (c.body.includes(marker) || (!tagged && c.body.includes(LEGACY_TITLE) && !/<!-- llm-code-review:/.test(c.body)))
    );
    if (existing) {
      await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
      core.info('Updated the review comment');
    } else {
      await github.rest.issues.createComment({ owner, repo, issue_number, body });
      core.info('Created the review comment');
    }
  } catch (error) {
    core.warning(`Could not post the review comment: ${error.message}`);
  }
}

async function postInlineReview({ github, context, core, env }) {
  const result = readResult(env.RESULT_FILE);
  if (!result || env.REVIEW_ERROR) {
    core.info('No result for inline comments');
    return;
  }
  const comments = collectComments(result);
  if (!comments.length) {
    core.info('No finding has a file and a line');
    return;
  }
  const { owner, repo } = context.repo;
  const pull_number = context.issue.number;
  try {
    const files = await github.paginate(github.rest.pulls.listFiles, { owner, repo, pull_number, per_page: 100 });
    const patches = new Map(files.map((f) => [f.filename, f.patch]));
    const { inline, skipped } = selectInline(comments, patches);

    const old = await github.paginate(github.rest.pulls.listReviewComments, { owner, repo, pull_number, per_page: 100 });
    const known = new Set(old.map((c) => `${c.path}:${c.line}:${c.body}`));
    const fresh = inline.filter((c) => !known.has(`${c.path}:${c.line}:${c.body}`)).slice(0, MAX_INLINE_COMMENTS);

    core.info(`Inline comments: ${fresh.length} new, ${inline.length - fresh.length} known or over the limit, ${skipped.length} outside the diff`);
    if (!fresh.length) return;

    await github.rest.pulls.createReview({
      owner,
      repo,
      pull_number,
      commit_id: env.HEAD_SHA,
      event: 'COMMENT',
      body: `${LEGACY_TITLE}${cleanTag(env.COMMENT_TAG) ? ` (${cleanTag(env.COMMENT_TAG)})` : ''}: ${fresh.length} inline comment(s). This review is advisory.`,
      comments: fresh,
    });
    core.info('Created the review');
  } catch (error) {
    core.warning(`Could not post inline comments: ${error.message}`);
  }
}

module.exports = {
  MARKER,
  neutralize,
  cleanTag,
  markerFor,
  buildSummary,
  patchRightLines,
  collectComments,
  selectInline,
  postSummary,
  postInlineReview,
};
