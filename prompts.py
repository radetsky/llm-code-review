"""
Load prompt text files.

Each prompt is a text file in the prompts folder. Edit a file to change
the text that the model receives. A placeholder has the form {name}.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"

_cache: dict[tuple[str, str], str] = {}


def load_prompt(name: str) -> str:
    """Return the text of prompts/<name>.md without the final newline."""
    key = (str(PROMPTS_DIR), name)
    if key not in _cache:
        path = PROMPTS_DIR / f"{name}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt file not found: {path}") from None
        _cache[key] = text.rstrip("\n")
    return _cache[key]


def render(template: str, **values: object) -> str:
    """Replace each {name} in the template with its value.

    This is not str.format: other braces in the text stay as they are.
    """
    for name, value in values.items():
        template = template.replace("{" + name + "}", str(value))
    return template
