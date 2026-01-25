# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM-powered code review system with three integration modes:
- **Terminal CLI** (`review.py`) - Direct command-line usage
- **Git hooks** - Pre-commit/pre-push automation
- **GitHub Actions** - CI/CD integration with PR comments

Uses OpenAI-compatible LLM API (configurable model and endpoint).

## Common Commands

```bash
# Activate virtual environment
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
python review.py --strict                   # Block on warnings too
python review.py --verbose                  # Verbose output
python review.py --test-connection          # Test LLM API connectivity

# Install git hooks
python install_hooks.py

# Monitoring
python monitor.py health                    # System health check
python monitor.py report --days 7           # Usage report
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
```

## Exit Codes

| Code | Meaning | Git Action |
|------|---------|------------|
| 0 | Success | Allow |
| 1 | Critical issues | Block |
| 2 | Warnings only | Allow |
| 3 | Model unavailable | Allow (static fallback) |
| 4 | Configuration error | Block |

## Configuration

- `review_config.json` - Main configuration file
- `review_config_example.json` - Example config for OpenAI

### Environment Variables (take precedence over config file)
- `LLM_API_KEY` - API key for LLM service
- `LLM_BASE_URL` - Override base URL (optional)
- `LLM_MODEL` - Override model name (optional)

### Current Setup
- Model: `anthropic/claude-sonnet-4`
- Base URL: `https://api.opencode.ai/v1`

## Code Conventions

- **All code comments must be in English**
- Communication with users can be in Ukrainian
- Uses fish shell for environment configuration
