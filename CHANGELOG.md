# CHANGES

The release 0.1.0 waits for the decision about the default engine.

## [Unreleased]

### Added
- Secrets in the text of a review are hidden before the review leaves the program (`redaction.py`).
  The rules cover private keys, tokens of known formats (GitHub, Slack, Stripe, AWS, Google, JWT and
  others), `Bearer` headers, passwords in URLs and values that follow a name such as `password` or
  `api_key`. Both engines use it. The JSON output has `redacted_count`, and the pull request comment
  tells how many values are hidden. Code in a suggested change is checked with the rules for known
  token formats only, so a correct code line is not changed.
- A larger deny list for the tools of the agent: key stores, `terraform.tfstate`, `*.tfvars`,
  `secrets.yml` and similar files, `local_settings.py`, service account files, and the folders `.ssh`,
  `.aws`, `.kube`, `.gnupg` and `.docker`.
- The agent prompt says that text in files, diffs, comments and tool results is data, not
  instructions, and that a finding must not contain the value of a secret.
- Two options for the cost of the agent, both off by default: `agent.inline_diff_chars` (put diffs in
  the first message) and `agent.steps_over_target` (a step cap close to the step target). Measurements
  showed no gain: diffs in the first message cut recall on a case that needs code from other files (1 of
  10 runs against 8 of 10), and the cap did not lower the cost on real changes.
- `python -m evaluation.history` measures the cost of both engines on real changes from the git
  history of a repository, in four size classes: time, tokens, steps, reviews that hit a budget,
  fallbacks and the number of findings.
- A golden case `injection-in-comment` and the evaluation metric "findings that write a planted
  secret". Both engines pass the case.
- Agent engine (`--engine agent`, `LLM_ENGINE=agent`, config `agent.enabled`). The model reads the
  repository with read-only tools, then sends its findings with `submit_review`. The tools are
  `list_changed_files`, `get_diff`, `read_file`, `grep`, `find_files`, `find_definition`, `git_log`
  and `git_blame`. The tools use no shell. They check each path and refuse `..`, symlinks, binary
  files and secret files such as `.env` and `*.pem`.
- Budgets for the agent: `agent.max_steps`, `agent.max_total_tokens`, `agent.wall_timeout_sec`, with
  the flags `--max-steps` and `--wall-timeout`. When a budget ends, the agent must submit its findings.
  The agent also stops after two steps that only repeat earlier calls.
- The agent runs up to four tool calls from one message, and it checks each finding against the diff:
  the file and the line must be in the diff, and repeated findings are removed.
- Degradation chain: agent, then classic (same model), then static analysis.
- `RepoSource` in `diff_parser.py`: safe, read-only access to the files of the index, the working
  tree or a git revision. `read_file` reads a large file as a stream, so a line deep in a file
  is available and the file is not loaded into memory (`agent.max_read_scan_bytes`).
- `--trace` prints the steps of the agent. `--trace-llm` prints each request and each response of the
  model, with the tool calls and the reasoning text.
- Every prompt is a text file in `prompts/`. Optional language checks for Django, Go and Rust
  (`prompt.language_blocks`) and the project rules (`prompt.custom_*`) go into the agent prompt.
- `--fail-on none|critical|warnings` (default `none`). `--strict` stays as an alias of
  `--fail-on warnings`.
- Monitoring: `monitoring.enabled` (or `LLM_MONITORING=1`) writes one line to a log for each review.
  `python monitor.py report` shows the engines side by side: time, steps, tokens, invalid tool calls,
  reviews that hit a budget and reviews that fell back to the classic engine. `--json` prints JSON.
- `evaluation/`: 16 golden cases and `python -m evaluation.run_eval`. The script runs both engines
  and reports recall, precision, false positives, time, steps and tokens.
- GitHub Action inputs `engine`, `max_steps`, `wall_timeout` and `comment_tag`, and the outputs
  `outcome` and `engine`.
- GitHub Action: inline comments are posted in one review. The action posts only on lines that the
  diff shows, it does not repeat a comment that exists, and it updates its summary comment.
