# LLM Code Review System

Automated code review powered by LLM. Works with any OpenAI-compatible API (OpenAI, Anthropic via OpenRouter, local Ollama, etc.).

## Features

- **Security-focused** - Detects credentials, SQL injection, XSS, unsafe functions
- **Customizable rules** - Add project-specific review rules via config
- **Multiple modes** - CLI, Git hooks, GitHub Actions
- **Flexible** - Works with any OpenAI-compatible endpoint
- **Graceful fallback** - Static analysis when LLM unavailable

## Quick Start

### 1. Install

```bash
git clone https://github.com/pashokred/cl-llm.git
cd cl-llm
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
/path/to/cl-llm/.venv/bin/python /path/to/cl-llm/review.py --mode staged
```

## Global Installation (Recommended)

Install the `llm-review` command system-wide:

```bash
./install.sh --global
```

Now use from any directory:

```bash
cd ~/my-project
llm-review --mode staged        # Review staged changes
llm-review --mode all           # Review all uncommitted changes
llm-review --test-connection    # Test API connection
```

## Git Hook Integration

Automatically review code before every commit:

```bash
cd ~/my-project
/path/to/cl-llm/install.sh --hook
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
llm-review --mode staged          # Review staged changes (default)
llm-review --mode unstaged        # Review unstaged changes
llm-review --mode all             # Review all uncommitted changes
llm-review --base main --head dev # Compare branches
llm-review --format json          # JSON output for CI/CD
llm-review --strict               # Block on warnings too
llm-review --verbose              # Detailed output
llm-review --test-connection      # Test API connectivity
```

## Configuration

Edit `review_config.json` to customize rules, or use environment variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_KEY` | API key for LLM service | Yes |
| `LLM_BASE_URL` | API endpoint URL | No (uses config) |
| `LLM_MODEL` | Model name | No (uses config) |

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
- `custom_prompt` - Completely replace the default prompt (advanced)

### Example Configs

- `review_config_example.json` - OpenAI configuration
- `review_config_rust_example.json` - Rust project with unsafe block detection

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

## GitHub Actions

Add to your workflow:

```yaml
- name: LLM Code Review
  env:
    LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
  run: |
    pip install openai
    python review.py --mode staged --format json
```

Set `LLM_API_KEY` in repository secrets.

## Troubleshooting

```bash
# Test API connection
llm-review --test-connection

# Verbose output
llm-review --mode staged --verbose

# Health check
python monitor.py health
```

## Project Structure

```
cl-llm/
├── install.sh                    # Installation script
├── review.py                     # CLI entry point
├── review_core.py                # LLM integration & prompt building
├── config.py                     # Configuration management
├── static_analyzer.py            # Fallback analysis
├── review_config.json            # Your configuration
├── review_config_example.json    # OpenAI example
└── review_config_rust_example.json  # Rust project example
```

## License

MIT