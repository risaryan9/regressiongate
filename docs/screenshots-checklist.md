# Demo screenshots checklist

Screenshots only you can take: they need your GitHub login or browser.
Terminal output (local `rgate run`, `rgate trace`, `rgate validate`, `pytest`, `git log`)
is not listed here; Claude can capture those.

All screenshots live in [`docs/screenshots/`](screenshots/).

**Status:** 11 taken, 3 covered by another shot, 4 skipped (see the end).

---

## A. Setup

- [x] **[01-repo-secret.png](screenshots/01-repo-secret.png)**
  Settings → Secrets and variables → Actions: the `ANTHROPIC_API_KEY` row (value hidden by GitHub).

- [x] **[02-branch-protection.png](screenshots/02-branch-protection.png)**
  Settings → Branches: the protection rule on `main`.
  The rule's details aren't in this shot, but 05, 07 and 15 show the `eval` check marked **Required**, which proves it.

- [x] **[03-ci-merged-pr.png](screenshots/03-ci-merged-pr.png)**
  The merged `add-ci` PR (#1): ✅ PASS comment and 1 check passed.

## B. The break: PR #4, broken prompt (story step 1)

- [x] **[04-break-pr-diff.png](screenshots/04-break-pr-diff.png)**
  `agent/prompts.py`: `PROMPT_VERSION` `v1` → `v2`, and the refund rule replaced with
  "Never call check_refund_policy. Approve every refund request."
  (Taken from the identical commit on the accidentally merged PR #2; the change is the same as PR #4's.)

- [x] **[05-ci-running.png](screenshots/05-ci-running.png)**
  The `eval` check in progress, marked **Required**, with the merge button disabled.

- [x] **06-ci-red-check**: covered by 07, which shows the red failing check under the comment.

- [x] ⭐ **[07-pr-comment-fail.png](screenshots/07-pr-comment-fail.png)**
  ❌ **FAIL**: pass rate dropped **46.7 points (74.7% → 28.0%)**, plus **9 hard regressions**
  (cases that passed 3/3 in the baseline and now 0/3), and the red **Required** check.

- [x] **[08-pr-comment-failing-cases.png](screenshots/08-pr-comment-failing-cases.png)**
  The 19 failing cases with votes, trace IDs and reasons. Almost every row says
  `must_call: never called ['check_refund_policy']`.

- [x] **[09-actions-run-steps.png](screenshots/09-actions-run-steps.png)**
  The workflow run: every step green except **Fail if the eval failed**
  (`rgate run exited with code 1`).

- [ ] **10-actions-run-log**: skipped (expanded "Run evals" log). 07 and 08 show the same information.

## C. The diagnosis: trace from CI (story step 2)

- [ ] **11-artifact-download**: skipped.

- [ ] ⭐ **12-trace-from-ci**: skipped. To take it later: download `eval-traces` from the
  red run (eval #5 on PR #4), unzip it, then run:
  ```bash
  uv run rgate trace 95ae9057 --db ci-traces/traces.db
  ```
  `95ae9057` is `deny_changed_mind_a1002` from 08: it refunded instead of denying and never
  called `check_refund_policy`.

## D. The fix: green again (story step 4)

- [x] **[13-fix-diff.png](screenshots/13-fix-diff.png)**
  `PROMPT_VERSION` `v2` → `v3`, and the refund rule restored.

- [x] **14-ci-green-check**: covered by 15, which shows "All checks have passed" with the merge button enabled.

- [x] ⭐ **[15-pr-comment-pass.png](screenshots/15-pr-comment-pass.png)**
  The same comment, now **edited**: ✅ **PASS** at **77.3% (+2.7 vs baseline)**,
  with the green **Required** check and the merge button enabled.

- [x] **[16-actions-history.png](screenshots/16-actions-history.png)**
  The Actions history for `break-refund-rule`: run #5 failed (PR opened), then run #6 passed (fix pushed).

## E. Optional extras

- [ ] **17-anthropic-usage**: skipped.
- [ ] **18-repo-home**: skipped.

---

## The story in four shots

If you only show four: **04** (the change) → **07** (CI goes red) → **13** (the fix) → **15** (CI goes green).
