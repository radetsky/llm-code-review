# LLM Code Review System

Automated code review powered by LLM. Works with any OpenAI-compatible API (OpenAI, local Ollama, vLLM, SGLang, etc.).

## Features

- **Security-focused** - Detects credentials, SQL injection, XSS, unsafe functions
- **Customizable rules** - Add project-specific review rules via config
- **Multiple modes** - CLI, Git hooks, GitHub Actions
- **Flexible** - Works with any OpenAI-compatible endpoint
- **Graceful fallback** - Static analysis when LLM unavailable
- **Offline mode** - Run static analysis only, without LLM calls (`--offline`)
- **YAML support** - Reviews GitHub Actions, docker-compose, and other YAML files
- **Accurate line numbers** - All diff lines (context, removed, added) carry explicit line numbers,
  eliminating hallucinated file:line references in LLM output

## Supported File Types

Python, JavaScript, TypeScript, JSX, TSX, Java, C, C++ (`.c`, `.cpp`, `.h`), Rust (`.rs`), Go, YAML (`.yml`, `.yaml`)

> YAML support covers GitHub Actions workflows, docker-compose files, Kubernetes manifests,
> and other infrastructure-as-code files. Configure `review.file_extensions` to add or remove types.
> For Rust, the agent engine gets extra checks (`unsafe`, `unwrap`, `transmute`). See
> `review_config_rust_example.json` for rules of a Rust project.

## Quick Start

### 1. Install

```bash
git clone https://github.com/radetsky/llm-code-review.git
cd llm-code-review
./install.sh
```

### 2. Configure API Key

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export LLM_API_KEY="your-api-key"
```

### 3. Run Review

```bash
cd /path/to/your/project
/path/to/llm-code-review/.venv/bin/python /path/to/llm-code-review/review.py --mode staged
```

## Global Installation (Recommended)

Install the `llm-code-review` command system-wide:

```bash
./install.sh --global
```

Now use from any directory:

```bash
cd ~/my-project
llm-code-review --mode staged        # Review staged changes
llm-code-review --mode all           # Review all uncommitted changes
llm-code-review --test-connection    # Test API connection
```

## Git Hook Integration

Automatically review code before every commit:

```bash
cd ~/my-project
/path/to/llm-code-review/install.sh --hook
```

Or install both global command and hook:

```bash
./install.sh --global --hook
```

## Supported LLM Providers

### OpenAI
```bash
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4"
```

### Your own server (vLLM, SGLang)
```bash
export LLM_API_KEY="any-non-empty-string"
export LLM_BASE_URL="http://your-server:port/v1"
export LLM_MODEL="your-model-name"
```
For a Qwen model, set `llm.extra_body` in `review_config.json` to turn thinking off, for example
`{"chat_template_kwargs": {"enable_thinking": false}}`. The agent engine needs a model that supports
tool calling. Run `llm-code-review --test-tools` to check it.

### Local Ollama
```bash
export LLM_API_KEY="ollama"
export LLM_BASE_URL="http://localhost:11434/v1"
export LLM_MODEL="llama3.2"
```

## CLI Reference

```bash
llm-code-review --mode staged          # Review staged changes (default)
llm-code-review --mode unstaged        # Review unstaged changes
llm-code-review --mode all             # Review all uncommitted changes
llm-code-review --base main --head dev # Compare branches
llm-code-review --format json          # JSON output for CI/CD
llm-code-review --engine agent         # Agentic review: the model reads the repository with tools
llm-code-review --engine hybrid        # The classic engine proposes, the agent verifies
llm-code-review --fail-on critical     # Exit 1 on critical issues (default: always exit 0)
llm-code-review --fail-on warnings     # Exit 1 on warnings too (alias: --strict)
llm-code-review --trace --trace-llm    # Print agent steps and the full LLM exchange
llm-code-review --engine agent --thinking on   # Let the model think in the agent engine (slower)
llm-code-review --verbose              # Detailed output
llm-code-review --offline              # Static analysis only (no API key needed)
llm-code-review --context 15           # Use 15 context lines around each change (default: 10)
llm-code-review --test-connection      # Test API connectivity
```

## Configuration

Edit `review_config.json` to customize rules, or use environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_KEY` | API key for LLM service | Yes |
| `LLM_BASE_URL` | API endpoint URL (required in GitHub Actions: the action ignores `llm.base_url` of the config file) | Yes, unless `llm.base_url` is set |
| `LLM_MODEL` | Model name | No (uses config) |
| `LLM_TIMEOUT` | Request timeout in seconds (default: 180) | No |
| `LLM_MAX_TOKENS_PER_REQUEST` | Max tokens per review chunk (default: 8192) | No |
| `LLM_TOKEN_LIMIT_STRATEGY` | Strategy when exceeding tokens: `chunk`, `truncate`, or `skip` (default: `chunk`) | No |
| `LLM_ENGINE` | `classic`, `agent` or `hybrid` (the flag `--engine` wins) | No |
| `LLM_AGENT_THINKING` | `default`, `on` or `off`: thinking mode of the model for the agent (the flag `--thinking` wins) | No |
| `LLM_MONITORING` | `1` writes one line to the review log for each review | No |
| `LLM_CODE_SUGGESTIONS` | Enable inline code change suggestions: `true` or `false` (default: `false`) | No |

