import json

from typer.testing import CliRunner

from evals.checks import Budgets
from evals.report import render_markdown
from evals.runner import compare
from tests.test_evals import run_with


def test_pass_report_has_table_and_no_failures():
    baseline = run_with()
    run = run_with()
    md = render_markdown(run, baseline, compare(run, baseline, 10.0, Budgets()))
    assert md.startswith("## RegressionGate eval: ✅ **PASS**")
    assert "| Pass rate | 100.0% | 100.0% (25/25) | +0.0 |" in md
    assert "failing case" not in md


def test_fail_report_lists_reasons_newly_failing_and_traces():
    baseline = run_with(repeats=3)
    run = run_with(wrong=["refund_damaged_a1001"], repeats=3)
    md = render_markdown(run, baseline, compare(run, baseline, 10.0, Budgets()), traces_hint="see artifact")
    assert "❌ **FAIL**" in md
    assert "- hard regression: refund_damaged_a1001 passed 3/3 in baseline, now 0/3" in md
    assert "**Newly failing:** `refund_damaged_a1001`" in md
    row = next(line for line in md.splitlines() if line.startswith("| `refund_damaged_a1001`"))
    assert "| 0/3 |" in row and "action: got" in row
    assert md.rstrip().endswith("<sub>see artifact</sub>")


def test_not_comparable_report():
    run = run_with()
    md = render_markdown(run, None, None, error="baseline used --repeats 1")
    assert "⚠️ **Not comparable**" in md and "> baseline used --repeats 1" in md


def test_reason_with_pipes_and_newlines_stays_in_one_table_cell():
    run = run_with(wrong=["asks_for_human"])
    attempt = next(c for c in run.cases if c.case_id == "asks_for_human").attempts[0]
    attempt.error = "line one\nline | two"
    md = render_markdown(run, None, None)
    row = next(line for line in md.splitlines() if line.startswith("| `asks_for_human`"))
    assert "line one line \\| two" in row


def test_cli_require_baseline_without_baseline_fails_cleanly(tmp_path, monkeypatch):
    """Regression: this used to crash on baseline.meta when no baseline existed."""
    import cli
    from tests.test_evals import FakeJudge, fake_agent

    agent, _ = fake_agent()
    monkeypatch.setattr("agent.agent.SupportAgent", lambda: agent)
    monkeypatch.setattr("evals.judge.LLMJudge", FakeJudge)
    monkeypatch.chdir(tmp_path)  # runs/ and report.md land in the temp dir
    from tests.test_evals import DATASET

    result = CliRunner().invoke(
        cli.app,
        ["run", "--dataset", str(DATASET), "--require-baseline", "--baselines-dir", str(tmp_path / "none"),
         "--report", "report.md"],
    )
    assert result.exit_code == 1, result.output
    assert "no baseline for dataset support" in result.output
    assert "❌ **FAIL**" in (tmp_path / "report.md").read_text()
    assert json.loads(next((tmp_path / "runs").iterdir()).read_text())["total"] == 25
