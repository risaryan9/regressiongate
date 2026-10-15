import pytest

from tracing.store import TraceStore
from tracing.trace import set_store


@pytest.fixture(autouse=True)
def tmp_trace_store(tmp_path):
    """Every test traces into its own temp DB, never the real traces.db."""
    store = TraceStore(str(tmp_path / "traces.db"))
    set_store(store)
    return store
