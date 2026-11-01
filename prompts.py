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


def _rule_list(prompt_config: dict, key: str) -> list:
    value = prompt_config.get(key) or []
    return list(value) if isinstance(value, list) else []


def _bullets(rules: list) -> str:
    return "\n".join(f"- {rule}" for rule in rules if isinstance(rule, str))


def collect_rules(config) -> dict[str, str]:
    """Return the project rules from the config as text, one bullet per rule.

    The keys are critical, warnings, suggestions and additional. Both review
    engines use this function. The config is not changed.
    """
    prompt_config = config.get("prompt") or {}
    if not isinstance(prompt_config, dict):
        prompt_config = {}

    suggestions = _rule_list(prompt_config, "custom_suggestions")
    if config.get("review.check_docstrings", True):
        docstring_rule = load_prompt("rule_docstrings")
        if docstring_rule not in suggestions:
            suggestions.append(docstring_rule)

    additional = prompt_config.get("additional_instructions") or ""
    return {
        "critical": _bullets(_rule_list(prompt_config, "custom_critical_rules")),
        "warnings": _bullets(_rule_list(prompt_config, "custom_warnings")),
        "suggestions": _bullets(suggestions),
        "additional": additional if isinstance(additional, str) else "",
    }