### Custom Review Rules

Add project-specific rules to the `prompt` section in `review_config.json`:

```json
{
  "prompt": {
    "custom_critical_rules": [
      "Rust `unsafe` blocks - block any use of `unsafe` keyword",
      "Raw SQL queries without parameterization"
    ],
    "custom_warnings": [
      "Missing error handling with unwrap()",
      "Clone on large structs"
    ],
    "custom_suggestions": [
      "Use clippy lint suggestions"
    ],
    "additional_instructions": "This is a Rust project. Pay special attention to memory safety."
  }
}
```

**Options:**
- `custom_critical_rules` - Additional rules that the review reports as critical issues
- `custom_warnings` - Additional rules that the review reports as warnings
- `custom_suggestions` - Additional improvement suggestions
- `additional_instructions` - Extra context for the LLM (language, framework, etc.)
- `additional_instructions_file` - Path to a Markdown file with project rules. A relative path starts at the folder of the config file. The file text comes before `additional_instructions`.
- `custom_prompt` - Completely replace the default prompt with placeholders support (see below)

### Custom Prompt with Placeholders

For full control over the review prompt, use `custom_prompt` with placeholders:

```json
{
  "prompt": {
    "custom_prompt": "You are a code reviewer.\n\nCRITICAL:\n{custom_critical_rules}\n\nWARNINGS:\n{custom_warnings}\n\n{additional_instructions}\n\nReview:\n{diff_content}\n\nRespond with CRITICAL:, WARNING:, or SUGGESTION: prefixes.",
    "custom_critical_rules": ["memory leaks", "race conditions"],
    "custom_warnings": ["deprecated API usage"],
    "additional_instructions": "Focus on thread safety"
  }
}
```

**Available placeholders:**
- `{diff_content}` - The git diff to review
- `{custom_critical_rules}` - Formatted list of custom critical rules
- `{custom_warnings}` - Formatted list of custom warnings
- `{custom_suggestions}` - Formatted list of custom suggestions
- `{additional_instructions}` - Additional instructions text
- `{context_lines}` - Number of context lines shown around each change (from config)

All placeholders are optional - use only the ones you need. See `custom_prompt_example.txt` for more examples.

### Large Diff Handling (Chunking)

For large diffs that exceed LLM token limits, the system automatically splits them into smaller chunks and reviews each separately. Configure in `review_config.json`:

```json
{
  "llm": {
    "max_tokens_per_request": 8192,
    "token_limit_strategy": "chunk",
    "chars_per_token": 4
  }
}
```

**Options:**
- `max_tokens_per_request` - Maximum tokens per LLM request (default: 8192)
- `token_limit_strategy` - Strategy for large diffs: `"chunk"` (split and review parts) or `"truncate"` (review only the beginning)
- `chars_per_token` - Character to token ratio for estimation (default: 4)

### Context Lines

Control how many surrounding lines of code are shown alongside each change. More context helps the LLM understand multi-line patterns (try/except blocks, long function calls):

```json
{
  "output": {
    "max_context_lines": 10
  }
}
```

Or override per-run with the CLI flag:

```bash
llm-code-review --mode staged --context 20
```

### Example Configs

