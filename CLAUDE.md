# RegressionGate

An eval and tracing harness for LLM agents. It catches regressions when a prompt or model changes, and traces every bad output back to the exact step that broke.

The agent is small on purpose. **The harness is the product.**

## Goal of this repo

By the end, the repo must show this story with real public PRs:

1. PR #1 changes a prompt and swaps a model. CI goes red.
2. `rgate trace <id>` shows the exact span that broke.
3. The failure becomes a test case in the dataset.
4. PR #2 fixes it. CI goes green. Merged.

## Stack (do not change without asking)

- Python 3.12, **uv** for deps and running (`uv add`, `uv run`). Never use pip directly.
- **Anthropic Python SDK**, called directly. No LangChain, no LangGraph, no agent frameworks.
- Agent model: `claude-haiku-5-5`. Judge model: `claude-sonnet-5-5`.
- **Pydantic v2** for all schemas.
- **SQLite** (stdlib `sqlite3`) for traces. No ORM.
- **Typer** for the CLI. **pytest** for tests.
- **GitHub Actions** for CI.

## Hard rules

- **Tracing is hand-rolled.** Do not add Langfuse, LangSmith, OpenTelemetry SDK, or any tracing library. The span format should be OpenTelemetry-compatible in shape only.
- **No new dependencies** without asking me first.
- **Never hard-code API keys.** Read `ANTHROPIC_API_KEY` from the environment.
- **Never edit a dataset file** (`datasets/*/cases.jsonl`) without also bumping `schema_version` or the dataset version in its `manifest.json`.
- **Never edit files in `baselines/`** unless I explicitly ask to update a baseline.
- Keep the agent under ~150 lines. If it grows, stop and ask.

## Repo layout

```
agent/            # system under test: support-ticket agent + its 3 tools
  agent.py        # tool-use loop, implements the Agent protocol
  tools.py        # lookup_order, check_refund_policy, escalate (fake data)
  prompts.py      # system prompt (versioned with a PROMPT_VERSION constant)
tracing/
  trace.py        # @trace decorator, contextvars for parent spans
  store.py        # SQLite read/write
  pricing.py      # token -> USD cost per model
  tree.py         # span-tree printer for `rgate trace`
  stats.py        # percentiles (p50/p95 latency)
datasets/
  schema.py       # Pydantic models for cases + manifest
  support/        # cases.jsonl + manifest.json (version lives in the manifest; git keeps old versions)
evals/
  checks.py       # deterministic checks
  judge.py        # LLM-as-judge (rubric, structured output, score + reason)
  runner.py       # run dataset, score, compare to baseline
  cache.py        # judge cache keyed on hash(case, output, rubric_version)
baselines/        # one JSON result file per dataset hash
sim/              # prod simulator: messy inputs for failure discovery
cli.py            # rgate run | trace | promote | validate | diff
.github/workflows/eval.yml
```

## Key interfaces

```python
class Agent(Protocol):
    def run(self, ticket: str) -> AgentResult: ...
```

The eval runner must only depend on this protocol, never on agent internals. This keeps the harness framework-agnostic (a LangGraph adapter may be added later).

Every span stores: `trace_id, span_id, parent_id, run_id, name, kind (eval|agent|llm|tool|judge), input, output, model, tokens_in, tokens_out, cost_usd, latency_ms, status, error, started_at`.

## Eval rules

- Deterministic checks run first. If any fails, **skip the judge** for that case.
- Judge returns `{reason: str, score: 1-5, passed: bool}` via structured output. A case passes the judge only if `passed` and `score >= 3`.
- Sampling params (temperature) are rejected by current models; repeatability comes from the judge cache and `--repeats` majority voting.
- Every eval result records: dataset hash, prompt version, agent model, judge model, rubric version, repeats.
- Baselines are keyed on the dataset hash: editing cases (and bumping) means the old baseline no longer applies.
  - CI runs with `--require-baseline`, so a missing baseline fails instead of skipping the regression check.
  - A PR that changes the dataset must save the new baseline (`--save-baseline --repeats 3`) in the same PR.
  - Never change the dataset and the prompt/model in the same PR: the new baseline would be measured with the new prompt and hide the regression.
- Baseline and new run must use the same `--repeats` (default 1 for dev, 3 for CI and baselines), or the comparison is refused.
- A run **fails (exit code 1)** if pass rate drops more than the threshold vs baseline (default 5 percentage points), or if cost or p95 latency exceed budget.

## Who writes what

Claude writes the code, including the parts originally reserved for me (trace decorator, judge rubric, baseline comparison). I review them afterwards.


## How to work with me

- I'll give you one block at a time. Plan first, then code. Don't jump ahead to later blocks.
- Keep diffs small. One block = one commit.
- When you write something non-obvious, add a one-line comment saying **why**, not what.
- Explain in simple English with proper technical terms.
- After each block, tell me the exact command to verify it works.

## Commands

```bash
uv sync                               # install
uv run pytest                         # unit tests
uv run rgate validate datasets/support
uv run rgate bump datasets/support      # after editing cases.jsonl
uv run rgate run --dataset datasets/support
uv run rgate trace <trace_id>
uv run rgate promote <trace_id> --to datasets/support   # appends the case, then bump
uv run rgate diff <run_a> <run_b>
```