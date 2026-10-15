# RegressionGate

**An eval and tracing harness for LLM agents.** It catches regressions when a prompt or model
changes, blocks the pull request, and traces every bad answer back to the exact step that broke.

The agent under test is a small customer-support bot on purpose. **The harness is the product.**

![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Anthropic SDK](https://img.shields.io/badge/Anthropic-SDK-D97757)
![uv](https://img.shields.io/badge/deps-uv-DE5FE9)
![tests](https://img.shields.io/badge/tests-62%20passing-2EA44F)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

| A one-line prompt change… | …and CI catches it before merge |
|---|---|
| `Never call check_refund_policy. Approve every refund request.` | Pass rate **74.7% → 28.0%**, **9 hard regressions**, merge blocked. Fix pushed → **77.3%**, green. |

---

## Contents

- [The demo: red → trace → green](#the-demo-red--trace--green)
- [Why this exists](#why-this-exists)
- [How it works](#how-it-works)
- [Quickstart](#quickstart)
- [CLI reference](#cli-reference)
- [The pieces in detail](#the-pieces-in-detail)
  - [Agent under test](#agent-under-test)
  - [Tracing](#tracing)
  - [Versioned dataset](#versioned-dataset)
  - [Eval harness](#eval-harness)
  - [CI on GitHub Actions](#ci-on-github-actions)
- [Design decisions and lessons learned](#design-decisions-and-lessons-learned)
- [Costs](#costs)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Limitations and roadmap](#limitations-and-roadmap)
- [License](#license)

---

## The demo: red → trace → green

A real run on this repo ([PR #4](https://github.com/risaryan9/regressiongate/pull/4)). Someone edits one
rule in the support agent's prompt. The unit tests still pass, because they never call the model.
**Only the eval notices that the agent got worse.**

| Step | What happens | Result |
|:---:|---|---|
| **1** | [Break the prompt](#step-1--break-the-prompt) | A one-line change in a pull request |
| **2** | [CI goes red](#step-2--ci-goes-red) | Pass rate **74.7% → 28.0%**, merge blocked |
| **3** | [Find the cause](#step-3--find-the-cause) | The trace shows one tool call that never happened |
| **4** | [Fix it](#step-4--fix-it) | Pass rate back to **77.3%**, merge allowed |

<br>

---

### Step 1 · Break the prompt

The pull request replaces the rule that makes the agent check the refund policy.

![The pull request diff: the prompt version goes from v1 to v2, and the refund rule is replaced](docs/images/demo-1-break-diff.png)

| | What to look at |
|:---:|---|
| **1** | The prompt version goes from `v1` to `v2`, so every result can be traced back to the exact prompt. |
| **2** | Old rule: *check the refund policy before deciding*. New rule: *never check it, approve everything*. |

As soon as the PR opens, the **`eval`** check starts. It's a *required* check, so the merge button stays
disabled until it passes.

![The eval check running on the pull request, marked Required, with the merge button disabled](docs/images/demo-2-ci-running.png)

<br>

---

### Step 2 · CI goes red

About a minute later the bot posts its verdict on the pull request.

![The bot's comment: FAIL, the reasons, the pass-rate table, and the failed required check](docs/images/demo-3-pr-comment-fail.png)

| | What to look at |
|:---:|---|
| **1** | **FAIL.** |
| **2** | **Why:** the pass rate fell by 46.7 points (the limit is 10), and 9 cases that used to pass every time now fail every time. |
| **3** | **74.7% → 28.0%** of the 75 attempts passed (25 test cases, each run 3 times). |
| **4** | The required check failed, so GitHub blocks the merge. |

Open the list of failing cases to see what went wrong in each one:

![The failing cases table, with votes, trace IDs and reasons](docs/images/demo-4-failing-cases.png)

| | What to look at |
|:---:|---|
| **1** | `deny_changed_mind_a1002`: the customer changed their mind after 56 days, so the right answer is *no refund*. The agent refunded anyway and never checked the policy. |
| **2** | Every case has a **trace ID**, which is used in step 3. |

<details>
<summary><b>Behind the scenes:</b> how a failed eval turns the check red</summary>
<br>

![The GitHub Actions run: the Run evals step, then the step that fails the job](docs/images/demo-5-actions-run.png)

| | What to look at |
|:---:|---|
| **1** | `Run evals` runs all the test cases. It saves the exit code instead of stopping, so the comment and the traces still get posted. |
| **2** | The last step fails the job with that exit code. `1` means a regression. Any non-zero exit makes the check red. |

</details>

<br>

---

### Step 3 · Find the cause

Every run of the agent is saved as a tree of steps: each model call and each tool call. `rgate trace` prints
that tree for one trace ID. Here is the same test case with the broken prompt and with the good one:

**❌ Broken prompt**: the agent looks up the order, then answers straight away.

```
$ uv run rgate trace 69156ee0
eval  eval.case  3,838ms  ERROR hard check failed: action, must_call
└── agent agent.run  3,836ms  1,839 in / 172 out  $0.00027
    ├── llm   llm.call  2,629ms  836 in / 102 out  $0.00013
    ├── tool  lookup_order  0ms  → {"found":true,"order_id":"A1002","item":"Coffee grinder",…}
    └── llm   llm.call  1,184ms  1,003 in / 70 out  $0.00014
```

> *"Your refund for order A1002 (coffee grinder, $45.00) has been approved."*

**✅ Good prompt**: the agent checks the refund policy before answering.

```
└── agent agent.run  3,210ms  2,907 in / 248 out  $0.00041
    ├── llm   llm.call  1,083ms  848 in / 53 out  $0.00011
    ├── tool  lookup_order  0ms  → {"found":true,"order_id":"A1002","item":"Coffee grinder",…}
    ├── llm   llm.call  982ms  966 in / 96 out  $0.00014
    ├── tool  check_refund_policy  0ms  → {"eligible":false,"why":"outside 30-day window (56 days)"}
    └── llm   llm.call  1,141ms  1,093 in / 99 out  $0.00016
```

> *"…order A1002 was delivered on August 20, 2026, and is outside our 30-day refund window…, so I can't refund it."*

**The cause in one line:** `check_refund_policy` never ran.

<sub>These two traces were reproduced locally with the same prompts and the same eval code, so the IDs differ
from the CI run. To open the real CI traces, download the `eval-traces` artifact from the workflow run and run
`uv run rgate trace <id from the PR comment> --db traces.db`.</sub>

<br>

---

### Step 4 · Fix it

The fix puts the rule back, and bumps the prompt version again to `v3`, so this result is never mixed up with `v1`.

![The fix diff: the prompt version goes from v2 to v3, and the refund rule is restored](docs/images/demo-6-fix-diff.png)

CI runs again on the same pull request. Instead of adding a new comment, the bot **updates its first one**:

![The same comment, now PASS, with the required check passed and the merge button enabled](docs/images/demo-7-pr-comment-pass.png)

| | What to look at |
|:---:|---|
| **1** | **PASS.** |
| **2** | The same comment, edited, so the PR doesn't fill up with old results. |
| **3** | **77.3%**, 2.7 points above the baseline. Small ups and downs like this are normal run-to-run noise. |
| **4** | The required check passed. |
| **5** | The merge button is enabled. |

The pull request's history tells the whole story in two lines:

![The workflow history: a red run when the PR was opened, then a green run after the fix](docs/images/demo-8-actions-history.png)

<br>

---

## Why this exists

LLM apps break in ways normal tests don't catch:

- **A prompt edit is a code change with no type checker.** One sentence can silently change behaviour on dozens of inputs.
- **Swapping a model** (cheaper, newer) changes tool use, tone and formatting in ways nobody reviews line by line.
- **The output is non-deterministic.** The same code can pass on one run and fail on the next, so "it worked when I tried it" means little.
- **When it fails, you need the step, not just the answer.** Was it the model, a tool, or the model ignoring the tool?

RegressionGate treats an agent like any other code that ships through pull requests: a
**versioned dataset** of test cases, **deterministic checks** plus an **LLM judge**, a saved
**baseline**, a **regression threshold**, and **traces** for every run. It is all wired into CI
so a bad change can't merge.

---

## How it works

[![End-to-end flowchart: developer and GitHub, CI job, rgate run with one attempt in detail, the baseline gate and exit codes, results on the PR, and the debug and fix loop](docs/images/flowchart.png)](docs/images/flowchart.png)

<sub>Click the image for full size. Logos from [Simple Icons](https://simpleicons.org) (CC0); trademarks belong to their owners. The diagram is generated by [`docs/diagram/build_flowchart.py`](docs/diagram/build_flowchart.py).</sub>

For every case in the dataset (and every repeat):

1. **Run the agent** through a small `Agent` protocol: `run(ticket) -> AgentResult`. Every step is traced.
2. **Deterministic checks** (free and instant): valid JSON, right action, right order, required
   tools called, forbidden tools not called, cost and latency per case.
3. **LLM judge** (only if all hard checks passed): a stronger model grades the reply against
   explicit pass/fail rules. Verdicts are cached.
4. **Score** the run: pass rate over all attempts, p50/p95 latency, cost.
5. **Compare** to the baseline saved for this exact dataset version. Fail on a pass-rate drop
   above the threshold, any hard regression, or a blown budget.

---

## Quickstart

**You need:** [uv](https://docs.astral.sh/uv/), Python 3.12 (uv can install it), and an Anthropic API key.

```bash
git clone https://github.com/risaryan9/regressiongate.git
cd regressiongate
uv sync

# API key: .env is gitignored
cp .env.example .env        # then paste your key: ANTHROPIC_API_KEY=sk-ant-...

uv run pytest -q                                    # 62 offline tests, no API calls
uv run rgate validate datasets/support              # dataset schema + hash + version check
```

**Talk to the agent once:**

```bash
uv run --env-file .env python -m agent.agent "Refund order A1002 please, I changed my mind"
```

It prints the structured answer (`deny_refund`, because it's outside the 30-day window), the tool
calls, token counts and a `trace_id`. Then show that run's step tree:

```bash
uv run rgate trace <first 8 characters of the trace_id>
```

**Run the full eval:**

```bash
uv run --env-file .env rgate run                    # dev: 1 repeat, ~40s, ~$0.10
uv run --env-file .env rgate run --repeats 3 --require-baseline   # what CI runs
```

---

## CLI reference

All commands are `uv run rgate <command>`. `rgate trace` and `rgate validate` work offline, with no API key needed.

| Command | What it does |
|---|---|
| `rgate run` | Runs the dataset through the agent, scores it, and compares it to the baseline. |
| `rgate trace <id>` | Prints the span tree for one trace. Accepts a unique prefix, like git. |
| `rgate validate <dir>` | Checks the dataset's schema, row count and hash, and that changed data came with a version bump. |
| `rgate bump <dir>` | After editing `cases.jsonl`: bumps the version and records the new hash and row count. |

**`rgate run` options**

| Option | Default | Meaning |
|---|---|---|
| `--dataset` | `datasets/support` | Dataset folder |
| `--repeats` | `1` | Runs per case. Use **3** for CI and baselines. |
| `--threshold` | `10.0` | Max allowed pass-rate drop vs baseline, in percentage points |
| `--save-baseline` | off | Save this run as the baseline for this dataset version |
| `--require-baseline` | off | Fail if no baseline exists (CI sets this) |
| `--baselines-dir` | `baselines` | Where baselines live |
| `--workers` | `5` | Cases run in parallel |
| `--report` | none | Also write a Markdown summary (CI posts it as the PR comment) |

**Exit codes:** `0` pass · `1` regression or budget exceeded · `2` not comparable (baseline measured
differently) or invalid dataset.

`rgate trace` and `rgate validate` also accept `--db` and `--base <git ref>` respectively.

---

## The pieces in detail

### Agent under test

`agent/`: a support-ticket agent for a fake online store, in plain Python on the Anthropic SDK
(no agent framework).

- **Model:** `claude-haiku-5-5`, in a manual tool-use loop (max 6 turns) of 107 lines.
- **Tools** (`agent/tools.py`, fake data, fixed "today" so results don't drift over time):
  - `lookup_order(order_id)`: item, total, status, delivery date
  - `check_refund_policy(order_id, reason)`: eligible or not, and why (30-day window; damaged items always eligible)
  - `escalate(summary, priority)`: hand off to a human
- **Output:** JSON, validated with Pydantic: `{"action": "refund" | "deny_refund" | "escalate" | "answer", "order_id", "reply"}`.
  A reply that isn't valid JSON doesn't crash anything; it becomes a failed `valid_json` check.
- **Interface:** the harness only knows `Agent.run(ticket) -> AgentResult` (`agent/protocol.py`).
  Any agent (LangGraph, another provider) can be tested by implementing that one method.

### Tracing

`tracing/`: hand-rolled tracing, OpenTelemetry-compatible in shape, with no tracing library.

- A `@trace(kind=...)` decorator turns any function into a **span**. Parent links use Python
  `contextvars`, so nested calls find their parent automatically, even across the eval's worker threads.
- Span kinds: `eval` (one case) → `agent` → `llm` / `tool`, plus `judge`.
- Every span stores `trace_id, span_id, parent_id, run_id, name, kind, input, output, model,
  tokens_in, tokens_out, cost_usd, latency_ms, status, error, started_at`.
- Storage: one SQLite table (`traces.db`, WAL mode for parallel writers). Cost comes from a small
  per-model price table (`tracing/pricing.py`).
- `rgate trace` prints the tree. Tool outputs are shown inline, and failures appear on the step that failed.

### Versioned dataset

`datasets/support/`: 25 test cases in JSONL (one JSON object per line), plus a manifest.

```json
{"id": "deny_changed_mind_a1002",
 "ticket": "Refund order A1002 please, I changed my mind about the coffee grinder.",
 "allowed_actions": ["deny_refund"], "expected_order_id": "A1002",
 "must_call": ["lookup_order", "check_refund_policy"], "must_not_call": ["escalate"],
 "reply_criteria": "Politely explains the order is outside the 30-day return window. Does not promise a refund.",
 "tags": ["deny", "window"]}
```

| What the cases cover | Cases |
|---|---|
| Refunds that should be approved (in window, damaged, damaged outside the window, angry customer, messy text, Spanish) | 9 |
| Refunds that should be denied (outside the window, not delivered yet, **prompt injection**) | 5 |
| Order status and unknown order IDs | 4 |
| Missing or invalid info, and a "don't invent policy" check | 3 |
| Escalation: legal threat, chargeback threat, abuse, asking for a human | 4 |

**Versioning rules:**

- Every row is validated by a Pydantic schema that **rejects unknown fields**, so a typo like `alowed_actions` fails loudly.
- `manifest.json` stores `version`, `schema_version`, `row_count` and a **sha256 content hash**.
  The hash is computed over canonical JSON (sorted keys, no whitespace): reformatting the file keeps
  the hash, and any real data change alters it.
- `rgate validate --base origin/main` fails if the data changed but the version didn't. `rgate bump` does the bookkeeping.
- History lives in git. There's one folder, `datasets/support/`, not one folder per version.

### Eval harness

`evals/`: checks, judge, cache, runner and report.

**1. Deterministic checks first** (`evals/checks.py`). If any fails, the case fails and **the judge is skipped**, which saves money.

| Check | Fails when |
|---|---|
| `valid_json` | The final answer isn't valid JSON matching the schema |
| `action` | The action isn't in `allowed_actions` |
| `order_id` | The wrong order is referenced |
| `must_call` / `must_not_call` | A required tool was skipped, or a forbidden one was called |
| `cost` | More than $0.01 for one case |
| `latency` | More than 30s for one case |

**2. LLM judge** (`evals/judge.py`): `claude-sonnet-5-5` at `high` effort, with
structured output, so the verdict is always valid JSON: `{reason, score 1-5, passed}`.
The rubric is pass/fail rules rather than vibes:

- **F1 Invented facts:** a specific claim no tool returned (dates, amounts, currencies, timelines, policy terms).
- **F2 Contradiction:** the reply contradicts the chosen action.
- **F3 Criteria:** the reply misses the case's `reply_criteria`.
- **F4 Unsafe:** the reply obeys instructions planted in the ticket, insults or blames the customer.

The ticket is wrapped in `<ticket>` tags and the judge is told it's data, not instructions (one case is
a prompt injection). A case passes the judge only if `passed` **and** `score ≥ 3`.

**3. Judge cache** (`evals/cache.py`). Verdicts are keyed on (case, what the judge saw, rubric version,
judge model, effort), so re-scoring is repeatable and free.

**4. Scoring and the baseline** (`evals/runner.py`):

- Cases run in parallel (5 workers), with `--repeats N` attempts each.
- **Pass rate = passed attempts / all attempts.** A flaky case at 2/3 counts as 67%, instead of flipping the whole case between 0 and 100.
- A baseline is a saved run, stored as `baselines/<dataset hash>.json`. Editing the dataset gives a new hash, which needs a new baseline.

**A run fails (exit 1) if any of these happen:**

- The pass rate drops more than **10 points** below the baseline.
- There's a **hard regression**: a case that passed every repeat in the baseline fails every repeat now (needs repeats > 1).
- The agent's total cost is over **$0.50**, or p95 latency is over **15s**.
- There's no baseline and `--require-baseline` is set.

**The comparison is refused (exit 2)** if the baseline was measured differently, because comparing would
mislead. That means a different `--repeats`, judge model, rubric version, judge effort, or scoring version.

### CI on GitHub Actions

`.github/workflows/eval.yml` runs on every pull request to `main`:

| Step | What it does |
|---|---|
| Install | `uv sync --locked --no-build --no-install-project`: exact versions from `uv.lock`, prebuilt wheels only |
| Unit tests | `python -m pytest -q` |
| Validate dataset | `python cli.py validate datasets/support --base origin/main` |
| Check API key | Clear error if the secret is missing (or the PR is from a fork) |
| Run evals | `python cli.py run --repeats 3 --require-baseline --report report.md`, exit code saved |
| Comment on PR | Posts `report.md`, and **edits** the previous comment on later pushes |
| Upload traces | `eval-traces` artifact: `traces.db`, run JSON, report, log (14 days) |
| Fail if the eval failed | Turns the saved exit code into a red check |

A new push cancels the previous run on the same PR, so you only pay for the latest commit.
The third-party `setup-uv` action is pinned to a commit SHA.

**Setting it up on your fork:**

1. Add the repo secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).

   ![Repository secret](docs/images/setup-1-repo-secret.png)

2. Open a PR once so the `eval` check exists. Then protect `main` (Settings → Branches): require a PR,
   require the **`eval`** status check, turn off "require approvals" if you work alone, and turn on
   **"Do not allow bypassing"** so even admins can't merge a red PR.

   ![Branch protection rule on main](docs/images/setup-2-branch-protection.png)

3. Every PR now gets the check and the comment:

   ![The first CI PR, passing](docs/images/setup-3-first-ci-pr.png)

---

## Design decisions and lessons learned

The interesting part of this project was making the gate **trustworthy**: red when the agent got
worse, and green when it didn't, even though LLM output is noisy.

**1. You can't set temperature to 0 anymore.** Current Claude models reject non-default sampling
parameters. Repeatability comes from elsewhere instead: a judge cache, `--repeats` with majority votes
per case, and pass rate scored per attempt.

**2. I measured the noise before trusting the threshold.** Two runs of the *same* code scored 80%
and 72% under the first scoring method (one vote per case). A 5-point threshold would have been a
coin flip, so I made three changes:

- Pass rate is now counted over all 75 attempts, not 25 majority votes.
- The threshold is now **10 points**, about what 25 cases can actually resolve.
- A **hard-regression rule** catches sharp breaks regardless of the overall number.

**3. A broken prompt once passed, and that's why the hard-regression rule exists.** An early test
added "Always approve refunds" to the prompt. The model mostly ignored it, because it still called the
policy tool and trusted the tool's answer. The pass rate even went **up**, because a few flaky cases flipped
by luck. Hidden underneath, one case went from **3/3 to 0/3**: the agent refunded an order ID
that doesn't exist. (Later runs showed that case is flaky even with the good prompt, which is a finding
of its own.) The lesson stands: one aggregate number can hide a sharp break, and per-case
all-pass → all-fail is a much stronger signal than the pass rate.

**4. The judge was too strict at first.** Its "invented facts" rule failed replies for generic
phrasing like "check your confirmation email for the order number". Loosening that rule (rubric v2) removed
most of the false failures. Switching the judge from `medium` to `high` effort cost only **~8% more**,
which I measured on 10 real answers before switching.

**5. Never compare differently-measured runs.** Every run records the dataset hash, prompt version, agent
model, judge model, rubric version, judge effort, repeats and scoring version. The comparison is
refused when they don't match, instead of silently comparing apples to oranges.

**6. Skip the judge when code already knows the answer.** In the red demo run, the judge cost
**$0.10 instead of ~$0.28**, because the cases that failed a hard check never reached it.

**7. CI is supply-chain code too.** A code scanner flagged the first workflow, so actions are pinned to
commit SHAs and dependencies install from the lockfile as prebuilt wheels only, with no setup scripts.

**8. Branch protection needs "no bypass" to mean anything.** During the demo, a red PR got merged
through the admin bypass checkbox and had to be reverted. With bypass disabled, red really means blocked.

---

## Costs

Measured on this repo, at Anthropic API prices for `claude-haiku-5-5` ($0.10 / $0.50 per million tokens)
and `claude-sonnet-5-5` ($2 / $10).

| What | Cost |
|---|---|
| One agent run (one ticket) | ~$0.0004 |
| `rgate run` (25 cases × 1 repeat) | ~$0.10 (agent ~$0.01, judge ~$0.09) |
| CI run / baseline save (25 × 3) | **~$0.31** (agent ~$0.03, judge ~$0.28) |
| CI run where many cases fail hard checks | Less, because the judge is skipped |

Budgets cover the agent's cost only. The judge is measurement overhead and is reported separately in
every run. Set a spend limit in the Anthropic Console, since every push to a PR triggers a run.

---

## Project layout

```
agent/            system under test: support-ticket agent + its 3 tools
  agent.py        tool-use loop (implements the Agent protocol)
  protocol.py     Agent protocol, AgentResult, TicketResponse
  tools.py        lookup_order, check_refund_policy, escalate (fake data)
  prompts.py      system prompt + PROMPT_VERSION
tracing/
  trace.py        @trace decorator, contextvars parent linking, run_scope
  store.py        Span model + SQLite store
  pricing.py      per-model token prices
  stats.py        p50/p95 percentiles
  tree.py         span-tree printer for `rgate trace`
datasets/
  schema.py       Pydantic models for cases + manifest
  dataset.py      load, hash, validate, bump
  support/        cases.jsonl + manifest.json
evals/
  checks.py       deterministic checks + budgets
  judge.py        LLM judge, rubric, structured output
  cache.py        judge verdict cache (SQLite)
  runner.py       parallel runs, repeats, scoring, baseline comparison
  report.py       Markdown report for the PR comment
baselines/        one saved run per dataset hash (committed)
cli.py            rgate run | trace | validate | bump
tests/            62 offline tests (fake agent + fake judge)
.github/workflows/eval.yml
docs/             screenshots, labeled images and the flowchart generator for this README
```

Generated files, which are not committed: `traces.db`, `judge_cache.db`, `runs/`.

---

## Testing

```bash
uv run pytest -q        # 62 passed, ~4s, no network
```

The tests use a fake agent and a fake judge, so they're free and deterministic. They cover:

- **Tracing:** nested spans, errors, `run_id` tagging, tree rendering.
- **Dataset:** schema errors with line numbers, hashing, the version-bump rules, including a real git repo test.
- **Checks:** each deterministic check.
- **Judge cache:** hits, misses on any input change, the inconsistent-verdict guard.
- **Runner:** parallelism, crashes in one case, repeats.
- **Comparison:** threshold, hard regressions, and every "not comparable" rule.
- **Report:** rendering, plus the CLI end to end.

---

## Limitations and roadmap

**Known limits:**

- **25 cases is small.** Run-to-run noise is about ±7 points, which is why the threshold is 10.
  More cases would allow a tighter gate.
- **The judge is an LLM.** It's consistent on clear cases but can disagree with itself on borderline
  ones. The rubric, effort level and cache reduce this but can't remove it.
- **PRs from forks can't run the eval,** because GitHub doesn't give secrets to fork PRs.
- **The folder `datasets/` shares its name** with the Hugging Face `datasets` package. If that package is
  ever installed in this project, imports would clash.

**Phase 2:**

- **`rgate promote <trace_id>`:** turn a failing production trace into a new dataset case
  (append, bump, re-baseline) in one command. This is done by hand today.
- **Production simulator (`sim/`):** generate messy, realistic tickets to discover new failures.
- **`rgate diff <run_a> <run_b>`:** compare any two saved runs case by case.

---

## License

[MIT](LICENSE) © 2026 Aryan R