- `review_config_example.json` - OpenAI configuration
- `review_config_rust_example.json` - Rust project with unsafe block detection
- `custom_prompt_example.txt` - Custom prompt template examples

## Review Engines

Three engines review a change.

| Engine | How it works | Use it when |
|--------|--------------|-------------|
| `classic` (default) | Sends the diff in one prompt | The change is small and you want the lowest cost and time |
| `hybrid` | The classic engine lists candidate problems. The agent checks each candidate with the tools and keeps the confirmed ones | You want fewer false alarms at a cost that depends on the number of candidates (`hybrid.*` in the config) |
| `agent` | The model reads files, searches the code and checks the history with tools, then sends its findings | A problem can depend on code outside the diff, or you want fewer false alarms |

Choose the engine with `--engine agent`, with `LLM_ENGINE=agent`, or with `"agent": {"enabled": true}`
in `review_config.json`. The flag wins over the variable, and the variable wins over the config.
If the agent fails, the review falls back to the classic engine, and then to static analysis.

**The hybrid engine.** The classic engine reads the whole diff in one request and lists candidate problems.
The agent then checks each candidate with the tools and keeps only the confirmed ones. The cost depends on
the number of candidates, not on the size of the change. On the golden cases it found 95% of the problems
with 90% precision in a median of 7.6 s. If the check fails, the result of the classic engine is used
(`hybrid->classic`). Notices of the classic engine (failed chunks, truncated review) stay in the result.
Candidates over `max_candidates` are listed as not verified.

| Key (config `hybrid`) | Default | Meaning |
|-----|---------|---------|
| `max_candidates` | `10` | The agent checks at most this many candidates |
| `base_steps` | `3` | Steps of the agent that every check gets |
| `steps_per_candidate` | `2` | More steps for each candidate |
| `when_no_candidates` | `accept` | `accept` keeps the empty classic result. `agent` runs a full agent review |

**Tools of the agent.** All tools only read. They use no shell. They refuse paths outside the
repository, symlinks, binary files and secret files (`.env*`, `*.pem`, `id_rsa*` and others).

| Tool | What it does |
|------|--------------|
| `list_changed_files`, `get_diff` | Show the changed files and the numbered diff |
| `read_file` | Read lines of a file (a window of 300 lines if you give no range) |
| `grep`, `find_files`, `find_definition` | Search the repository |
| `git_log`, `git_blame` | Show the history of a file or of some lines |

**Settings** (config key `agent`):

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `false` | Use the agent engine when no flag or variable names an engine |
| `thinking` | `default` | `default` keeps `llm.extra_body`. `on` or `off` sets `enable_thinking` for the agent only. The flag is `--thinking`, the variable is `LLM_AGENT_THINKING` |
| `final_timeout_sec` | `60` | Time for the last request after a budget ends |
| `max_steps` | `20` | Steps of exploration. The flag is `--max-steps` |
| `steps_over_target` | `100` | The step cap is the step target (4 + 2 for each file) plus this number, and never more than `max_steps`. A high value turns the cap off |
| `inline_diff_chars` | `0` | Put the diffs of this many characters in the first message. `0` turns it off (see the note below) |
| `max_total_tokens` | `1000000` | Tokens for one review (the sum over all steps) |
| `wall_timeout_sec` | `300` | Time for one review. The flag is `--wall-timeout` |
| `max_tool_output_chars` | `32000` | The agent receives at most this many characters from one tool call |
| `max_grep_matches` | `50` | Matches that one search returns |
| `read_default_lines` | `300` | Lines that `read_file` returns if you give no range |
| `max_read_scan_bytes` | `5000000` | The agent reads at most this much of one file |

**Thinking.** You can let the model think before each step (`--thinking on`, `agent.thinking`, or the
action input `thinking`). It is off by default, because it did not improve the result in our tests. On the
17 golden cases the agent found all 65 planted problems with thinking off and with thinking on. The median
time doubled (6.3 s and 11.9 s), the tokens grew by 30%, and some real changes took several minutes: one
review of a large change did not finish in 15 minutes. Try it if your model does better with it or if
quality matters more to you than time. The setting applies to the agent only. The classic engine follows
`llm.extra_body`. The server must support `chat_template_kwargs.enable_thinking`, as Qwen on SGLang does.

