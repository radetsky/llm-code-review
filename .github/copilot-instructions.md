# Copilot Instructions for cl-llm

## Project Overview

A Python project for interacting with CossackLabs' internal LLM API using the OpenAI-compatible client.

## Architecture

- **Single-script project**: Main logic lives in `hello_llm.py`
- **OpenAI-compatible API**: Uses the `openai` Python package against a custom endpoint (`https://llm.dev.cossacklabs.com/api`)
- **Model**: `gpt-oss:20b` - the internal LLM model identifier

## Environment Setup

```bash
# Activate Python virtual environment
source .python-venv/bin/activate.fish

# Load API key (fish shell)
source .env.fish
```

The API key is stored in `SECRET_LLM_API_KEY` environment variable.

## Code Patterns

### API Client Configuration

Always configure the OpenAI client with the custom base URL:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://llm.dev.cossacklabs.com/api",
    api_key=os.environ.get("SECRET_LLM_API_KEY")  # Use env var, not hardcoded
)
```

### Making LLM Requests

Use the chat completions API with the `gpt-oss:20b` model:

```python
response = client.chat.completions.create(
    model="gpt-oss:20b",
    messages=[{"role": "user", "content": "Your prompt"}]
)
```

## Important Notes

- **Never commit API keys**: Use environment variables from `.env.fish`
- **Language**: The project uses Ukrainian language in prompts/responses
- **Shell**: Project uses fish shell for environment configuration
