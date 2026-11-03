"""
Hide values that look like secrets in the text of a review.

The text of a review can go to a public place, for example a pull request
comment. The model reads files and can write a secret from a file into a
finding. This module replaces such values with [REDACTED] before the review
leaves the program.

There are two kinds of rules:
  specific: tokens with a known format (private keys, GitHub tokens, ...).
            The module applies them to all text, also to suggested code.
  generic:  a name such as password or api_key with a long mixed value.
            The module applies them to prose only, because in code the same
            pattern can be a correct expression.
"""

import re

PLACEHOLDER = "[REDACTED]"

_SPECIFIC = [
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
        r"[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)"
    ),
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]

_BEARER = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{20,}")
_URL_PASSWORD = re.compile(
    r"\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(@)", re.IGNORECASE
)

# A name that suggests a secret, a separator and a long value without
# brackets. The value must have letters and digits.
_GENERIC = re.compile(
    r"""
    (?P<key>\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey
        |access[_-]?key|private[_-]?key|credential)[\w.-]*)
    (?P<sep>\s*[:=]\s*)
    (?P<quote>["'`]?)
    (?P<value>[A-Za-z0-9+/_\-=.@$!%^*~]{12,})
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _looks_mixed(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))


def redact(text: str, generic: bool = True) -> tuple[str, int]:
    """Return the text without secrets and the number of replacements."""
    if not isinstance(text, str) or not text:
        return text, 0
    count = 0

    for pattern in _SPECIFIC:
        text, n = pattern.subn(PLACEHOLDER, text)
        count += n

    text, n = _BEARER.subn(lambda m: m.group(1) + PLACEHOLDER, text)
    count += n
    text, n = _URL_PASSWORD.subn(lambda m: m.group(1) + PLACEHOLDER + m.group(2), text)
    count += n

    if generic:
        found = 0

        def replace(match: re.Match) -> str:
            nonlocal found
            value = match.group("value")
            if value == PLACEHOLDER or not _looks_mixed(value):
                return match.group(0)
            found += 1
            return f"{match.group('key')}{match.group('sep')}{match.group('quote')}{PLACEHOLDER}"

        text = _GENERIC.sub(replace, text)
        count += found
    return text, count


def redact_list(items: list) -> tuple[list, int]:
    total = 0
    result = []
    for item in items:
        new, n = redact(item) if isinstance(item, str) else (item, 0)
        result.append(new)
        total += n
    return result, total


def _redact_strings(data: dict) -> int:
    """Hide secrets in every string value of a nested dict. Return the count."""
    total = 0
    for key, value in data.items():
        if isinstance(value, str):
            data[key], n = redact(value)
            total += n
        elif isinstance(value, dict):
            total += _redact_strings(value)
    return total


def redact_result(result) -> int:
    """Hide secrets in a ReviewResult. Return the number of replacements.

    The function changes the result and adds the number to result.redacted_count.
    """
    total = 0
    for name in ("critical_issues", "warnings", "suggestions"):
        new, n = redact_list(getattr(result, name))
        setattr(result, name, new)
        total += n
    for suggestion in result.code_suggestions:
        suggestion.description, n = redact(suggestion.description)
        total += n
        suggestion.suggested_code, n = redact(suggestion.suggested_code, generic=False)
        total += n
    if isinstance(result.agent_stats, dict):
        total += _redact_strings(result.agent_stats)
    if isinstance(result.raw_response, str):
        result.raw_response, n = redact(result.raw_response)
        total += n
    result.redacted_count = getattr(result, "redacted_count", 0) + total
    return total
