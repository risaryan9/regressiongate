import json

import pytest

from tracing.pricing import cost_usd
from tracing.stats import percentile
from tracing.store import TraceStore
from tracing.trace import current_trace_id, mark_error, run_scope, set_store, set_tokens, trace
from tracing.tree import render_tree


@pytest.fixture
def store(tmp_path):
    s = TraceStore(str(tmp_path / "traces.db"))
    set_store(s)
    return s


# --- pricing ---------------------------------------------------------------


def test_cost_known_model():
    # 1M in at $0.10 + 1M out at $0.50
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)


def test_cost_unknown_model_is_none():
    assert cost_usd("some-other-model", 100, 100) is None


# --- percentile ------------------------------------------------------------


def test_percentile_empty_is_none():
    assert percentile([], 0.95) is None


def test_percentile_matches_nearest_rank_round_down():
    values = list(range(1, 21))  # 1..20, deliberately passed unsorted below
    assert percentile(list(reversed(values)), 0.50) == 10  # index int(0.5*19)=9
    assert percentile(values, 0.95) == 19  # index int(0.95*19)=18 -> second slowest


# --- @trace ----------------------------------------------------------------


@trace(kind="tool")
def add(a, b):
    return {"sum": a + b}


@trace(kind="llm", name="fake.llm")
def fake_llm():
    set_tokens("claude-haiku-5-5", 1000, 200)
    return "ok"


@trace(kind="agent", name="agent.run")
def fake_agent():
    fake_llm()
    add(1, 2)
    return current_trace_id()


def test_nested_spans_share_trace_and_link_parents(store):
    trace_id = fake_agent()
    spans = {s.name: s for s in store.get_trace(trace_id)}

    assert set(spans) == {"agent.run", "fake.llm", "add"}
    root = spans["agent.run"]
    assert root.parent_id is None
    assert spans["fake.llm"].parent_id == root.span_id
    assert spans["add"].parent_id == root.span_id
    assert json.loads(spans["add"].input) == {"a": 1, "b": 2}
    assert json.loads(spans["add"].output) == {"sum": 3}
    assert all(s.latency_ms is not None and s.status == "ok" for s in spans.values())


def test_set_tokens_records_cost(store):
    trace_id = fake_agent()
    llm = next(s for s in store.get_trace(trace_id) if s.kind == "llm")
    assert (llm.model, llm.tokens_in, llm.tokens_out) == ("claude-haiku-5-5", 1000, 200)
    assert llm.cost_usd == pytest.approx(cost_usd("claude-haiku-5-5", 1000, 200))


def test_separate_calls_get_separate_traces(store):
    assert fake_agent() != fake_agent()


def test_exception_is_recorded_and_reraised(store):
    @trace(kind="tool")
    def boom():
        raise ValueError("bad input")

    @trace(kind="agent")
    def runner():
        tid = current_trace_id()
        with pytest.raises(ValueError):
            boom()
        return tid

    spans = {s.name: s for s in store.get_trace(runner())}
    assert spans["boom"].status == "error"
    assert spans["boom"].error == "ValueError: bad input"
    assert spans["runner"].status == "ok"  # the caller handled it


def test_mark_error_flags_span_without_raising(store):
    @trace(kind="agent")
    def runner():
        mark_error("invalid JSON output")
        return current_trace_id()

    (span,) = store.get_trace(runner())
    assert span.status == "error" and span.error == "invalid JSON output"


def test_run_scope_tags_spans_and_feeds_latencies(store):
    with run_scope("run-1"):
        fake_agent()
        fake_agent()
    fake_agent()  # outside the run, must not be counted

    assert len(store.latencies("run-1")) == 2
    assert len(store.latencies("run-1", kind="tool")) == 2


def test_helpers_are_noops_outside_a_span():
    set_tokens("claude-haiku-5-5", 1, 1)
    mark_error("nothing to mark")
    assert current_trace_id() is None


# --- tree ------------------------------------------------------------------


def test_render_tree_nests_children(store):
    lines = render_tree(store.get_trace(fake_agent())).splitlines()
    assert lines[0].startswith("agent agent.run")
    assert lines[1].startswith("├── llm   fake.llm")
    assert lines[2].startswith("└── tool  add")
    assert '→ {"sum":3}' in lines[2]


def test_find_traces_by_prefix(store):
    trace_id = fake_agent()
    assert store.find_traces(trace_id[:8]) == [trace_id]
