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


if __name__ == "__main__":
    app()
