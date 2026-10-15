"""rgate: command-line entry point for the RegressionGate harness."""

from pathlib import Path

import typer

from datasets.dataset import bump as bump_dataset
from datasets.dataset import load_manifest, manifest_at_ref, validate as validate_dataset
from tracing.store import TraceStore
from tracing.tree import render_tree

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Eval and tracing harness for LLM agents."""
    # An explicit callback keeps `rgate trace` a subcommand even while it's the only command.


@app.command()
def trace(
    trace_id: str = typer.Argument(..., help="Trace ID, or a unique prefix of one."),
    db: str = typer.Option(None, help="Path to the trace database (default: $TRACE_DB or traces.db)."),
) -> None:
    """Print the span tree for one trace."""
    store = TraceStore(db) if db else TraceStore()
    matches = store.find_traces(trace_id)
    if not matches:
        typer.echo(f"No trace found for '{trace_id}'.", err=True)
        raise typer.Exit(1)
    if len(matches) > 1:
        typer.echo(f"'{trace_id}' matches {len(matches)} traces; use more characters.", err=True)
        raise typer.Exit(1)
    typer.echo(f"trace {matches[0]}")
    typer.echo(render_tree(store.get_trace(matches[0])))


@app.command()
def validate(
    dataset_dir: Path = typer.Argument(..., help="Dataset folder with cases.jsonl and manifest.json."),
    base: str = typer.Option("HEAD", help="Git ref to compare against. CI should pass origin/main."),
) -> None:
    """Check the dataset's schema and hash, and that changed data came with a version bump."""
    base_manifest = manifest_at_ref(dataset_dir, base)
    errors = validate_dataset(dataset_dir, base_manifest)
    if errors:
        typer.echo(f"✗ {dataset_dir}: {len(errors)} problem(s)", err=True)
        for e in errors:
            typer.echo(f"  - {e}", err=True)
        raise typer.Exit(1)
    m = load_manifest(dataset_dir)
    note = f"compared to {base} (v{base_manifest.version})" if base_manifest else f"no manifest at {base}, skipped bump check"
    typer.echo(f"✓ {m.name} v{m.version}: {m.row_count} cases, sha256 {m.sha256[:12]}… ({note})")


@app.command()
def bump(dataset_dir: Path = typer.Argument(..., help="Dataset folder to bump.")) -> None:
    """After editing cases.jsonl: bump the version and record the new hash and row count."""
    try:
        m = bump_dataset(dataset_dir)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"bumped {m.name} to v{m.version}: {m.row_count} cases, sha256 {m.sha256[:12]}…")


@app.command()
def run(
    dataset: Path = typer.Option(Path("datasets/support"), help="Dataset folder to run."),
    repeats: int = typer.Option(1, min=1, help="Runs per case; majority vote decides. Use 3 for CI and baselines."),
    threshold: float = typer.Option(10.0, help="Max allowed pass-rate drop vs baseline, in percentage points."),
    save_baseline: bool = typer.Option(False, "--save-baseline", help="Store this run as the baseline for this dataset."),
    baselines_dir: Path = typer.Option(Path("baselines"), help="Where baselines live."),
    workers: int = typer.Option(5, min=1, help="Cases run in parallel."),
    require_baseline: bool = typer.Option(
        False, "--require-baseline", help="Fail if this dataset version has no baseline. CI should set this."
    ),
) -> None:
    """Run the dataset through the agent, score it, and compare against the baseline."""
    # Imported here so `rgate trace` / `rgate validate` work without an API key or network.
    from agent.agent import SupportAgent
    from evals.judge import LLMJudge
    from evals.runner import (
        NotComparable,
        baseline_path,
        compare,
        load_baseline,
        run_dataset,
        save_result,
    )
    from evals.checks import Budgets

    budgets = Budgets()
    try:
        result = run_dataset(dataset, SupportAgent(), LLMJudge(), repeats=repeats, budgets=budgets, workers=workers)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)

    for case in result.cases:
        mark = "✓" if case.passed else "✗"
        votes = f" ({sum(a.passed for a in case.attempts)}/{len(case.attempts)})" if repeats > 1 else ""
        line = f"{mark} {case.case_id}{votes}"
        failing = next((a for a in case.attempts if not a.passed), None)
        if not case.passed and failing:
            line += f"  [{(failing.trace_id or '')[:8]}] {failing.why}"
        typer.echo(line)

    m = result.meta
    p50 = f"{result.p50_latency_ms:,.0f}ms" if result.p50_latency_ms is not None else "-"
    p95 = f"{result.p95_latency_ms:,.0f}ms" if result.p95_latency_ms is not None else "-"
    typer.echo(
        f"\n{m.dataset} v{m.dataset_version} | prompt {m.prompt_version} | {m.agent_model} | judge {m.judge_model} "
        f"rubric {m.rubric_version} effort {m.judge_effort} | repeats {m.repeats}"
    )
    typer.echo(
        f"pass rate {result.pass_rate:.1f}% ({result.attempts_passed}/{result.attempts_total} attempts, "
        f"{result.passed}/{result.total} cases) | p50 {p50} p95 {p95} | "
        f"agent ${result.agent_cost_usd:.4f} judge ${result.judge_cost_usd:.4f}"
    )

    run_file = Path("runs") / f"{m.run_id}.json"
    save_result(result, run_file)
    typer.echo(f"saved {run_file}")

    if save_baseline:
        path = baseline_path(baselines_dir, m.dataset_hash)
        save_result(result, path)
        typer.echo(f"baseline saved to {path}")
        return

    baseline = load_baseline(baselines_dir, m.dataset_hash)
    try:
        cmp = compare(result, baseline, threshold, budgets, require_baseline=require_baseline)
    except NotComparable as e:
        typer.echo(f"✗ cannot compare: {e}", err=True)
        raise typer.Exit(2)

    if baseline is None and not require_baseline:
        typer.echo("no baseline for this dataset version yet; save one with --save-baseline")
    else:
        typer.echo(f"vs baseline {baseline.meta.run_id}: {baseline.pass_rate:.1f}% -> {result.pass_rate:.1f}% ({cmp.pass_rate_delta:+.1f})")
        if cmp.newly_failing:
            typer.echo(f"  newly failing: {', '.join(cmp.newly_failing)}")
        if cmp.newly_passing:
            typer.echo(f"  newly passing: {', '.join(cmp.newly_passing)}")

    if cmp.failed:
        typer.echo("✗ FAIL", err=True)
        for r in cmp.reasons:
            typer.echo(f"  - {r}", err=True)
        raise typer.Exit(1)
    typer.echo("✓ PASS")


if __name__ == "__main__":
    app()
