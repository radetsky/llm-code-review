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
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4"

# Optional: choose the review engine (classic, agent or hybrid)
export LLM_ENGINE="agent"

# Optional: Increase timeout for large reviews (default: 180 seconds)
export LLM_TIMEOUT="300"
```

## Code Patterns

### API Client Configuration

Configuration is loaded from `review_config.json`, but environment variables take precedence:

```python
from config import ReviewConfig

config = ReviewConfig()

# These methods check env vars first, then fall back to config file
api_key = config.get_api_key()      # LLM_API_KEY env var
base_url = config.get_base_url()    # LLM_BASE_URL env var
model = config.get_model()          # LLM_MODEL env var
timeout = config.get_timeout()      # LLM_TIMEOUT env var
```

### Making LLM Requests

The system uses OpenAI-compatible client:

```python
from openai import OpenAI

client = OpenAI(
    base_url=config.get_base_url(),
    timeout=config.get_timeout(),
    api_key=config.get_api_key()
)

response = client.chat.completions.create(
    model=config.get_model(),
    messages=[{"role": "user", "content": "Your prompt"}]
)
```

## Engines and Prompts

- `classic` sends the diff in one prompt (`review_core.py`). `agent` lets the model read the
  repository with read-only tools (`agent_core.py`, `agent_tools.py`). `hybrid` (`hybrid_core.py`)
  lets the classic engine list candidates and the agent check them. `config.ENGINES` lists the engines.
- Every prompt is a text file in `prompts/`. `prompts.py` loads them. Keep the placeholders.
- The review is advisory. Do not add code that blocks a commit, a push or a pull request.
- Write code, comments, docstrings and documentation in ASD-STE100 Simplified Technical English.
- Run `python -m pytest` before you commit. Run `ruff format` and `ruff check` on your files.
  CI (`.github/workflows/ci.yml`) pins ruff 0.17.3 and runs the Python and JavaScript tests.
- Secrets: `redaction.redact_result` runs before any review text leaves the program.

## Important Notes

- **Never commit API keys**: Use environment variables
- **All code comments must be in English**
- **Shell**: Project uses fish shell for environment configuration