**Time limit.** `wall_timeout_sec` limits the time for the steps. Each request gets only the time that is
left, and a request that the limit cuts leads to the last request, which gets `final_timeout_sec`. So a
review ends about `wall_timeout_sec + final_timeout_sec` after it starts.

The options `steps_over_target` and `inline_diff_chars` are off by default. In a test on the golden
cases, diffs in the first message made the agent read less code in other files: it found the problem
of the case `cross-file-signature` in 1 of 10 runs, and in 8 of 10 runs without the diffs. The saving
of tokens was small. A step cap did not lower the cost on real changes either.

When a budget ends, the agent must send the findings that it has. A step that only repeats earlier
tool calls counts as a repeat, and two repeats in a row end the review.

**See what the agent does.** `--trace` prints one line for each tool call. `--trace-llm` prints each
request and each response of the model, with the tool calls. The API key is never printed.

**Prompts.** Every prompt is a text file in `prompts/`. Edit a file to change the prompt, and keep the
placeholders, for example `{step_target}`. The agent prompt gets checks for Django, Go and Rust files
(config `prompt.language_blocks`: `"auto"`, a list such as `["rust"]`, or `[]`) and your project rules
(`prompt.custom_*`, `prompt.additional_instructions`).

## Security

- **What leaves the program.** The diff and the files that the agent reads go to the LLM endpoint
  that you configure. The text of the review can go to a public place, for example a pull request
  comment.
- **Read-only tools.** The agent cannot write files or run commands. It cannot read paths outside the
  repository, symlinks, binary files or files that usually hold secrets (key files, `.env*`,
  `secrets.yml`, `terraform.tfstate`, `.aws/`, `.ssh/` and others).
- **Hidden secrets.** Before the review is printed, saved or posted, the program replaces values that
  look like secrets with `[REDACTED]`. The rules are heuristic. They catch known token formats and
  values after names such as `password` or `api_key`. They do not catch every secret. Keep real
  secrets out of files that the agent can read.
- **Text in code is data.** A comment in the code can try to give orders to the model. The prompt
  tells the model not to follow them. A model can still fail, so do not rely on the prompt alone.
- **Forks.** The action does not run with the secrets of your repository on a pull request from a fork.

## Monitoring

Turn on the review log with `"monitoring": {"enabled": true}` in `review_config.json` or with
`LLM_MONITORING=1`. Each review writes one line to `logs/reviews_YYYYMMDD.jsonl` (the folder is
`monitoring.log_dir`). The line holds the engine, the time, the mode, the counts of findings and, for the
agent, the steps, the tokens and the reason why the review stopped. It holds no code.

```bash
python monitor.py report --days 7          # Totals and one part for each engine
python monitor.py report --days 7 --json   # The same as JSON
```

The report shows the median and the 90th percentile of time, steps and tokens, the share of invalid
tool calls, the share of reviews that hit a budget, and the share of reviews that fell back to the
classic engine. If a write to the log fails, the review is not affected.

## Evaluation

`python -m evaluation.run_eval --runs 3` runs the engines on 17 golden cases (changes with a known
problem and clean changes that look risky) and prints recall, precision, false positives, time, steps
and tokens. See `evaluation/README.md` to add your own cases.

## Exit Codes

The review is advisory. By default (`--fail-on none`) the exit code is 0 whenever a
review was produced. The git hooks never block a commit or a push. Use `--fail-on`
in your own scripts if you want a failing exit code.

| Code | Meaning | `--fail-on none` (default) | `--fail-on critical` / `warnings` |
|------|---------|----------------------------|-----------------------------------|
| 0 | No issues | yes | yes |
| 1 | Failing findings | never | critical issues (and warnings with `warnings`) |
| 2 | Warnings only / wrong arguments | wrong arguments only | warnings with `critical`; wrong arguments |
| 3 | LLM unavailable (static fallback) | never (0) | yes |
| 4 | Configuration error | yes | yes |
| 5 | Review skipped (token limit) | never (0) | yes |

## What It Detects

**Critical:**
- Hardcoded credentials, API keys, secrets
- SQL injection, XSS vulnerabilities
- Unsafe functions (`eval()`, `exec()`, `system()`)
- Command injection, buffer overflow risks
- *Plus your custom critical rules*

