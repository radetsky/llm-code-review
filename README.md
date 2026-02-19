# LLM Code Review System

Automated code review powered by LLM. Works with any OpenAI-compatible API (OpenAI, Anthropic via OpenRouter, local Ollama, etc.).

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

Python, JavaScript, TypeScript, JSX, TSX, Java, C, C++, Go, YAML (`.yml`, `.yaml`)

> YAML support covers GitHub Actions workflows, docker-compose files, Kubernetes manifests,
> and other infrastructure-as-code files. Configure `review.file_extensions` to add or remove types.

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

### Anthropic (via OpenRouter)
```bash
export LLM_API_KEY="your-openrouter-key"
export LLM_BASE_URL="https://openrouter.ai/api/v1"
export LLM_MODEL="anthropic/claude-sonnet-4"
```

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
llm-code-review --strict               # Block on warnings too
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
| `LLM_BASE_URL` | API endpoint URL | No (uses config) |
| `LLM_MODEL` | Model name | No (uses config) |
| `LLM_TIMEOUT` | Request timeout in seconds (default: 180) | No |
| `LLM_MAX_TOKENS_PER_REQUEST` | Max tokens per review chunk (default: 8192) | No |
| `LLM_TOKEN_LIMIT_STRATEGY` | Strategy when exceeding tokens: `chunk`, `truncate`, or `skip` (default: `chunk`) | No |
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
- `custom_critical_rules` - Additional rules that block commits
- `custom_warnings` - Additional rules that warn but allow commits
- `custom_suggestions` - Additional improvement suggestions
- `additional_instructions` - Extra context for the LLM (language, framework, etc.)
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

## Exit Codes

| Code | Meaning | Git Hook Action |
|------|---------|-----------------|
| 0 | No issues | Allow commit |
| 1 | Critical issues | Block commit |
| 2 | Warnings only | Allow commit |
| 3 | LLM unavailable | Allow (static fallback) |
| 4 | Config error | Block commit |

## What It Detects

**Critical (blocks commit):**
- Hardcoded credentials, API keys, secrets
- SQL injection, XSS vulnerabilities
- Unsafe functions (`eval()`, `exec()`, `system()`)
- Command injection, buffer overflow risks
- *Plus your custom critical rules*

**Warnings (allows commit):**
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
| Anthropic (OpenRouter) | OpenRouter key | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4` |
| Anthropic (OpenCode) | OpenCode key | `https://api.opencode.ai/v1` | `anthropic/claude-sonnet-4` |
| Local / self-hosted | any non-empty string | `http://your-server:port/v1` | your model name |

### Step 2: Create Workflow File

Create `.github/workflows/llm-code-review.yml` in your repository:

```yaml
name: LLM Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  code-review:
    name: AI Code Review
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
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
- Checks out full git history (`fetch-depth: 0`) for diff analysis
- Runs LLM code review and posts results as a PR comment

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
          strict: 'true'              # Fail on warnings too (default: false)
          post_comment: 'true'         # Post review as PR comment (default: true)
          fail_on_critical: 'true'     # Fail action on critical issues (default: true)
          inline_comments: 'true'      # Post inline comments on code lines (default: true)
          code_suggestions: 'true'    # Enable code change suggestions (default: true)

      - name: Check results
        if: always()
        run: |
          echo "Status: ${{ steps.review.outputs.status }}"
          echo "Critical: ${{ steps.review.outputs.critical_count }}"
          echo "Warnings: ${{ steps.review.outputs.warning_count }}"
          echo "Suggestions: ${{ steps.review.outputs.suggestion_count }}"
```

### Action Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `api_key` | LLM API key | Yes | - |
| `base_url` | API endpoint URL | No | config |
| `model` | Model name | No | config |
| `strict` | Fail on warnings | No | `false` |
| `post_comment` | Post PR comment | No | `true` |
| `fail_on_critical` | Fail on critical issues | No | `true` |
| `inline_comments` | Post inline review comments on code lines | No | `true` |
| `code_suggestions` | Enable inline code change suggestions | No | `true` |
| `context` | Number of context lines around each change | No | `10` |

### Action Outputs

| Output | Description |
|--------|-------------|
| `status` | Review status: success, warnings, critical, error |
| `critical_count` | Number of critical issues |
| `warning_count` | Number of warnings |
| `suggestion_count` | Number of suggestions |
| `result_file` | Path to JSON result file |

See `examples/` folder for more workflow examples.

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
├── review_core.py                # LLM integration, chunking & prompt building
├── config.py                     # Configuration management
├── static_analyzer.py            # Fallback analysis
├── review_config.json            # Your configuration
├── review_config_example.json    # OpenAI example
├── review_config_rust_example.json  # Rust project example
├── custom_prompt_example.txt     # Custom prompt template examples
├── examples/
│   ├── workflow-basic.yml        # Basic GitHub Actions workflow
│   └── workflow-advanced.yml     # Advanced workflow with all options
└── .github/workflows/
    └── llm_code_review.yml       # Self-test workflow (uses local action)
```

## License

MIT