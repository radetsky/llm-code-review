# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM-powered code review system with three integration modes:
- **Terminal CLI** (`review.py`) - Direct command-line usage
- **Git hooks** - Pre-commit/pre-push automation
- **GitHub Actions** - CI/CD integration with PR comments

Uses OpenAI-compatible LLM API (configurable model and endpoint).

### Supported Languages
Python, JavaScript, TypeScript, JSX, TSX, Java, C, C++, Rust, Go

## Common Commands

```bash
# Activate virtual environment (Python 3.11-3.13; 3.15 breaks pydantic-core build)
source .python-venv/bin/activate.fish

# Load API key (fish shell)
source .env.fish

# Install dependencies
pip install -r requirements.txt

# Run code review
python review.py --mode staged              # Review staged changes
python review.py --mode unstaged            # Review unstaged changes
python review.py --mode all                 # Review all changes from HEAD
python review.py --base main --head feature # Review between branches
python review.py --format json              # JSON output for CI/CD
python review.py --engine agent             # Agentic review (tools); default is classic
python review.py --engine hybrid            # Classic proposes, the agent verifies
python review.py --fail-on critical         # Exit 1 on critical issues (default: none, advisory)
python review.py --fail-on warnings         # Exit 1 on warnings too (alias: --strict)
python review.py --trace                    # Print agent steps / tool calls to stderr
python review.py --trace-llm                # Print full LLM requests and responses to stderr
python review.py --verbose                  # Verbose output
python review.py --test-connection          # Test LLM API connectivity

# Install git hooks
python install_hooks.py

# Code formatting and linting
ruff format .                               # Format all Python files
ruff check .                                # Lint all Python files
ruff check --fix .                          # Auto-fix linting issues

# Evaluation on golden cases (calls the LLM)
python -m evaluation.run_eval --list                        # List the cases
python -m evaluation.run_eval --runs 3                      # Both engines, 3 runs for each case
python -m evaluation.run_eval --engines agent --cases sql-injection   # One engine, one case
python -m evaluation.history --list                         # Real changes from git history, by size
python -m evaluation.history --per-bucket 3                 # Cost of both engines on those changes

# Monitoring
python monitor.py health                    # System health check
python monitor.py report --days 7           # Report by engine: time, steps, tokens (needs monitoring.enabled)
python monitor.py report --days 7 --json    # The same report as JSON
```

## Architecture

```
review.py           CLI entry point, argument parsing, output formatting
    |
    v
review_core.py      LLM integration, retry logic, response parsing
    |               Uses OpenAI client with custom base URL
    v
diff_parser.py      Git diff extraction and structured parsing
    |
    v
config.py           Configuration management (review_config.json)
    |
    v
static_analyzer.py  Fallback security analysis when LLM unavailable

agent_core.py       Agent loop (engine "agent"): budgets, forced submit_review,
    |               Qwen quirks, finding validation, tracing
    v
agent_tools.py      Read-only tools (read_file, grep, git_blame, ...)
    |               hybrid_core.py: classic candidates, agent check (engine "hybrid")
    |
    v
diff_parser.py      RepoSource: safe file access for index / worktree / git rev
```

Prompts: every text that tells the model what to do is a file in `prompts/`
(`agent_system.md`, `agent_task.md`, `agent_nudge.md`, `agent_budget_exhausted.md`,
`agent_project_rules.md`, `agent_lang_{django,go,rust}.md`, `rule_docstrings.md`,
`classic_review.md`, `classic_code_suggestions.md`, `hybrid_system.md`, `hybrid_task.md`). `prompts.py` loads them.
`agent_prompt.py` builds the agent system prompt: it adds the language checks
(config `prompt.language_blocks`: `"auto"`, a list, or `[]`) and the project rules
(`prompt.custom_*`, `prompt.additional_instructions`, `review.check_docstrings`).
Edit a file to change the prompt. Keep the placeholders, for example `{step_target}`.
Agent prompts follow ASD-STE100. The tool descriptions and the notes in tool
results are still in `agent_tools.py` and `agent_core.py`.