**Warnings:**
- Code style issues
- Potential bugs
- Missing error handling
- *Plus your custom warnings*

## GitHub Actions Setup Guide

Use the LLM Code Review as a GitHub Action to automatically review pull requests.

### Step 1: Add Secrets to Your Repository

Go to your repository **Settings → Secrets and variables → Actions** and add:

| Secret | Required | Description |
|--------|----------|-------------|
| `LLM_API_KEY` | Yes | Your LLM provider API key |
| `LLM_BASE_URL` | No | API endpoint URL (see provider table below) |
| `LLM_MODEL` | No | Model name (see provider table below) |

**Provider-specific values:**

| Provider | `LLM_API_KEY` | `LLM_BASE_URL` | `LLM_MODEL` |
|----------|---------------|-----------------|--------------|
| OpenAI | `sk-...` | `https://api.openai.com/v1` | `gpt-4` |
| Local / self-hosted | any non-empty string | `http://your-server:port/v1` | your model name |

### Step 2: Create Workflow File

Create `.github/workflows/llm-code-review.yml` in your repository:

```yaml
name: LLM Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  code-review:
    name: AI Code Review
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0

      - name: Run LLM Code Review
        uses: radetsky/llm-code-review@main
        with:
          api_key: ${{ secrets.LLM_API_KEY }}
          base_url: ${{ secrets.LLM_BASE_URL }}
          model: ${{ secrets.LLM_MODEL }}
```

**What this does:**
- Triggers on every pull request (open, update, reopen)
- Checks out the commit of the pull request with the full git history (`fetch-depth: 0`), because the review needs the diff and the files
- Runs the review and posts one summary comment and one review with inline comments

### How the action behaves

The review is advisory. No step of the action fails the job.

- **No blocking.** The action posts reviews with the event `COMMENT` only. It never requests changes.
  Do not add the job of this action to the required checks of a branch.
- **Failures are comments.** If the review cannot run (the model is down, the output is not valid, the
  time limit is over), the pull request comment says so in one line. The job stays green.
- **Forks.** A pull request from a fork has no access to secrets. The action sees an empty `api_key`
  and skips the review without an error. Do not use the event `pull_request_target` to get around this:
  that event gives your secrets to code from the fork.
- **One comment for each run.** A new commit updates the summary comment. Inline comments appear only
  on lines that the diff of the pull request shows. A comment that already exists is not posted again.
- **Safe inputs.** The action passes every input to its scripts through environment variables.
  An input is never run as code.

### Step 3: Advanced Configuration

Add optional inputs to customize behavior:

```yaml
      - name: Run LLM Code Review
        id: review
        uses: radetsky/llm-code-review@main
        with:
          api_key: ${{ secrets.LLM_API_KEY }}
          base_url: ${{ secrets.LLM_BASE_URL }}
          model: ${{ secrets.LLM_MODEL }}
          engine: agent               # classic (default), agent or hybrid
          max_steps: '20'             # agent only (optional)
          wall_timeout: '300'         # agent only, seconds (optional)
          post_comment: 'true'        # Post the summary comment (default: true)
          inline_comments: 'true'     # Post inline comments on code lines (default: true)
          code_suggestions: 'true'    # Let the review propose code changes (default: true)

      - name: Check results
        if: always()
        env:
          STATUS: ${{ steps.review.outputs.status }}
          OUTCOME: ${{ steps.review.outputs.outcome }}
          CRITICAL: ${{ steps.review.outputs.critical_count }}
        run: echo "Status: $STATUS, outcome: $OUTCOME, critical: $CRITICAL"
```

Pass values to `run:` scripts through `env:`, as in this example. Do not write `${{ ... }}` inside a script.

### Choosing an engine

| Engine | What it does | When to use it |
|--------|--------------|----------------|
| `classic` (default) | Sends the diff in one prompt | Small changes, the lowest cost and time |
| `hybrid` | The classic engine lists candidates, the agent checks each one | Fewer false alarms than classic at a lower cost than the agent |
| `agent` | The model reads files, searches the code and checks the history with tools, then submits findings | Changes whose problems depend on code outside the diff; fewer false alarms |

