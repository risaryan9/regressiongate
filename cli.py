"""rgate: command-line entry point for the RegressionGate harness."""

import typer

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


if __name__ == "__main__":
    app()
