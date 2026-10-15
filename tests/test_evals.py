from pathlib import Path

import pytest

from agent.protocol import AgentResult, TicketResponse, ToolCall
from datasets.schema import Case
from evals.cache import JudgeCache
from evals.checks import Budgets, run_checks
from evals.judge import PASS_SCORE, JudgeResult, LLMJudge, Verdict, render_input
from evals.runner import NotComparable, compare, run_dataset
from tracing.store import TraceStore
from tracing.trace import set_store

DATASET = Path(__file__).parent.parent / "datasets" / "support"

CASE = Case(
    id="refund_a1001",
    ticket="A1001 arrived broken",
    allowed_actions=["refund"],
    expected_order_id="A1001",
    must_call=["lookup_order", "check_refund_policy"],
    must_not_call=["escalate"],
    reply_criteria="Approves the refund.",
)


def make_result(action="refund", order_id="A1001", tools=("lookup_order", "check_refund_policy"), error=None, parsed=True):
    return AgentResult(
        ticket="t",
        response=TicketResponse(action=action, order_id=order_id, reply="Refund approved.") if parsed else None,
        raw_output="...",
        tool_calls=[ToolCall(name=t, input={}, output={}) for t in tools],
        model="claude-haiku-5-5",
        prompt_version="v1",
        tokens_in=1000,
        tokens_out=100,
        error=error,
    )


@pytest.fixture(autouse=True)
def tmp_store(tmp_path):
    set_store(TraceStore(str(tmp_path / "traces.db")))


def failed(checks):
    return {c.name for c in checks if not c.passed}


# --- deterministic checks --------------------------------------------------


def test_all_checks_pass_for_correct_result():
    assert failed(run_checks(CASE, make_result(), 1000, 0.001, Budgets())) == set()


def test_wrong_action_and_order():
    checks = run_checks(CASE, make_result(action="deny_refund", order_id="A1004"), 1000, 0.001, Budgets())
    assert failed(checks) == {"action", "order_id"}


def test_order_id_is_case_insensitive():
    assert failed(run_checks(CASE, make_result(order_id="a1001"), 1000, 0.001, Budgets())) == set()


def test_tool_rules():
    checks = run_checks(CASE, make_result(tools=("lookup_order", "escalate")), 1000, 0.001, Budgets())
    assert failed(checks) == {"must_call", "must_not_call"}


def test_invalid_json_skips_response_checks():
    checks = run_checks(CASE, make_result(parsed=False, error="invalid JSON output"), 1000, 0.001, Budgets())
    assert "valid_json" in failed(checks)
    assert not {"action", "order_id"} & {c.name for c in checks}


def test_cost_and_latency_budgets():
    checks = run_checks(CASE, make_result(), 99_999, 0.5, Budgets())
    assert failed(checks) == {"cost", "latency"}


# --- judge -----------------------------------------------------------------


def make_judge(tmp_path, verdict: Verdict) -> tuple[LLMJudge, list]:
    """An LLMJudge whose API call is replaced by a stub that counts calls."""
    judge = LLMJudge.__new__(LLMJudge)
    judge.model, judge.rubric_version, judge.effort = "claude-sonnet-5-5", "v1", "high"
    judge.cache = JudgeCache(str(tmp_path / "cache.db"))
    calls = []
    judge._call = lambda prompt: (calls.append(prompt), (verdict, 0.01))[1]
    return judge, calls


