"""Deterministic checks: plain code, free, instant, same answer every time.

They run before the judge. If any fails, the case has failed and the judge is skipped.
"""

from pydantic import BaseModel

from agent.protocol import AgentResult
from datasets.schema import Case


class Budgets(BaseModel):
    max_case_cost_usd: float = 0.01
    max_case_latency_ms: float = 30_000  # one run; generous so only real hangs/loops trip it
    max_p95_latency_ms: float = 15_000  # whole eval run
    max_total_cost_usd: float = 0.50  # agent cost for the whole eval run (judge cost is reported separately)


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


def run_checks(case: Case, result: AgentResult, latency_ms: float, cost_usd: float, budgets: Budgets) -> list[CheckResult]:
    checks: list[CheckResult] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append(CheckResult(name=name, passed=passed, detail="" if passed else detail))

    resp = result.response
    add("valid_json", resp is not None and result.error is None, result.error or "no parsed response")

    if resp is not None:
        add(
            "action",
            resp.action in case.allowed_actions,
            f"got '{resp.action}', expected one of {case.allowed_actions}",
        )
        if case.expected_order_id is not None:
            got = (resp.order_id or "").strip().upper()
            add("order_id", got == case.expected_order_id.upper(), f"got {resp.order_id!r}, expected {case.expected_order_id!r}")

    called = {t.name for t in result.tool_calls}
    missing = [t for t in case.must_call if t not in called]
    add("must_call", not missing, f"never called {missing}")
    forbidden = [t for t in case.must_not_call if t in called]
    add("must_not_call", not forbidden, f"called forbidden {forbidden}")

    add("cost", cost_usd <= budgets.max_case_cost_usd, f"${cost_usd:.4f} > ${budgets.max_case_cost_usd}")
    add("latency", latency_ms <= budgets.max_case_latency_ms, f"{latency_ms:,.0f}ms > {budgets.max_case_latency_ms:,.0f}ms")

    return checks
