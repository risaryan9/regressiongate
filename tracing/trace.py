"""The @trace decorator. Records each decorated call as a span and links it to its parent.

Parent links use contextvars: while a span runs, it is the "current span", so any traced
call made inside it picks it up as its parent without IDs being passed around by hand.
"""

import functools
import inspect
import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from tracing.pricing import cost_usd
from tracing.store import Span, SpanKind, TraceStore

_current_span: ContextVar[Span | None] = ContextVar("current_span", default=None)
_current_run: ContextVar[str | None] = ContextVar("current_run", default=None)
_store: TraceStore | None = None


def set_store(store: TraceStore) -> None:
    """Point tracing at a different database (tests use a temp file)."""
    global _store
    _store = store


def _get_store() -> TraceStore:
    global _store
    if _store is None:
        _store = TraceStore()  # created lazily so importing this module never touches disk
    return _store


def _to_json(value) -> str:
    def default(o):
        # Pydantic models and Anthropic SDK objects both expose model_dump.
        if hasattr(o, "model_dump"):
            return o.model_dump(mode="json")
        return str(o)

    return json.dumps(value, default=default)


def trace(kind: SpanKind, name: str | None = None):
    """Decorator: record each call of the function as a span of the given kind."""

    def decorator(func):
        span_name = name or func.__name__
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            parent = _current_span.get()
            bound = sig.bind_partial(*args, **kwargs)
            inputs = {k: v for k, v in bound.arguments.items() if k != "self"}
            span = Span(
                trace_id=parent.trace_id if parent else uuid.uuid4().hex,
                span_id=uuid.uuid4().hex,
                parent_id=parent.span_id if parent else None,
                run_id=_current_run.get(),
                name=span_name,
                kind=kind,
                input=_to_json(inputs),
                started_at=datetime.now(UTC).isoformat(),
            )
            token = _current_span.set(span)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                span.output = _to_json(result)
                return result
            except Exception as e:
                span.status = "error"
                span.error = f"{type(e).__name__}: {e}"
                raise
            finally:
                span.latency_ms = (time.perf_counter() - start) * 1000
                _current_span.reset(token)
                _get_store().save(span)

        return wrapper

    return decorator


def set_tokens(model: str, tokens_in: int, tokens_out: int) -> None:
    """Attach model, token counts and cost to the current span. No-op outside a span."""
    span = _current_span.get()
    if span is None:
        return
    span.model = model
    span.tokens_in = tokens_in
    span.tokens_out = tokens_out
    span.cost_usd = cost_usd(model, tokens_in, tokens_out)


def mark_error(message: str) -> None:
    """Flag the current span as failed without raising (e.g. the model returned bad JSON)."""
    span = _current_span.get()
    if span is not None:
        span.status = "error"
        span.error = message


def current_trace_id() -> str | None:
    span = _current_span.get()
    return span.trace_id if span else None


@contextmanager
def run_scope(run_id: str):
    """Tag every span created inside this block with run_id (used by eval runs)."""
    token = _current_run.set(run_id)
    try:
        yield
    finally:
        _current_run.reset(token)
