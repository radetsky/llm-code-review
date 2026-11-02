"""Tests for the monitoring log and the report."""

import json
import sys
from datetime import datetime, timedelta

import pytest

import monitor
from config import ReviewConfig
from monitor import MonitoringUtils, percentile, summarize
from review_core import ReviewResult


def result(status="success", critical=0, warnings=0, stats=None, **kw):
    return ReviewResult(
        status=status,
        critical_issues=["c"] * critical,
        warnings=["w"] * warnings,
        suggestions=[],
        agent_stats=stats,
        **kw,
    )


def agent_stats(**kw):
    base = {
        "steps": 4,
        "tokens": 8000,
        "tool_calls": 6,
        "invalid_tool_calls": 0,
        "duplicate_tool_calls": 0,
        "forced_submit": None,
        "stop_reason": "submitted",
        "duration_sec": 5.0,
    }
    base.update(kw)
    return base


def write_entry(
    logs, day, engine="classic", duration=3.0, status="success", stats=None, **counts
):
    logs.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": day.isoformat(),
        "result": {
            "status": status,
            "critical_count": counts.get("critical", 0),
            "warning_count": counts.get("warnings", 0),
            "suggestion_count": 0,
            "fallback_used": False,
        },
        "metadata": {"engine": engine, "duration_sec": duration},
    }
    if stats:
        entry["agent"] = stats
    with open(logs / f"reviews_{day.strftime('%Y%m%d')}.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def now():
    """Local time without a time zone. monitor.py names its log files the same way."""
    return datetime.now()  # noqa: DTZ005


@pytest.fixture
def logs(tmp_path):
    return tmp_path / "logs"


class TestLogging:
    def test_creating_the_object_makes_no_folder(self, logs):
        MonitoringUtils(ReviewConfig(), logs_dir=logs)
        assert not logs.exists()

    def test_folder_is_created_by_the_first_entry(self, logs):
        MonitoringUtils(ReviewConfig(), logs_dir=logs).log_review_result(result())
        assert logs.is_dir() and len(list(logs.glob("reviews_*.jsonl"))) == 1

    def test_log_folder_comes_from_the_config(self, tmp_path):
        config = ReviewConfig()
        config.config["monitoring"] = {
            "enabled": True,
            "log_dir": str(tmp_path / "custom"),
        }
        assert MonitoringUtils(config).logs_dir == tmp_path / "custom"

    def test_classic_entry(self, logs):
        monitor_ = MonitoringUtils(ReviewConfig(), logs_dir=logs)
        monitor_.log_review_result(
            result(critical=2, warnings=1), {"engine": "classic", "duration_sec": 3.2}
        )
        (entry,) = monitor_.read_entries(1)
        assert entry["result"]["critical_count"] == 2
        assert entry["result"]["review_outcome"] == "critical"
        assert entry["metadata"] == {"engine": "classic", "duration_sec": 3.2}
        assert "agent" not in entry

    def test_agent_entry_keeps_the_statistics(self, logs):
        stats = agent_stats(
            extra_secret_field="x", fallback="classic", fallback_reason="boom"
        )
        monitor_ = MonitoringUtils(ReviewConfig(), logs_dir=logs)
        monitor_.log_review_result(result(stats=stats), {"engine": "agent->classic"})
        (entry,) = monitor_.read_entries(1)
        assert entry["agent"]["steps"] == 4 and entry["agent"]["tokens"] == 8000
        assert entry["agent"]["fallback_reason"] == "boom"
        assert "extra_secret_field" not in entry["agent"]

    def test_entries_are_appended(self, logs):
        monitor_ = MonitoringUtils(ReviewConfig(), logs_dir=logs)
        for _ in range(3):
            monitor_.log_review_result(result())
        assert len(monitor_.read_entries(1)) == 3


class TestReadEntries:
    def test_period_and_order(self, logs):
        today = now()
        write_entry(logs, today - timedelta(days=10), duration=1.0)
        write_entry(logs, today - timedelta(days=2), duration=2.0)
        write_entry(logs, today, duration=3.0)
        monitor_ = MonitoringUtils(ReviewConfig(), logs_dir=logs)
        assert [e["metadata"]["duration_sec"] for e in monitor_.read_entries(7)] == [
            2.0,
            3.0,
        ]
        assert len(monitor_.read_entries(1)) == 1
        assert len(monitor_.read_entries(30)) == 3

    def test_broken_lines_are_skipped(self, logs):
        write_entry(logs, now())
        file = next(logs.glob("*.jsonl"))
        with open(file, "a") as f:
            f.write('not json\n[1, 2]\n{}\n{"result": 5}\n\n')
        assert len(MonitoringUtils(ReviewConfig(), logs_dir=logs).read_entries(1)) == 1

    def test_missing_folder(self, tmp_path):
        assert (
            MonitoringUtils(ReviewConfig(), logs_dir=tmp_path / "none").read_entries(7)
            == []
        )


class TestPercentile:
    def test_cases(self):
        assert percentile([], 50) is None
        assert percentile([7], 90) == 7
        assert percentile([4, 1, 3, 2], 50) == 2
        assert percentile(list(range(1, 11)), 90) == 9
        assert percentile(list(range(1, 11)), 100) == 10
        assert percentile([5, 1], 0) == 1


def entry(engine="agent", status="success", stats=None, duration=10.0, **counts):
    e = {
        "result": {
            "status": status,
            "critical_count": counts.get("critical", 0),
            "warning_count": counts.get("warnings", 0),
        },
        "metadata": {"engine": engine, "duration_sec": duration},
    }
    if stats is not None:
        e["agent"] = stats
    return e


class TestSummarize:
    def test_empty(self):
        s = summarize([])
        assert s["total_reviews"] == 0 and s["success_rate"] == 0
        assert s["median_steps"] is None and s["invalid_call_rate"] is None

    def test_counts_and_rates(self):
        entries = [
            entry(critical=1, warnings=2, stats=agent_stats(steps=2, tokens=1000)),
            entry(
                warnings=1,
                stats=agent_stats(
                    steps=4, tokens=3000, tool_calls=8, invalid_tool_calls=2
                ),
            ),
            entry(status="model_unavailable"),
            entry(
                stats=agent_stats(
                    steps=20, tokens=9000, forced_submit="max_steps", fallback="classic"
                )
            ),
        ]
        s = summarize(entries)
        assert s["total_reviews"] == 4 and s["successful_reviews"] == 3
        assert s["success_rate"] == 75.0 and s["unavailable_reviews"] == 1
        assert s["total_critical_issues"] == 1 and s["total_warnings"] == 3
        assert s["avg_warnings_per_review"] == 0.75
        assert s["agent_reviews"] == 3
        assert s["median_steps"] == 4 and s["p90_steps"] == 20
        assert s["median_tokens"] == 3000 and s["total_tokens"] == 13000
        assert s["invalid_call_rate"] == pytest.approx(2 / (6 + 8 + 6 + 2))
        assert s["forced_submit_rate"] == pytest.approx(1 / 3)
        assert s["fallback_rate"] == pytest.approx(1 / 3)

    def test_durations(self):
        s = summarize([entry(duration=d) for d in (1.0, 2.0, 3.0, 4.0, 100.0)])
        assert s["median_duration_sec"] == 3.0 and s["p90_duration_sec"] == 100.0

    def test_old_entries_without_new_fields(self):
        old = {"result": {"status": "success", "critical_count": 1, "warning_count": 0}}
        s = summarize([old, old])
        assert s["total_reviews"] == 2 and s["median_duration_sec"] is None
        assert s["agent_reviews"] == 0

    def test_a_classic_review_does_not_count_as_an_agent_review(self):
        s = summarize([entry(engine="classic"), entry(stats={})])
        assert s["agent_reviews"] == 0


class TestReport:
    def test_split_by_engine(self, logs):
        today = now()
        write_entry(logs, today, engine="classic", duration=3.0)
        write_entry(
            logs, today, engine="agent", duration=9.0, stats=agent_stats(steps=5)
        )
        write_entry(
            logs,
            today,
            engine="agent->classic",
            duration=30.0,
            stats=agent_stats(fallback="classic"),
        )
        write_entry(logs, today, engine=None)
        report = MonitoringUtils(ReviewConfig(), logs_dir=logs).generate_report(1)
        assert report["summary"]["total_reviews"] == 4
        assert set(report["by_engine"]) == {
            "classic",
            "agent",
            "agent->classic",
            "unknown",
        }
        assert report["by_engine"]["agent"]["median_steps"] == 5
        assert report["by_engine"]["classic"]["agent_reviews"] == 0
        assert len(report["details"]) == 4

    def test_details_keep_the_last_ten(self, logs):
        for _ in range(15):
            write_entry(logs, now())
        report = MonitoringUtils(ReviewConfig(), logs_dir=logs).generate_report(1)
        assert len(report["details"]) == 10 and report["summary"]["total_reviews"] == 15


class TestCommandLine:
    def run(self, monkeypatch, capsys, *argv):
        monkeypatch.setattr(sys, "argv", ["monitor.py", *argv])
        monitor.main()
        return capsys.readouterr().out

    def test_report_without_reviews_does_not_crash(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        out = self.run(monkeypatch, capsys, "report")
        assert "No reviews in this period." in out and "LLM_MONITORING" in out
        assert not (tmp_path / "logs").exists()  # Reading does not create the folder.

    def test_report_text(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        write_entry(
            tmp_path / "logs",
            now(),
            engine="agent",
            stats=agent_stats(steps=6, tokens=12000),
        )
        write_entry(tmp_path / "logs", now(), engine="classic")
        out = self.run(monkeypatch, capsys, "report", "--days", "2")
        assert "Last 2 days" in out and "Total Reviews: 2" in out
        assert "Engine: agent" in out and "Engine: classic" in out
        assert (
            "Steps (median / p90): 6 / 6" in out
            and "Tokens (median / p90): 12000" in out
        )
        assert out.count("Agent reviews:") == 2  # In the total and in the agent part.

    def test_report_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        write_entry(tmp_path / "logs", now(), engine="agent", stats=agent_stats())
        data = json.loads(self.run(monkeypatch, capsys, "report", "--json"))
        assert data["summary"]["total_reviews"] == 1
        assert data["by_engine"]["agent"]["median_steps"] == 4

    def test_no_command_prints_help(self, monkeypatch, capsys):
        assert "usage" in self.run(monkeypatch, capsys).lower()


def test_monitoring_switch(monkeypatch):
    config = ReviewConfig()
    monkeypatch.delenv("LLM_MONITORING", raising=False)
    assert config.get_monitoring_enabled() is False
    config.config["monitoring"] = {"enabled": True}
    assert config.get_monitoring_enabled() is True
    monkeypatch.setenv("LLM_MONITORING", "0")
    assert config.get_monitoring_enabled() is False
    monkeypatch.setenv("LLM_MONITORING", "yes")
    config.config["monitoring"] = {"enabled": False}
    assert config.get_monitoring_enabled() is True