def test_judge_caches_identical_inputs(tmp_path):
    judge, calls = make_judge(tmp_path, Verdict(reason="ok", score=5, passed=True))
    first = judge.judge(CASE, make_result())
    second = judge.judge(CASE, make_result())
    assert len(calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert second.passed and second.cost_usd == 0.0


def test_judge_cache_misses_when_reply_changes(tmp_path):
    judge, calls = make_judge(tmp_path, Verdict(reason="ok", score=5, passed=True))
    judge.judge(CASE, make_result())
    judge.judge(CASE, make_result(order_id="A1001 "))  # different output text -> different key
    assert len(calls) == 2


def test_judge_cache_misses_when_effort_changes(tmp_path):
    judge, calls = make_judge(tmp_path, Verdict(reason="ok", score=5, passed=True))
    judge.judge(CASE, make_result())
    judge.effort = "medium"
    judge.judge(CASE, make_result())
    assert len(calls) == 2


def test_inconsistent_verdict_fails(tmp_path):
    judge, _ = make_judge(tmp_path, Verdict(reason="meh", score=PASS_SCORE - 1, passed=True))
    assert judge.judge(CASE, make_result()).passed is False


def test_render_input_wraps_ticket_and_shows_tools():
    text = render_input(CASE, make_result())
    assert "<ticket>\nA1001 arrived broken\n</ticket>" in text
    assert "- lookup_order({}) -> {}" in text


# --- runner ----------------------------------------------------------------


class FakeAgent:
    """Gets every case right except the ones listed in wrong."""

    def __init__(self, wrong=(), crash=()):
        self.wrong, self.crash = set(wrong), set(crash)
        self.cases = {}

    def run(self, ticket):
        case = self.cases[ticket]
        if case.id in self.crash:
            raise RuntimeError("boom")
        action = case.allowed_actions[0]
        if case.id in self.wrong:
            action = next(a for a in ("refund", "deny_refund", "escalate", "answer") if a not in case.allowed_actions)
        return make_result(action=action, order_id=case.expected_order_id, tools=tuple(case.must_call))


class FakeJudge:
    model, rubric_version, effort = "fake-judge", "v1", "high"

    def __init__(self):
        self.calls = 0

    def judge(self, case, result):
        self.calls += 1
        return JudgeResult(verdict=Verdict(reason="fine", score=5, passed=True), passed=True, cached=False)


def fake_agent(**kw):
    from datasets.dataset import load_cases

    agent = FakeAgent(**kw)
    cases, _, _ = load_cases(DATASET)
    agent.cases = {c.ticket: c for c in cases}
    return agent, cases


def test_run_all_pass():
    agent, cases = fake_agent()
    judge = FakeJudge()
    result = run_dataset(DATASET, agent, judge, workers=4)
    assert result.pass_rate == 100.0 and result.total == len(cases)
    assert judge.calls == len(cases)
    assert all(a.trace_id for c in result.cases for a in c.attempts)


def test_hard_check_failure_skips_judge():
    agent, cases = fake_agent(wrong=["refund_damaged_a1001"])
    judge = FakeJudge()
    result = run_dataset(DATASET, agent, judge)
    outcome = next(c for c in result.cases if c.case_id == "refund_damaged_a1001")
    assert not outcome.passed and outcome.attempts[0].judge is None
    assert judge.calls == len(cases) - 1


def test_agent_crash_fails_only_that_case():
    agent, cases = fake_agent(crash=["asks_for_human"])
    result = run_dataset(DATASET, agent, FakeJudge())
    assert result.passed == len(cases) - 1
    crashed = next(c for c in result.cases if c.case_id == "asks_for_human")
    assert "agent crashed" in crashed.attempts[0].error


def test_repeats_and_majority_vote():
    agent, cases = fake_agent()
    result = run_dataset(DATASET, agent, FakeJudge(), repeats=3)
    assert result.meta.repeats == 3
    assert all(len(c.attempts) == 3 for c in result.cases)


def test_spans_are_tagged_with_run_id(tmp_path):
    store = TraceStore(str(tmp_path / "t.db"))
    set_store(store)
    agent, cases = fake_agent()
    result = run_dataset(DATASET, agent, FakeJudge())
    assert len(store.latencies(result.meta.run_id, kind="eval")) == len(cases)


# --- baseline comparison ---------------------------------------------------


def run_with(wrong=(), repeats=1):
    agent, _ = fake_agent(wrong=wrong)
    return run_dataset(DATASET, agent, FakeJudge(), repeats=repeats)


def test_no_baseline_passes_within_budget():
    cmp = compare(run_with(), None, 5.0, Budgets())
    assert not cmp.failed and cmp.pass_rate_delta is None


def test_missing_baseline_fails_when_required():
    cmp = compare(run_with(), None, 5.0, Budgets(), require_baseline=True)
    assert cmp.failed and "no baseline for dataset support" in cmp.reasons[0]


def test_one_flip_is_within_threshold_two_is_not():
    baseline = run_with()
    one = compare(run_with(wrong=["refund_damaged_a1001"]), baseline, 5.0, Budgets())
    assert not one.failed and one.newly_failing == ["refund_damaged_a1001"]  # 4 points < 5

    two = compare(run_with(wrong=["refund_damaged_a1001", "asks_for_human"]), baseline, 5.0, Budgets())
    assert two.failed and "pass rate dropped 8.0 points" in two.reasons[0]


def test_hard_regression_fails_even_when_pass_rate_rises():
    baseline = run_with(wrong=["asks_for_human", "legal_threat_a1003"], repeats=3)
    # One solid case breaks while two others recover: pass rate goes up, but it must still fail.
    run = run_with(wrong=["refund_damaged_a1001"], repeats=3)
    cmp = compare(run, baseline, 5.0, Budgets())
    assert cmp.pass_rate_delta > 0
    assert cmp.failed
    assert cmp.reasons == ["hard regression: refund_damaged_a1001 passed 3/3 in baseline, now 0/3"]


def test_hard_regression_rule_off_with_one_repeat():
    cmp = compare(run_with(wrong=["refund_damaged_a1001"]), run_with(), 5.0, Budgets())
    assert not cmp.failed  # a single-repeat flip could be noise; the 5-point rule handles it


def test_improvement_is_reported():
    baseline = run_with(wrong=["asks_for_human"])
    cmp = compare(run_with(), baseline, 5.0, Budgets())
    assert not cmp.failed and cmp.newly_passing == ["asks_for_human"]


def test_different_repeats_are_not_comparable():
    with pytest.raises(NotComparable, match="--repeats 1"):
        compare(run_with(repeats=3), run_with(repeats=1), 5.0, Budgets())


def test_budgets_fail_even_without_regression():
    run = run_with()
    tight = Budgets(max_total_cost_usd=0.0, max_p95_latency_ms=-1)
    cmp = compare(run, run, 5.0, tight)
    assert cmp.failed and len(cmp.reasons) == 2
