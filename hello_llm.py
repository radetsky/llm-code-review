# hello_llm.py
"""
Simple helper to fetch an LLM reply via the OpenAI SDK.

Environment variables:
- LLM_API_KEY  – API key (required)
- LLM_BASE_URL – Base API URL (default: `https://llm.dev.cossacklabs.com/api`)
- LLM_MODEL    – Model name (default: `gpt-oss:20b`)
"""

import os
import logging
from typing import Optional

from openai import OpenAI
from openai import OpenAIError


# Basic logging setup
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def get_client() -> OpenAI:
    """Create and return an OpenAI client using the required environment variables."""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise EnvironmentError("LLM_API_KEY is not set in the environment.")

    base_url = os.getenv("LLM_BASE_URL", "https://llm.dev.cossacklabs.com/api")
    return OpenAI(base_url=base_url, api_key=api_key)


def ask_gpt(message: str, *, model: Optional[str] = None) -> str:
    """Return the LLM response to the provided message."""
    client = get_client()
    model = model or os.getenv("LLM_MODEL", "gpt-oss:20b")

    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": message}]
        )
    except OpenAIError as exc:
        log.error("OpenAI API call failed: %s", exc)
        raise

    # Ensure we always return a string
    return response.choices[0].message.content or ""


def main() -> None:
    message = "¡Hola, que pasa, tio?"
    log.info("Sending message to LLM: %s", message)
    answer = ask_gpt(message)
    print(answer)


if __name__ == "__main__":
    main()
