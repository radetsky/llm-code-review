"""Tests for the hiding of secrets in the text of a review."""

import json

import pytest

from redaction import PLACEHOLDER, redact, redact_list, redact_result
from review_core import CodeSuggestion, ReviewResult

HEX_SECRET = "4f9c2a7e61b84d3f9a05c8d17e2b6a43"
GITHUB_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
STRIPE_KEY = "sk_live_" + "51HxExAmPlEkEy000000000000"


class TestSpecificPatterns:
    @pytest.mark.parametrize(
        "secret",
        [
            GITHUB_TOKEN,
            "github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
            "xoxb-" + "1234567890-abcdefghij",
            STRIPE_KEY,
            "sk-proj-" + "abcdefghij0123456789ABCDEF",
            "sk-" + "abcdefghijklmnopqrstuvwx",
            "AKIA" + "ABCDEFGHIJKLMNOP",
            "AIza" + "SyA1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q",
            "eyJhbGciOiJIUzI1NiJ9"
            + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        ],
    )
    def test_token_formats(self, secret):
        text, count = redact(f"The code uses {secret} here.", generic=False)
        assert secret not in text and PLACEHOLDER in text and count == 1

    def test_private_key_block(self):
        block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabcdef\n-----END RSA PRIVATE KEY-----"
        text, count = redact(f"The file has\n{block}\nin it", generic=False)
        assert "MIIEow" not in text and "BEGIN" not in text and count == 1
        assert text.startswith("The file has\n") and text.endswith("\nin it")

    def test_private_key_without_end(self):
        text, _ = redact("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg", generic=False)
        assert "MIIEvQ" not in text

    def test_bearer_header(self):
        text, count = redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456")
        assert text == f"Authorization: Bearer {PLACEHOLDER}" and count == 1

    def test_url_password_keeps_the_rest(self):
        text, count = redact(
            "connect to postgres://admin:hunter2pass@db.example.com/app"
        )
        assert text == f"connect to postgres://admin:{PLACEHOLDER}@db.example.com/app"
        assert count == 1

    def test_specific_rules_also_apply_to_code(self):
        text, _ = redact(f'KEY = "{GITHUB_TOKEN}"', generic=False)
        assert GITHUB_TOKEN not in text

    def test_several_secrets_are_counted(self):
        text, count = redact(f"{GITHUB_TOKEN} and {STRIPE_KEY}")
        assert count == 2 and text == f"{PLACEHOLDER} and {PLACEHOLDER}"


class TestGenericRule:
    @pytest.mark.parametrize(
        "line,expected",
        [
            (
                f'PAYMENT_API_KEY = "{HEX_SECRET}" is in the code',
                f'PAYMENT_API_KEY = "{PLACEHOLDER}" is in the code',
            ),
            (f"password: {HEX_SECRET}", f"password: {PLACEHOLDER}"),
            (f"db.secret_token='{HEX_SECRET}'", f"db.secret_token='{PLACEHOLDER}'"),
            (
                f"AWS_SECRET_ACCESS_KEY={'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'}",
                f"AWS_SECRET_ACCESS_KEY={PLACEHOLDER}",
            ),
        ],
    )
    def test_names_with_long_mixed_values(self, line, expected):
        assert redact(line)[0] == expected

    @pytest.mark.parametrize(
        "line",
        [
            "token = get_token()",
            "password = request.POST['password']",
            "api_key = os.environ['API_KEY']",
            "SECRET_KEY = settings.SECRET_KEY",
            "max_tokens = 4096",
            "token_limit = 1000000000000",
            "the password is stored in a vault",
            "password = 'short1'",
            "password_hash = hash_password(password)",
            "commit 4f9c2a7e61b84d3f9a05c8d17e2b6a43c0ffee11 changed it",
            "The library sk-learn is fine",
            "Use Bearer tokens in the header",
        ],
    )
    def test_normal_code_and_text_are_not_changed(self, line):
        assert redact(line) == (line, 0)

    def test_generic_rule_is_off_for_code(self):
        line = f'api_key = "{HEX_SECRET}"'
        assert redact(line, generic=False) == (line, 0)

    def test_result_is_stable(self):
        once, _ = redact(f'api_key = "{HEX_SECRET}" and {GITHUB_TOKEN}')
        assert redact(once) == (once, 0)

    def test_empty_and_wrong_types(self):
        assert redact("") == ("", 0)
        assert redact(None) == (None, 0)
        assert redact_list(["a", None, 5, f"token={HEX_SECRET}"]) == (
            ["a", None, 5, f"token={PLACEHOLDER}"],
            1,
        )


def make_result(**kw):
    base = {
        "status": "success",
        "critical_issues": [f"a.py:1: key {GITHUB_TOKEN} is in the code"],
        "warnings": [f'a.py:2: api_key = "{HEX_SECRET}"'],
        "suggestions": ["a.py:3: fine"],
        "code_suggestions": [
            CodeSuggestion(
                "a.py",
                4,
                4,
                f"use token={HEX_SECRET}",
                f'api_key = os.environ["K"]  # {GITHUB_TOKEN}',
            ),
            CodeSuggestion("a.py", 5, 5, "plain", f'password = "{HEX_SECRET}"'),
        ],
        "raw_response": f"error with {GITHUB_TOKEN}",
        "agent_stats": {"steps": 3, "fallback_reason": f"failed: token={HEX_SECRET}"},
    }
    base.update(kw)
    return ReviewResult(**base)


class TestRedactResult:
    def test_all_fields(self):
        result = make_result()
        count = redact_result(result)
        dump = json.dumps(
            [
                result.critical_issues,
                result.warnings,
                result.suggestions,
                result.raw_response,
                result.agent_stats,
            ]
            + [(c.description, c.suggested_code) for c in result.code_suggestions[:1]]
        )
        assert GITHUB_TOKEN not in dump and HEX_SECRET not in dump
        assert count == result.redacted_count and count >= 6
        assert result.suggestions == ["a.py:3: fine"]
        assert result.agent_stats["steps"] == 3

    def test_code_keeps_working_syntax_except_for_known_token_formats(self):
        result = make_result()
        redact_result(result)
        first, second = result.code_suggestions
        assert first.suggested_code.startswith('api_key = os.environ["K"]')
        assert (
            PLACEHOLDER in first.suggested_code
            and GITHUB_TOKEN not in first.suggested_code
        )
        # The generic rule is off for code, so a plain assignment stays as the model wrote it.
        assert second.suggested_code == f'password = "{HEX_SECRET}"'

    def test_count_adds_up_when_called_twice(self):
        result = make_result()
        first = redact_result(result)
        assert redact_result(result) == 0
        assert result.redacted_count == first

    def test_clean_result_is_not_changed(self):
        result = ReviewResult("success", ["a.py:1: bad"], [], [])
        assert redact_result(result) == 0 and result.redacted_count == 0
        assert result.critical_issues == ["a.py:1: bad"]


def test_nested_hybrid_fallback_reason_is_redacted():
    result = make_result(
        agent_stats={"hybrid": {"fallback_reason": f"failed with {GITHUB_TOKEN}"}}
    )
    redact_result(result)
    reason = result.agent_stats["hybrid"]["fallback_reason"]
    assert GITHUB_TOKEN not in reason and PLACEHOLDER in reason
