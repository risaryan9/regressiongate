"""Run a dataset through an agent, score every case, and compare against a baseline.

The runner only knows the Agent protocol (agent.run(ticket) -> AgentResult), never agent internals.
"""

import contextvars
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from agent.protocol import Agent, AgentResult
from datasets.dataset import load_cases, load_manifest
from datasets.schema import Case
from evals.checks import Budgets, CheckResult, run_checks
from evals.judge import JudgeResult
from tracing.pricing import cost_usd
from tracing.stats import percentile
from tracing.trace import current_trace_id, mark_error, run_scope, trace


class Judge(Protocol):
    model: str
    rubric_version: str

    def judge(self, case: Case, result: AgentResult) -> JudgeResult: ...


class Attempt(BaseModel):
    """One run of one case."""

    repeat: int
    trace_id: str | None
    passed: bool
    checks: list[CheckResult] = []
    judge: JudgeResult | None = None  # None when a hard check failed (judge skipped)
    latency_ms: float
    agent_cost_usd: float = 0.0
    error: str | None = None  # the agent or judge crashed

    @property
    def why(self) -> str:
        if self.error:
            return self.error
        failed = [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]
        if failed:
            return "; ".join(failed)
        return self.judge.verdict.reason if self.judge else ""


class CaseOutcome(BaseModel):
    case_id: str
    passed: bool  # majority vote over attempts
    attempts: list[Attempt]


class RunMeta(BaseModel):
    run_id: str
    started_at: str
    dataset: str
    dataset_version: int
    dataset_hash: str
    prompt_version: str
    agent_model: str
    judge_model: str
    rubric_version: str
    repeats: int


class RunResult(BaseModel):
    meta: RunMeta
    pass_rate: float  # percent, 0-100
    passed: int
    total: int
    agent_cost_usd: float
    judge_cost_usd: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    cases: list[CaseOutcome]

    def case_passed(self) -> dict[str, bool]:
        return {c.case_id: c.passed for c in self.cases}


class Comparison(BaseModel):
    failed: bool
    reasons: list[str]  # why the run failed; empty when it passed
    pass_rate_delta: float | None = None  # points vs baseline; None when there is no baseline
    newly_failing: list[str] = []
    newly_passing: list[str] = []


class NotComparable(Exception):
    """The baseline was measured differently (e.g. other repeats), so comparing would mislead."""


# --- running ---------------------------------------------------------------


def run_dataset(
    dataset_dir: Path,
    agent: Agent,
    judge: Judge,
    repeats: int = 1,
    budgets: Budgets | None = None,
    workers: int = 5,
) -> RunResult:
    budgets = budgets or Budgets()
    manifest = load_manifest(dataset_dir)
    cases, _, errors = load_cases(dataset_dir)
    if errors:
        raise ValueError("dataset is invalid; run `rgate validate` first:\n" + "\n".join(errors))

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    started_at = datetime.now(UTC).isoformat()
    jobs = [(case, r) for case in cases for r in range(repeats)]

    with run_scope(run_id), ThreadPoolExecutor(max_workers=workers) as pool:
        # Each job gets its own copy of the context so worker threads see run_id and
        # keep their own "current span" instead of sharing one.
        futures = [
            pool.submit(contextvars.copy_context().run, _run_case, case, r, agent, judge, budgets) for case, r in jobs
        ]
        attempts = [f.result() for f in futures]

    by_case: dict[str, list[Attempt]] = {c.id: [] for c in cases}
    agent_meta: dict[str, str] = {}
    for (case, _), (attempt, meta) in zip(jobs, attempts):
        by_case[case.id].append(attempt)
        agent_meta = agent_meta or meta

    outcomes = [
        CaseOutcome(case_id=cid, passed=sum(a.passed for a in atts) * 2 > len(atts), attempts=atts)
        for cid, atts in by_case.items()
    ]
    all_attempts = [a for o in outcomes for a in o.attempts]
    latencies = [a.latency_ms for a in all_attempts]
    passed = sum(o.passed for o in outcomes)

    return RunResult(
        meta=RunMeta(
            run_id=run_id,
            started_at=started_at,
            dataset=manifest.name,
            dataset_version=manifest.version,
            dataset_hash=manifest.sha256,
            prompt_version=agent_meta.get("prompt_version", "unknown"),
            agent_model=agent_meta.get("model", "unknown"),
            judge_model=judge.model,
            rubric_version=judge.rubric_version,
            repeats=repeats,
        ),
        pass_rate=100 * passed / len(outcomes) if outcomes else 0.0,
        passed=passed,
        total=len(outcomes),
        agent_cost_usd=sum(a.agent_cost_usd for a in all_attempts),
        judge_cost_usd=sum(a.judge.cost_usd for a in all_attempts if a.judge),
        p50_latency_ms=percentile(latencies, 0.50),
        p95_latency_ms=percentile(latencies, 0.95),
        cases=outcomes,
    )


