"""Markdown summary of an eval run, posted as a PR comment by CI."""

from evals.runner import Comparison, RunResult

MAX_REASON_CHARS = 200


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f}%"


def _ms(x: float | None) -> str:
    return "-" if x is None else f"{x:,.0f}ms"


def _short(text: str) -> str:
    text = " ".join(text.split()).replace("|", "\\|")  # one line, and no pipes to break the table
    return text if len(text) <= MAX_REASON_CHARS else text[: MAX_REASON_CHARS - 1] + "…"


def render_markdown(
    run: RunResult,
    baseline: RunResult | None,
    cmp: Comparison | None,
    error: str | None = None,
    traces_hint: str | None = None,
) -> str:
    """error is set when the run couldn't be compared at all (e.g. mismatched repeats)."""
    m = run.meta
    if error:
        status = "⚠️ **Not comparable**"
    elif cmp is not None and cmp.failed:
        status = "❌ **FAIL**"
    else:
        status = "✅ **PASS**"

    lines = [f"## RegressionGate eval: {status}", ""]
    if error:
        lines += [f"> {error}", ""]
    if cmp is not None and cmp.reasons:
        lines += [f"- {r}" for r in cmp.reasons] + [""]

    base_rate = _pct(baseline.pass_rate) if baseline else "no baseline"
    delta = f"{cmp.pass_rate_delta:+.1f}" if cmp is not None and cmp.pass_rate_delta is not None else "-"
    lines += [
        "| | Baseline | This PR | Change |",
        "|---|---|---|---|",
        f"| Pass rate | {base_rate} | {_pct(run.pass_rate)} ({run.attempts_passed}/{run.attempts_total}) | {delta} |",
        f"| p95 latency | {_ms(baseline.p95_latency_ms) if baseline else '-'} | {_ms(run.p95_latency_ms)} | |",
        f"| Agent cost | {f'${baseline.agent_cost_usd:.4f}' if baseline else '-'} | ${run.agent_cost_usd:.4f} | |",
        f"| Prompt | {baseline.meta.prompt_version if baseline else '-'} | {m.prompt_version} | |",
        f"| Agent model | {baseline.meta.agent_model if baseline else '-'} | {m.agent_model} | |",
        "",
    ]

    if cmp is not None and cmp.newly_failing:
        lines += ["**Newly failing:** " + ", ".join(f"`{c}`" for c in cmp.newly_failing), ""]
    if cmp is not None and cmp.newly_passing:
        lines += ["**Newly passing:** " + ", ".join(f"`{c}`" for c in cmp.newly_passing), ""]

    failing = [c for c in run.cases if not c.passed]
    if failing:
        lines += [
            f"<details><summary>{len(failing)} failing case(s)</summary>",
            "",
            "| Case | Votes | Trace | Why |",
            "|---|---|---|---|",
        ]
        for c in failing:
            votes = f"{sum(a.passed for a in c.attempts)}/{len(c.attempts)}"
            worst = next(a for a in c.attempts if not a.passed)
            lines.append(f"| `{c.case_id}` | {votes} | `{(worst.trace_id or '')[:8]}` | {_short(worst.why)} |")
        lines += ["", "</details>", ""]

    lines.append(
        f"<sub>dataset {m.dataset} v{m.dataset_version} · judge {m.judge_model} rubric {m.rubric_version} "
        f"effort {m.judge_effort} · repeats {m.repeats} · judge cost ${run.judge_cost_usd:.4f} · run `{m.run_id}`</sub>"
    )
    if traces_hint:
        lines += ["", f"<sub>{traces_hint}</sub>"]
    return "\n".join(lines) + "\n"