On a set of golden cases (`evaluation/`) the agent found more problems and made far fewer false
alarms, but it takes more time and tokens. The hybrid engine is between them: on small and medium
changes it takes seconds and a few thousand tokens, and it removes most false alarms of the classic engine. If the agent fails, the action falls back to the classic
engine and then to static analysis. To run both engines on one pull request, use two jobs with different
`comment_tag` values (see `.github/workflows/llm_code_review.yml`).

### Action Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `api_key` | LLM API key. If empty, the review is skipped | No | - |
| `base_url` | API endpoint URL. The action ignores `llm.base_url` in the config file, because a pull request can change that file | Yes | - |
| `model` | Model name | No | config |
| `engine` | `classic`, `agent` or `hybrid` | No | `classic` |
| `thinking` | Agent: `default`, `on` or `off` (the thinking mode of the model) | No | config (`agent.thinking`) |
| `max_steps` | Agent: maximum number of steps | No | config (`agent.max_steps`) |
| `wall_timeout` | Agent: time limit in seconds | No | config (`agent.wall_timeout_sec`) |
| `mode` | `staged`, `unstaged` or `all` (instead of `base`/`head`) | No | - |
| `base`, `head` | Commits of the diff (found for pull requests and pushes) | No | - |
| `post_comment` | Post the summary comment and the inline review | No | `true` |
| `inline_comments` | Post inline comments on the changed lines | No | `true` |
| `code_suggestions` | Let the review propose code changes | No | `true` |
| `context` | Number of context lines around each change | No | `10` |
| `comment_tag` | A short name that keeps the comments of two reviews apart | No | - |

The inputs `strict` and `fail_on_critical` do not exist any more. The action never fails the job.

### Action Outputs

| Output | Description |
|--------|-------------|
| `status` | Technical status: `success`, `model_unavailable`, `skipped` or `error` |
| `outcome` | Result of the review: `success`, `warnings`, `critical`, or `none` if the review did not run |
| `critical_count` | Number of critical issues |
| `warning_count` | Number of warnings |
| `suggestion_count` | Number of suggestions |
| `engine` | Engine that made the result: `classic`, `agent`, `hybrid`, `hybrid->classic` or `agent->classic` |
| `result_file` | Path to the JSON result file |

See the `examples/` folder for more workflow examples.

## Development

```bash
pip install -r requirements.txt ruff==0.17.3
ruff check . && ruff format --check .
python -m pytest -q
node --test scripts/post_review.test.js
```

The workflow `.github/workflows/ci.yml` runs the same checks on Python 3.11 and 3.13.

## Troubleshooting

```bash
# Test API connection
llm-code-review --test-connection

# Verbose output
llm-code-review --mode staged --verbose

# Offline static analysis (no API key needed)
llm-code-review --mode staged --offline

# Health check
python monitor.py health
```

## Project Structure

```
llm-code-review/
├── action.yml                    # GitHub Action definition
├── install.sh                    # Installation script
├── review.py                     # CLI entry point
├── review_core.py                # Classic engine: LLM integration, chunking & prompt building
├── agent_core.py                 # Agent engine: tool-calling loop, budgets, validation
├── hybrid_core.py                # Hybrid engine: classic candidates, agent check
├── redaction.py                  # Hides secrets in the text of a review
├── monitor.py                    # Review log and report
├── agent_tools.py                # Read-only tools of the agent
├── agent_prompt.py               # Builds the system prompt of the agent
├── diff_parser.py                # Diff parsing and safe file access (RepoSource)
├── prompts.py, prompts/          # Every prompt is a text file
├── config.py                     # Configuration management
├── static_analyzer.py            # Fallback analysis
├── scripts/                      # Scripts of the GitHub Action (post_review.js, read_result.py)
├── evaluation/                   # Golden cases and the evaluation runner
├── review_config.json            # Your configuration
├── review_config_example.json    # OpenAI example
├── review_config_rust_example.json  # Rust project example
├── custom_prompt_example.txt     # Custom prompt template examples
├── examples/
│   ├── workflow-basic.yml        # Basic GitHub Actions workflow
│   ├── workflow-advanced.yml     # Advanced workflow with all options
│   └── workflow-example.yml      # Pull request and push workflow
└── .github/workflows/
    ├── ci.yml                    # Lint and tests (no secrets)
    └── llm_code_review.yml       # Self-test workflow (uses local action)
```

## License

MIT