"""Tests for the evaluation tools. They do not call an LLM."""

import json
import re

import pytest

from agent_core import valid_lines_by_file
from config import ReviewConfig
from diff_parser import DiffParser
from evaluation import run_eval
from evaluation.cases import BASE_BRANCH, HEAD_BRANCH, Expected, build_repo, load_cases
from evaluation.report import render
from evaluation.scoring import Finding, aggregate, parse_findings, per_case, score_run

CASES = load_cases()


class TestGoldenCases:
    def test_there_are_enough_cases(self):
        assert 6 <= len(CASES) <= 12
        assert any(c.is_clean for c in CASES)
        assert any(not c.is_clean for c in CASES)

    def test_unknown_case_name(self):
        with pytest.raises(ValueError, match="Unknown case"):
            load_cases(["nope"])

    def test_filter_by_name(self):
        assert [c.id for c in load_cases(["sql-injection"])] == ["sql-injection"]

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
    def test_expected_places_are_visible_in_the_diff(self, case, tmp_path, monkeypatch):
        repo = build_repo(case, tmp_path / "repo")
        monkeypatch.chdir(repo)
        config = ReviewConfig()
        review = config.config["review"]
        review["file_extensions"] = review["file_extensions"] + case.extra_extensions
        parser = DiffParser(config)
        parsed = parser.parse_diff(parser.get_diff("range", BASE_BRANCH, HEAD_BRANCH))
        anchors = valid_lines_by_file(parsed)

        assert parsed, "the diff must have a reviewable file"
        for item in case.expected:
            assert item.file in anchors, f"{item.file} is not in the diff"
            assert item.line in anchors[item.file], (
                f"line {item.line} is not in the diff"
            )
            assert item.kind in ("critical", "warning")

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
    def test_the_change_is_a_real_change(self, case, tmp_path):
        repo = build_repo(case, tmp_path / "repo")
        import subprocess

        names = subprocess.run(
            ["git", "diff", "--name-only", f"{BASE_BRANCH}...{HEAD_BRANCH}"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert names

    def test_cases_do_not_give_the_answer_away(self):
        """The code must not tell the reviewer where the problem is."""
        for case in CASES:
            for path in (case.root / "after").rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8").lower()
                    hint = re.search(
                        r"\b(bug|vulnerab\w*|insecure|fixme|injection)\b", text
                    )
                    assert not hint, f"{path}: {hint.group(0)}"


class TestParseFindings:
    def result(self, **kw):
        base = {
            "critical_issues": [],
            "warnings": [],
            "suggestions": [],
            "code_suggestions": [],
        }
        base.update(kw)
        return base

    def test_all_sources(self):
        findings = parse_findings(
            self.result(
                critical_issues=["app/db.py:12: bad query"],
                warnings=["./a.py:3-5: range"],
                suggestions=["b.go:7: nice to have"],
                code_suggestions=[
                    {"file": "c.py", "line_start": 4, "line_end": 6, "description": "d"}
                ],
            )
        )
        got = [(f.severity, f.file, f.line, f.line_end) for f in findings]
        assert got == [
            ("critical", "app/db.py", 12, 12),
            ("warning", "a.py", 3, 5),
            ("suggestion", "b.go", 7, 7),
            ("suggestion", "c.py", 4, 6),
        ]

    def test_message_keeps_its_colons(self):
        (f,) = parse_findings(self.result(warnings=["a.py:3: bad: really: bad"]))
        assert f.text == "bad: really: bad"

    def test_text_without_location_is_unanchored(self):
        (f,) = parse_findings(self.result(warnings=["The code looks wrong"]))
        assert not f.anchored and f.text == "The code looks wrong"

    def test_bullet_and_backticks_are_accepted(self):
        (f,) = parse_findings(self.result(warnings=["- `src/lib.rs`:9: unwrap"]))
        assert (f.file, f.line) == ("src/lib.rs", 9)

    def test_empty_result(self):
        assert parse_findings({}) == []


def finding(severity, file, line, end=None):
    return Finding(severity, file, line, end or line, "text")


EXPECTED = [Expected("a.py", 10, "critical"), Expected("b.py", 20, "warning")]


class TestScoreRun:
    def test_everything_found(self):
        score = score_run(
            EXPECTED, [finding("critical", "a.py", 10), finding("warning", "b.py", 21)]
        )
        assert score["found"] == score["found_severity_ok"] == 2
        assert score["false_positives"] == 0 and score["true_positive_findings"] == 2

    def test_tolerance(self):
        assert score_run(EXPECTED, [finding("critical", "a.py", 12)])["found"] == 1
        assert score_run(EXPECTED, [finding("critical", "a.py", 13)])["found"] == 0
        assert (
            score_run(EXPECTED, [finding("critical", "a.py", 13)], tolerance=3)["found"]
            == 1
        )

    def test_tolerance_works_below_the_expected_line(self):
        assert score_run(EXPECTED, [finding("critical", "a.py", 8)])["found"] == 1
        assert score_run(EXPECTED, [finding("critical", "a.py", 7)])["found"] == 0

    def test_range_findings_overlap(self):
        assert (
            score_run(EXPECTED, [finding("warning", "a.py", 5, 9)], tolerance=1)[
                "found"
            ]
            == 1
        )
        assert (
            score_run(EXPECTED, [finding("warning", "a.py", 5, 7)], tolerance=1)[
                "found"
            ]
            == 0
        )

    def test_wrong_file_does_not_match(self):
        score = score_run(EXPECTED, [finding("critical", "c.py", 10)])
        assert score["found"] == 0 and score["false_positives"] == 1

    def test_severity_too_low_is_found_but_not_ok(self):
        score = score_run(EXPECTED, [finding("suggestion", "a.py", 10)])
        assert score["found"] == 1 and score["found_severity_ok"] == 0
        assert score["findings"] == 0  # A suggestion does not count for precision.

    def test_higher_severity_is_ok(self):
        score = score_run(EXPECTED, [finding("critical", "b.py", 20)])
        assert score["found_severity_ok"] == 1

    def test_false_positives_and_extra_suggestions(self):
        score = score_run(
            EXPECTED,
            [
                finding("warning", "a.py", 99),
                finding("critical", "z.py", 1),
                finding("suggestion", "a.py", 50),
                Finding("warning", None, None, None, "no place"),
            ],
        )
        assert score["false_positives"] == 3
        assert score["extra_suggestions"] == 1
        assert score["unanchored"] == 1

    def test_two_findings_for_one_problem_both_count_as_true(self):
        score = score_run(
            EXPECTED, [finding("warning", "a.py", 10), finding("critical", "a.py", 11)]
        )
        assert score["found"] == 1 and score["true_positive_findings"] == 2

    def test_clean_case(self):
        assert score_run([], [finding("warning", "a.py", 1)])["false_positives"] == 1
        assert score_run([], [])["false_positives"] == 0


def run(case, engine_used="agent", clean=False, ok=True, **score):
    base = {
        "expected": 1,
        "found": 1,
        "found_severity_ok": 1,
        "findings": 1,
        "true_positive_findings": 1,
        "false_positives": 0,
        "extra_suggestions": 0,
        "unanchored": 0,
    }
    base.update(score)
    return {
        "case": case,
        "clean": clean,
        "ok": ok,
        "score": base if ok else None,
        "stats": {
            "steps": 6,
            "tokens": 60000,
            "tool_calls": 9,
            "invalid_tool_calls": 1,
            "forced_submit": None,
        }
        if engine_used.startswith("agent")
        else None,
        "duration_sec": 30.0,
        "engine_used": engine_used,
        **({} if ok else {"error": "boom"}),
    }


class TestAggregate:
    def test_totals_and_ratios(self):
        runs = [
            run("a"),
            run(
                "b",
                found=0,
                found_severity_ok=0,
                true_positive_findings=0,
                false_positives=1,
            ),
            run(
                "c",
                clean=True,
                expected=0,
                found=0,
                found_severity_ok=0,
                findings=2,
                true_positive_findings=0,
                false_positives=2,
            ),
            run("d", ok=False),
        ]
        a = aggregate(runs)
        assert (a["runs"], a["failed_runs"]) == (4, 1)
        assert a["expected"] == 2 and a["found"] == 1 and a["recall"] == 0.5
        assert a["findings"] == 4 and a["precision"] == 0.25
        assert a["false_positives"] == 3 and a["false_positives_per_run"] == 1.0
        assert a["clean_runs_with_false_positive"] == 1.0
        assert a["median_steps"] == 6 and a["median_tokens"] == 60000
        assert a["invalid_call_rate"] == pytest.approx(1 / 10)

    def test_fallback_and_forced_submit(self):
        forced = run("a")
        forced["stats"] = dict(forced["stats"], forced_submit="max_steps")
        a = aggregate([run("a", engine_used="agent->classic"), forced])
        assert a["fallback_runs"] == 1
        assert a["forced_submit_rate"] == 0.5

    def test_classic_has_no_agent_figures(self):
        a = aggregate([run("a", engine_used="classic")])
        assert a["median_steps"] is None and a["invalid_call_rate"] is None

    def test_no_division_by_zero(self):
        a = aggregate([run("a", ok=False)])
        assert a["recall"] is None and a["precision"] is None
        assert aggregate([])["runs"] == 0

    def test_per_case(self):
        runs = [run("a"), run("a", found=0, false_positives=2), run("b", ok=False)]
        detail = per_case(runs)
        assert detail["a"]["found_runs"] == [1, 0]
        assert detail["a"]["false_positives"] == [0, 2]
        assert detail["b"]["failed_runs"] == 1 and detail["b"]["expected"] is None


class FakeRunner:
    """Replaces run_review. It returns a result from a function."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, engine, repo, config_file, timeout):
        self.calls.append((engine, repo.name, config_file))
        return self.answer(engine, repo.name)


def perfect_answer(engine, case):
    expected = {c.id: c for c in CASES}[case].expected
    return {
        "status": "success",
        "engine": engine,
        "critical_issues": [
            f"{e.file}:{e.line}: problem" for e in expected if e.kind == "critical"
        ],
        "warnings": [
            f"{e.file}:{e.line}: problem" for e in expected if e.kind == "warning"
        ],
        "suggestions": [],
        "code_suggestions": [],
        "agent_stats": {
            "steps": 5,
            "tokens": 50000,
            "tool_calls": 8,
            "invalid_tool_calls": 0,
            "forced_submit": None,
        }
        if engine == "agent"
        else None,
        "duration_sec": 12.5,
    }


class TestRunEval:
    def test_full_run_writes_the_report(self, tmp_path, capsys):
        runner = FakeRunner(perfect_answer)
        code = run_eval.main(
            [
                "--engines",
                "classic,agent",
                "--runs",
                "2",
                "--out",
                str(tmp_path / "out"),
            ],
            runner=runner,
        )
        assert code == 0
        assert len(runner.calls) == len(CASES) * 2 * 2
        report = (tmp_path / "out" / "report.md").read_text()
        assert "| Metric | classic | agent |" in report
        assert (
            "Recall (problems found) | 12/12 = 100%" in report.replace("  ", " ")
            or "100%" in report
        )
        data = json.loads((tmp_path / "out" / "runs.json").read_text())
        assert set(data["runs"]) == {"classic", "agent"}
        assert data["meta"]["runs"] == 2
        assert "sql-injection" in capsys.readouterr().out

    def test_perfect_answers_give_full_recall_and_precision(self, tmp_path):
        run_eval.main(
            ["--engines", "agent", "--out", str(tmp_path)],
            runner=FakeRunner(perfect_answer),
        )
        runs = json.loads((tmp_path / "runs.json").read_text())["runs"]["agent"]
        a = aggregate(runs)
        assert (
            a["recall"] == 1.0 and a["precision"] == 1.0 and a["false_positives"] == 0
        )

    def test_case_filter_and_engines(self, tmp_path):
        runner = FakeRunner(perfect_answer)
        run_eval.main(
            [
                "--engines",
                "agent",
                "--cases",
                "sql-injection,off-by-one",
                "--out",
                str(tmp_path),
            ],
            runner=runner,
        )
        assert sorted(c[1] for c in runner.calls) == ["off-by-one", "sql-injection"]
        assert {c[0] for c in runner.calls} == {"agent"}

    def test_extra_extensions_reach_the_case_config(self, tmp_path):
        runner = FakeRunner(perfect_answer)
        run_eval.main(
            [
                "--engines",
                "agent",
                "--cases",
                "rust-unwrap-transmute",
                "--out",
                str(tmp_path),
            ],
            runner=runner,
        )
        # The config file exists only while the run lasts. Check the writer directly.
        config = run_eval.write_case_config(
            run_eval.ROOT / "review_config.json", [".rs"], tmp_path / "c.json"
        )
        assert ".rs" in json.loads(config.read_text())["review"]["file_extensions"]
        again = run_eval.write_case_config(config, [".rs"], tmp_path / "d.json")
        assert (
            json.loads(again.read_text())["review"]["file_extensions"].count(".rs") == 1
        )

    def test_failed_runs_are_reported_and_do_not_count(self, tmp_path):
        def answer(engine, case):
            if case == "sql-injection":
                return {"error": "timeout after 5 s", "duration_sec": 5}
            if case == "off-by-one":
                return {
                    "status": "model_unavailable",
                    "warnings": ["x"],
                    "duration_sec": 1,
                }
            return perfect_answer(engine, case)

        run_eval.main(
            ["--engines", "agent", "--out", str(tmp_path)], runner=FakeRunner(answer)
        )
        report = (tmp_path / "report.md").read_text()
        assert "## Failed runs" in report
        assert "agent / sql-injection: timeout after 5 s" in report
        assert "agent / off-by-one: status model_unavailable" in report
        runs = json.loads((tmp_path / "runs.json").read_text())["runs"]["agent"]
        assert aggregate(runs)["failed_runs"] == 2

    def test_clean_case_false_positive_is_counted(self, tmp_path):
        def answer(engine, case):
            result = perfect_answer(engine, case)
            if case == "safe-lookalike":
                result["warnings"] = ["ops/stats.py:10: looks unsafe"]
            return result

        run_eval.main(
            ["--engines", "agent", "--out", str(tmp_path)], runner=FakeRunner(answer)
        )
        a = aggregate(json.loads((tmp_path / "runs.json").read_text())["runs"]["agent"])
        assert a["false_positives"] == 1
        assert a["clean_runs_with_false_positive"] == 0.5  # 1 of 2 clean cases

    def test_list_does_not_run_anything(self, capsys):
        runner = FakeRunner(perfect_answer)
        assert run_eval.main(["--list"], runner=runner) == 0
        assert runner.calls == []
        assert "cross-file-signature" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "argv",
        [["--engines", "turbo"], ["--runs", "0"], ["--cases", "nope"]],
    )
    def test_bad_arguments(self, argv):
        with pytest.raises(SystemExit) as error:
            run_eval.main(argv, runner=FakeRunner(perfect_answer))
        assert error.value.code == 2

    def test_missing_config(self, tmp_path, capsys):
        code = run_eval.main(
            ["--config", str(tmp_path / "none.json"), "--out", str(tmp_path)],
            runner=FakeRunner(perfect_answer),
        )
        assert code == 4 and "config file not found" in capsys.readouterr().err


class TestReport:
    def test_render_with_one_engine(self):
        text = render({"agent": [run("a")]}, {"model": "m", "cases": 1, "runs": 1})
        assert "| Metric | agent |" in text and "Model: m" in text
        assert "## Failed runs" not in text