`redaction.py` hides secrets in the text of a review. `review.py` calls `redact_result` for every
engine before it prints, logs or posts the result. Do not output review text before that call.

Engines: `classic` (single prompt, default), `agent` (tool-calling loop) and `hybrid`
(`hybrid_core.py`: classic proposes candidates, the agent verifies them).
Degradation: agent -> classic (same model) -> static analysis.

## GitHub Action

`action.yml` is a composite action. The review is advisory: no step fails the job.
An empty `api_key` (a pull request from a fork) skips the action. A failed review
becomes one line in the pull request comment. The action posts reviews with the
event `COMMENT` only: one summary comment (`scripts/post_review.js`, function
`postSummary`) and one review with inline comments (`postInlineReview`) on lines
that the diff shows. Rules for changes to `action.yml`:

- Never write `${{ ... }}` in a `run:` or `script:` block. Pass every value
  through `env:`. `test_action.py` checks this.
- The action runs `scripts/read_result.py` to read the result of `review.py`.
- `requirements-action.txt` must list every third-party module that the runtime
  files import. `test_action.py` checks this.
- JavaScript tests: `node --test scripts/post_review.test.js` (also run by pytest).

## Exit Codes

The review is advisory. With the default `--fail-on none` the exit code is 0
whenever a review was produced (see `review_outcome` / `status` in the output).

| Code | Meaning | `--fail-on none` (default) | `critical` / `warnings` |
|------|---------|----------------------------|-------------------------|
| 0 | Success | yes | yes |
| 1 | Failing findings | never | critical (and warnings for `warnings`) |
| 2 | Warnings only / usage error | usage error only | warnings with `critical`; usage error |
| 3 | Model unavailable (static fallback) | never (0) | yes |
| 4 | Configuration error | yes | yes |
| 5 | Review skipped (token limit) | never (0) | yes |

Git hooks (`hooks/pre-commit`, `hooks/pre-push`) never block: they always exit 0.

## Configuration

- `review_config.json` - Main configuration file
- `review_config_example.json` - Example config for OpenAI

### Environment Variables (take precedence over config file)
- `LLM_API_KEY` - API key for LLM service
- `LLM_BASE_URL` - Override base URL (optional)
- `LLM_MODEL` - Override model name (optional)
- `LLM_TIMEOUT` - Request timeout in seconds (default: 180)
- `LLM_MAX_TOKENS_PER_REQUEST` - Max tokens per review chunk (default: 4096)
- `LLM_ENGINE` - `agent`, `classic` or `hybrid` (CLI `--engine` wins; then `agent.enabled` in config)
- `LLM_AGENT_THINKING` - `default`, `on` or `off`: the thinking mode of the model for the agent (CLI `--thinking` wins; then `agent.thinking`)
- `LLM_MONITORING` - `1` writes one line to the review log for each review (config `monitoring.enabled`)
- `LLM_TOKEN_LIMIT_STRATEGY` - Strategy when exceeding tokens: `chunk`, `truncate`, or `skip` (default: `chunk`)

### Config sections

- `agent.*` - budgets and limits of the agent engine (`max_steps`, `max_total_tokens`,
  `wall_timeout_sec`, `max_tool_output_chars`, `read_default_lines`, `max_read_scan_bytes`, ...)
- `prompt.*` - project rules, `additional_instructions` and `language_blocks`
- `monitoring.*` - `enabled` and `log_dir` of the review log (`monitor.py` reads it)

### Current Setup
- Model: `qwen3.8-27b` (corporate, SGLang, 128k context, thinking disabled via `llm.extra_body`)
- Base URL: set via `LLM_BASE_URL` (not stored in the repo)

## Code Conventions

- **All code, comments, docstrings and documentation must be in English, written in ASD-STE100 Simplified Technical English** (short sentences, active voice, simple present tense, one term for one meaning, no idioms). Apply this to all new and changed text.
- Always communicate with the user in Ukrainian
- Uses fish shell for environment configuration
- Code formatted with `ruff format` and linted with `ruff check`
