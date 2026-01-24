# hello_llm.py
"""
Модуль для отримання відповіді від LLM за допомогою OpenAI SDK.

Параметри можна налаштувати через змінні середовища:
- SECRET_LLM_API_KEY – ключ API
- LLM_BASE_URL   – URL базового API (за замовчуванням `https://llm.dev.cossacklabs.com/api`)
- LLM_MODEL      – модель, яку використовувати (за замовчуванням `gpt-oss:20b`)
"""

import os
import logging
from typing import Optional

from openai import OpenAI
from openai import OpenAIError


# Налаштування логування
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def get_client() -> OpenAI:
    """
    Створює та повертає клієнт OpenAI, перевіряючи необхідні змінні середовища.
    """
    api_key = os.getenv("SECRET_LLM_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "SECRET_LLM_API_KEY is not set in the environment."
        )

    base_url = os.getenv("LLM_BASE_URL", "https://llm.dev.cossacklabs.com/api")
    return OpenAI(base_url=base_url, api_key=api_key)


def ask_gpt(message: str, *, model: Optional[str] = None) -> str:
    """
    Повертає відповідь LLM на надане повідомлення.

    :param message: Текст запиту користувача
    :param model: Назва моделі (за замовчуванням береться зі змінної `LLM_MODEL`)
    :return: Відповідь моделі
    """
    client = get_client()
    model = model or os.getenv("LLM_MODEL", "gpt-oss:20b")

    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": message}]
        )
    except OpenAIError as exc:
        log.error("OpenAI API call failed: %s", exc)
        raise

    # Відповідь повертається як рядок
    return response.choices[0].message.content or ""


def main() -> None:
    message = "Привіт, як справи?"
    log.info("Sending message to LLM: %s", message)
    answer = ask_gpt(message)
    print(answer)


if __name__ == "__main__":
    main()

