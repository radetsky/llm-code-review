"""Tests for code suggestion parsing in LLM response parser."""

import pytest

from review_core import CodeSuggestion, LLMReviewer, ReviewResult
from config import ReviewConfig


@pytest.fixture
def reviewer():
    """Create a reviewer instance for testing."""
    config = ReviewConfig()
    return LLMReviewer(config)


class TestCodeSuggestionParsing:
    """Tests for _parse_llm_response with code suggestion blocks."""

    def test_single_code_suggestion(self, reviewer):
        """Parse a single SUGGESTION with ```suggestion block."""
        response = (
            "SUGGESTION: app.py:42: Use list comprehension\n"
            "```suggestion\n"
            "items = [x for x in range(10)]\n"
            "```"
        )
        result = reviewer._parse_llm_response(response)

        assert len(result.code_suggestions) == 1
        assert len(result.suggestions) == 0

        cs = result.code_suggestions[0]
        assert cs.file == "app.py"
        assert cs.line_start == 42
        assert cs.line_end == 42
        assert cs.description == "Use list comprehension"
        assert cs.suggested_code == "items = [x for x in range(10)]"

    def test_multiline_range_suggestion(self, reviewer):
        """Parse SUGGESTION with line range file.py:10-15."""
        response = (
            "SUGGESTION: utils.py:10-15: Simplify loop\n"
            "```suggestion\n"
            "for item in items:\n"
            "    process(item)\n"
            "```"
        )
        result = reviewer._parse_llm_response(response)

        assert len(result.code_suggestions) == 1
        cs = result.code_suggestions[0]
        assert cs.file == "utils.py"
        assert cs.line_start == 10
        assert cs.line_end == 15
        assert cs.description == "Simplify loop"
        assert cs.suggested_code == "for item in items:\n    process(item)"

    def test_mixed_suggestions_and_code_suggestions(self, reviewer):
        """Parse response with both plain suggestions and code suggestions."""
        response = (
            "CRITICAL: auth.py:5: Hardcoded password\n"
            "WARNING: db.py:20: Missing error handling\n"
            "SUGGESTION: config.py:10: Consider using pathlib\n"
            "SUGGESTION: app.py:42: Use f-string\n"
            "```suggestion\n"
            'msg = f"Hello {name}"\n'
            "```\n"
            "SUGGESTION: utils.py:8: Add type hint\n"
        )
        result = reviewer._parse_llm_response(response)

        assert len(result.critical_issues) == 1
        assert len(result.warnings) == 1
        assert len(result.suggestions) == 2
        assert result.suggestions[0] == "config.py:10: Consider using pathlib"
        assert result.suggestions[1] == "utils.py:8: Add type hint"

        assert len(result.code_suggestions) == 1
        cs = result.code_suggestions[0]
        assert cs.file == "app.py"
        assert cs.line_start == 42
        assert cs.description == "Use f-string"
        assert cs.suggested_code == 'msg = f"Hello {name}"'

    def test_unclosed_suggestion_block_fallback(self, reviewer):
        """Unclosed ```suggestion block falls back to plain suggestion."""
        response = (
            "SUGGESTION: app.py:42: Use list comprehension\n"
            "```suggestion\n"
            "items = [x for x in range(10)]\n"
        )
        result = reviewer._parse_llm_response(response)

        assert len(result.code_suggestions) == 0
        assert len(result.suggestions) == 1
        assert result.suggestions[0] == "app.py:42: Use list comprehension"

    def test_empty_suggestion_block(self, reviewer):
        """Empty ```suggestion block (delete lines)."""
        response = "SUGGESTION: app.py:42-45: Remove dead code\n```suggestion\n```"
        result = reviewer._parse_llm_response(response)

        assert len(result.code_suggestions) == 1
        cs = result.code_suggestions[0]
        assert cs.file == "app.py"
        assert cs.line_start == 42
        assert cs.line_end == 45
        assert cs.description == "Remove dead code"
        assert cs.suggested_code == ""

    def test_suggestion_without_file_line_format(self, reviewer):
        """SUGGESTION without file:line before ```suggestion is plain suggestion."""
        response = (
            "SUGGESTION: Consider refactoring this module\n"
            "```suggestion\n"
            "some code\n"
            "```"
        )
        result = reviewer._parse_llm_response(response)

        # No file:line match, so it's a plain suggestion
        assert len(result.code_suggestions) == 0
        assert len(result.suggestions) == 1
        assert result.suggestions[0] == "Consider refactoring this module"

    def test_suggestion_none_ignored(self, reviewer):
        """SUGGESTION: NONE is ignored."""
        response = "SUGGESTION: NONE\n"
        result = reviewer._parse_llm_response(response)

        assert len(result.suggestions) == 0
        assert len(result.code_suggestions) == 0

    def test_multiple_code_suggestions(self, reviewer):
        """Parse multiple code suggestions in one response."""
        response = (
            "SUGGESTION: a.py:1: Fix import\n"
            "```suggestion\n"
            "import os\n"
            "```\n"
            "SUGGESTION: b.py:10-12: Simplify\n"
            "```suggestion\n"
            "return True\n"
            "```"
        )
        result = reviewer._parse_llm_response(response)

        assert len(result.code_suggestions) == 2
        assert result.code_suggestions[0].file == "a.py"
        assert result.code_suggestions[0].line_start == 1
        assert result.code_suggestions[1].file == "b.py"
        assert result.code_suggestions[1].line_start == 10
        assert result.code_suggestions[1].line_end == 12

    def test_code_suggestion_preserves_indentation(self, reviewer):
        """Code suggestion preserves indentation in the suggested code."""
        response = (
            "SUGGESTION: app.py:10: Fix indentation\n"
            "```suggestion\n"
            "    if condition:\n"
            "        do_something()\n"
            "```"
        )
        result = reviewer._parse_llm_response(response)

        assert len(result.code_suggestions) == 1
        cs = result.code_suggestions[0]
        assert cs.suggested_code == "    if condition:\n        do_something()"


class TestReviewResultCodeSuggestions:
    """Tests for ReviewResult with code_suggestions field."""

    def test_default_empty_code_suggestions(self):
        """ReviewResult has empty code_suggestions by default."""
        result = ReviewResult(
            status="success",
            critical_issues=[],
            warnings=[],
            suggestions=[],
        )
        assert result.code_suggestions == []

    def test_code_suggestions_field(self):
        """ReviewResult stores code_suggestions."""
        cs = CodeSuggestion(
            file="test.py",
            line_start=1,
            line_end=1,
            description="test",
            suggested_code="pass",
        )
        result = ReviewResult(
            status="success",
            critical_issues=[],
            warnings=[],
            suggestions=[],
            code_suggestions=[cs],
        )
        assert len(result.code_suggestions) == 1
        assert result.code_suggestions[0].file == "test.py"
