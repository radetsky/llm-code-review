# CHANGES

## [Unreleased]

## [0.1.5] - 2026-04-28

### Added
- Rust (`.rs`), Ruby (`.rb`), C# (`.cs`), PHP (`.php`), Kotlin (`.kt`), Swift (`.swift`), Shell (`.sh`), and SQL (`.sql`) added to the default list of reviewed file extensions in `review_config.json`, `review_config_example.json`, and `DEFAULT_CONFIG`.
- `CRITICAL_RULE_TEXTS` and `WARNING_RULE_TEXTS` mappings in `LLMReviewer` — symbolic rule names in config now map to concrete prompt text lines. Previously `review.critical_rules` and `review.warning_rules` were defined but never used.
- `command_injection` and `buffer_overflow` added to the default `critical_rules` list (were already mentioned in the hardcoded prompt but absent from config).
- `input_validation` added to the default `warning_rules` list.

### Changed
- `review.critical_rules` and `review.warning_rules` config fields are now functional. They control which built-in check categories appear in the LLM prompt. Project-specific rules go into `prompt.custom_critical_rules` and `prompt.custom_warnings` as before, and are appended after the selected built-in rules.
- CRITICAL ISSUES and WARNINGS sections in the system prompt are now fully dynamic — built from `review.critical_rules`/`review.warning_rules` (mapped to text) plus `prompt.custom_*` (raw text). Previously the built-in rule lines were hardcoded in the prompt regardless of config.
- `--config-file` CLI flag now correctly loads and applies the specified config file. Previously the flag was parsed by argparse but the loaded config was ignored — the tool always used defaults or `review_config.json`.
- Malformed JSON in any config file now causes an immediate fatal error with a descriptive message (exit code 4) instead of silently falling back to built-in defaults.
- Explicitly specified `--config-file` pointing to a non-existent path now causes a fatal error (exit code 4).
- Unrecognized or abbreviated CLI arguments (e.g. `--config` instead of `--config-file`) now cause an immediate error instead of being silently matched to a similar-looking flag. (`argparse allow_abbrev=False`).
- Custom prompt placeholder names updated: `{custom_critical_rules}` → `{critical_rules_section}`, `{custom_warnings}` → `{warning_rules_section}`, `{custom_suggestions}` → `{suggestions_section}`.
- `review_config_rust_example.json`: replaced `sql_injection`/`xss_vulnerabilities` with `buffer_overflow`/`command_injection` in `critical_rules`; reduced `custom_warnings` to one high-confidence rule (`unwrap()`/`expect()` without a safety comment); cleared `custom_suggestions`.

### Fixed
- `review_config_rust_example.json` contained invalid JSON (extra closing brace, trailing commas in arrays), causing silent fallback to default config on every run.

## [0.1.4] - 2026-03-27

### Added
- `max_tokens` input in GitHub Action to override max tokens per LLM request per workflow run.
- `timeout` input in GitHub Action to override LLM request timeout per workflow run.
- `LLM_MAX_RESPONSE_TOKENS` environment variable to control max tokens in LLM response (default: 16384).
- `llm.max_response_tokens` config key (default: 16384).

### Changed
- Default `llm.timeout` increased from 180 to 600 seconds to accommodate slow providers and large diffs with chunking.
- Default `max_tokens_per_request` increased to 32768 (see v0.1.3 notes).
- LLM requests now use `system` + `user` message roles instead of a single `user` message, giving reviewer instructions higher priority in the model's context window.
- `max_tokens` is now explicitly passed in every LLM API call, preventing unbounded response generation.

## [0.1.3] - 2026-03-27

### Added
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
- Default `output.max_context_lines` increased from 3 to 10 to reduce false positives caused by
  partially visible try/except blocks and multiline function calls.
- Default `max_tokens_per_request` increased from 4096 to 32768 to handle large PRs without
  chunking on modern LLMs with wide context windows (e.g. Claude Sonnet 4 supports 200K tokens).
  Override with `LLM_MAX_TOKENS_PER_REQUEST` environment variable if a lower limit is needed.
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

### TODO
- VSCode extension integration: provide real-time code review feedback directly in the editor.
- PyCharm/IntelliJ IDEA plugin integration: code review inspections and quick-fixes.
