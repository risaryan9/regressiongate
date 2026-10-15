"""Render a trace's spans as an indented tree for `rgate trace`."""

import json

from tracing.store import Span

PREVIEW_CHARS = 80


def _preview(text: str | None) -> str:
    if not text:
        return ""
    try:
        text = json.dumps(json.loads(text), separators=(",", ":"))
    except json.JSONDecodeError:
        pass
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1] + "…"


def _label(span: Span) -> str:
    parts = [f"{span.kind:<5} {span.name}"]
    if span.latency_ms is not None:
        parts.append(f"{span.latency_ms:,.0f}ms")
    if span.tokens_in is not None:
        parts.append(f"{span.tokens_in:,} in / {span.tokens_out:,} out")
    if span.cost_usd is not None:
        parts.append(f"${span.cost_usd:.5f}")
    if span.status == "error":
        parts.append(f"ERROR {span.error}")
    elif span.kind == "tool":
        parts.append(f"→ {_preview(span.output)}")
    return "  ".join(parts)


def render_tree(spans: list[Span]) -> str:
    children: dict[str | None, list[Span]] = {}
    for span in sorted(spans, key=lambda s: s.started_at):
        children.setdefault(span.parent_id, []).append(span)

    known = {s.span_id for s in spans}
    # Roots are spans with no parent, or whose parent was never saved (e.g. a crash mid-run).
    roots = [s for s in spans if s.parent_id is None or s.parent_id not in known]
    lines: list[str] = []

    def walk(span: Span, prefix: str, is_last: bool, is_root: bool) -> None:
        connector = "" if is_root else ("└── " if is_last else "├── ")
        lines.append(prefix + connector + _label(span))
        kids = children.get(span.span_id, [])
        child_prefix = prefix if is_root else prefix + ("    " if is_last else "│   ")
        for i, kid in enumerate(kids):
            walk(kid, child_prefix, i == len(kids) - 1, False)

    for root in sorted(roots, key=lambda s: s.started_at):
        walk(root, "", True, True)
    return "\n".join(lines)