@trace(kind="eval", name="eval.case")
def _run_case(case: Case, repeat: int, agent: Agent, judge: Judge, budgets: Budgets) -> tuple[Attempt, dict]:
    trace_id = current_trace_id()
    start = time.perf_counter()
    try:
        result = agent.run(case.ticket)
    except Exception as e:  # an agent crash fails this case, not the whole run
        mark_error(f"agent crashed: {e}")
        latency = (time.perf_counter() - start) * 1000
        return Attempt(repeat=repeat, trace_id=trace_id, passed=False, latency_ms=latency, error=f"agent crashed: {type(e).__name__}: {e}"), {}
    latency = (time.perf_counter() - start) * 1000

    meta = {"model": result.model, "prompt_version": result.prompt_version}
    cost = cost_usd(result.model, result.tokens_in, result.tokens_out) or 0.0
    checks = run_checks(case, result, latency, cost, budgets)
    base = dict(repeat=repeat, trace_id=trace_id, checks=checks, latency_ms=latency, agent_cost_usd=cost)

    if not all(c.passed for c in checks):
        mark_error("hard check failed: " + ", ".join(c.name for c in checks if not c.passed))
        return Attempt(**base, passed=False), meta

    try:
        verdict = judge.judge(case, result)
    except Exception as e:
        mark_error(f"judge crashed: {e}")
        return Attempt(**base, passed=False, error=f"judge crashed: {type(e).__name__}: {e}"), meta
    if not verdict.passed:
        mark_error(f"judge: {verdict.verdict.reason}")
    return Attempt(**base, passed=verdict.passed, judge=verdict), meta


# --- baselines -------------------------------------------------------------


def baseline_path(baselines_dir: Path, dataset_hash: str) -> Path:
    return baselines_dir / f"{dataset_hash}.json"


def load_baseline(baselines_dir: Path, dataset_hash: str) -> RunResult | None:
    path = baseline_path(baselines_dir, dataset_hash)
    return RunResult.model_validate_json(path.read_text()) if path.is_file() else None


def save_result(result: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n")


def compare(
    run: RunResult, baseline: RunResult | None, threshold: float, budgets: Budgets, require_baseline: bool = False
) -> Comparison:
    """Decide whether this run fails. Budgets always apply; the pass-rate rule needs a baseline.

    require_baseline (used in CI) turns "no baseline" into a failure, so editing the dataset
    can't silently skip the regression check.
    """
    reasons: list[str] = []

    if run.agent_cost_usd > budgets.max_total_cost_usd:
        reasons.append(f"agent cost ${run.agent_cost_usd:.4f} > budget ${budgets.max_total_cost_usd}")
    if run.p95_latency_ms is not None and run.p95_latency_ms > budgets.max_p95_latency_ms:
        reasons.append(f"p95 latency {run.p95_latency_ms:,.0f}ms > budget {budgets.max_p95_latency_ms:,.0f}ms")

    if baseline is None:
        if require_baseline:
            reasons.append(
                f"no baseline for dataset {run.meta.dataset} v{run.meta.dataset_version} "
                f"(hash {run.meta.dataset_hash[:12]}); save one with --save-baseline in this PR"
            )
        return Comparison(failed=bool(reasons), reasons=reasons)

    if baseline.meta.repeats != run.meta.repeats:
        raise NotComparable(
            f"baseline used --repeats {baseline.meta.repeats}, this run used --repeats {run.meta.repeats}; "
            "rerun with the same repeats"
        )

    delta = run.pass_rate - baseline.pass_rate
    if -delta > threshold:
        reasons.append(
            f"pass rate dropped {-delta:.1f} points ({baseline.pass_rate:.1f}% -> {run.pass_rate:.1f}%), "
            f"threshold is {threshold:g}"
        )

    before, after = baseline.case_passed(), run.case_passed()
    common = [cid for cid in after if cid in before]

    # A noisy case drifts 1/3 <-> 2/3; going from all-pass to all-fail is a real break even
    # when other cases improved by luck and the pass rate looks fine. Needs >1 repeat to mean anything.
    if run.meta.repeats > 1:
        base_attempts = {c.case_id: c.attempts for c in baseline.cases}
        for case in run.cases:
            old = base_attempts.get(case.case_id)
            if old and all(a.passed for a in old) and not any(a.passed for a in case.attempts):
                reasons.append(
                    f"hard regression: {case.case_id} passed {len(old)}/{len(old)} in baseline, "
                    f"now 0/{len(case.attempts)}"
                )

    return Comparison(
        failed=bool(reasons),
        reasons=reasons,
        pass_rate_delta=delta,
        newly_failing=[cid for cid in common if before[cid] and not after[cid]],
        newly_passing=[cid for cid in common if not before[cid] and after[cid]],
    )


def summary_dict(run: RunResult) -> dict:
    """Small JSON-friendly summary for printing or CI logs."""
    return json.loads(run.model_dump_json(exclude={"cases"}))
