# Copilot Instructions for cl-llm

## Project Overview

LLM-powered code review system with multiple integration modes:
- **Terminal CLI** (`review.py`) - Direct command-line usage
- **Git hooks** - Pre-commit/pre-push automation
- **GitHub Actions** - CI/CD integration with PR comments

Uses OpenAI-compatible API against configurable endpoints.

## Environment Setup

```bash
# Activate Python virtual environment
source .python-venv/bin/activate.fish

# Set API key
export LLM_API_KEY="your-api-key"

# Optional: Override base URL and model
export LLM_BASE_URL="https://api.opencode.ai/v1"
export LLM_MODEL="anthropic/claude-sonnet-4"
```

## Code Patterns

### API Client Configuration

Configuration is loaded from `review_config.json`, but environment variables take precedence:

```python
from config import ReviewConfig

config = ReviewConfig()

# These methods check env vars first, then fall back to config file
api_key = config.get_api_key()    # LLM_API_KEY env var
base_url = config.get_base_url()  # LLM_BASE_URL env var
model = config.get_model()        # LLM_MODEL env var
```

### Making LLM Requests

The system uses OpenAI-compatible client:

```python
from openai import OpenAI

client = OpenAI(
    base_url=config.get_base_url(),
    api_key=config.get_api_key()
)

response = client.chat.completions.create(
    model=config.get_model(),
    messages=[{"role": "user", "content": "Your prompt"}]
)
```

## Important Notes

- **Never commit API keys**: Use environment variables
- **All code comments must be in English**
- **Shell**: Project uses fish shell for environment configuration
