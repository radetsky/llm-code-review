"""Tests for the chunk strategy of the classic engine."""

import httpx
import openai

from config import ReviewConfig
from review_core import LLMReviewer, ReviewResult


def api_error():
    return openai.APIConnectionError(request=httpx.Request("POST", "http://x"))


def ok(text="WARNING: a.py:1: w"):
    return ReviewResult(
        status="success", critical_issues=[], warnings=[text], suggestions=[]
    )


def make(monkeypatch, outcomes):
    reviewer = LLMReviewer(ReviewConfig())
    calls = []

    def fake_call(chunk):
        calls.append(chunk)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(reviewer, "_call_llm", fake_call)
    monkeypatch.setattr(
        reviewer, "_chunk_diff", lambda diff, size: ["one", "two"], raising=True
    )
    return reviewer, calls


def test_model_outage_uses_the_unavailable_path(monkeypatch):
    reviewer, _ = make(monkeypatch, [api_error(), api_error()])
    seen = {}

    def unavailable(diff, error):
        seen["error"] = error
        return ReviewResult(
            status="model_unavailable", critical_issues=[], warnings=[], suggestions=[]
        )

    monkeypatch.setattr(reviewer, "_handle_model_unavailable", unavailable)
    result = reviewer._review_chunks("diff", 100)
    assert result.status == "model_unavailable"
    assert isinstance(seen["error"], openai.APIConnectionError)


def test_one_failed_chunk_is_a_warning(monkeypatch):
    reviewer, _ = make(monkeypatch, [ok(), api_error()])
    result = reviewer._review_chunks("diff", 100)
    assert result.status == "success"
    assert any(w.startswith("Chunk 2/2 review failed") for w in result.warnings)


def test_other_errors_keep_the_error_status(monkeypatch):
    reviewer, _ = make(monkeypatch, [ValueError("bad"), ValueError("bad")])
    assert reviewer._review_chunks("diff", 100).status == "error"