- `--context N` CLI flag to override the number of diff context lines per run (e.g. `--context 20`).
- `context` input in GitHub Action to override context lines per workflow run.
- `output.max_context_lines` config key (default: 10) to control how many surrounding lines are
  sent to the LLM alongside each change. Previously hardcoded to 3.
- Git diff now uses `-U{N}` flag matching `output.max_context_lines`, so raw diff and the
  LLM-formatted output always use the same context width.
- All diff lines (context before, removed, context after) now carry explicit line numbers in the
  LLM-formatted output. Previously only added lines were numbered, causing the LLM to hallucinate
  file:line references for context and removed lines.
- `context_after` lines are now included in the LLM-formatted diff. Previously they were parsed
  but never sent to the LLM.
- `.yml` and `.yaml` added to the list of reviewed file types, covering GitHub Actions workflows,
  docker-compose, Kubernetes manifests, and similar infrastructure files.
- Inline code change suggestions: LLM can now generate concrete code replacements using
  GitHub-native `suggestion` blocks. In GitHub Actions these render as "Apply suggestion" buttons.
  Controlled by `code_suggestions` action input (default: true) and
  `review.enable_code_suggestions` config / `LLM_CODE_SUGGESTIONS` env var.
- Inline PR review comments: GitHub Action posts review comments directly on specific code lines
  (file:line format) via Pull Request Review API, in addition to the existing summary comment.
  Controlled by `inline_comments` input (default: true).

### Changed
- The review is advisory. The default exit code is 0 when a review was produced (`--fail-on none`).
  The git hooks and `install.sh` never block a commit or a push.
- GitHub Action: no step fails the job. A missing API key (for example a pull request from a fork)
  skips the review. A failed review is one line in the pull request comment. The action posts
  reviews with the event `COMMENT` only. Each input goes through the environment of a step, so an
  input cannot run as code.
- The option `--config-file` now works. Before, `review.py` ignored it.
- `ReviewConfig` no longer shares its nested default values between objects.
- Default `output.max_context_lines` increased from 3 to 10 to reduce false positives caused by
  partially visible try/except blocks and multiline function calls.
- Default `max_tokens_per_request` increased from 4096 to 8192 to handle larger diffs that result
  from wider context windows.
- Prompt now explicitly tells the LLM how many context lines are included and instructs it not to
  flag constructs (try/except, multiline calls, class definitions) that extend beyond the visible area.
- Tightened LLM prompt to reduce noise: requires file:line references, prohibits generic advice,
  reports only issues visible in the actual diff.
- `--offline` CLI flag: run static analysis only, without any LLM calls. No API key or network
  connection required. Automatically forces `check_docstrings: True`. Mutually exclusive with
  `--test-connection`.
- Docstring suggestions: detects functions, methods, and classes missing documentation comments
  in added code. Supports Python docstrings, JSDoc (JS/TS/JSX/TSX), Javadoc, Doxygen (C/C++),
  godoc (Go). Works in both LLM and static analysis modes. Controlled by
  `review.check_docstrings` config option.

### Fixed
- The statistics of the agent counted an unknown tool call as a call and as an invalid call.
- `DiffParser.parse_diff` gave the last hunk of each file to the next file in a diff of many files.
  A removed line that starts with `--`, or an added line that starts with `++`, was read as a file
  header and moved the line numbers.
- `requirements-action.txt` did not list `json5`. The action would fail on import.
- `python monitor.py report` failed when there were no reviews, and nothing wrote the log.
- `DiffParser` refuses a git reference that starts with `-`.

### Removed
- GitHub Action inputs `strict` and `fail_on_critical`, the step "Check for failures" and the review
  event `REQUEST_CHANGES`.
- `llm.fallback_model` in `review_config.json`.

### TODO
- VSCode extension integration: provide real-time code review feedback directly in the editor.
- PyCharm/IntelliJ IDEA plugin integration: code review inspections and quick-fixes.
