# Rust OTLP Export Flake Investigation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging for the investigation itself, then superpowers:executing-plans (or subagent-driven-development) for the fix. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find the root cause of the intermittent Rust OTLP export-test failure, prove it with a deterministic reproducer, and fix it — or record the investigation as inconclusive and change nothing.

**Architecture:** This is an investigation, not a feature. It runs in its own branch or worktree so that no dependency, coverage, or contract change from the other plans can be mistaken for the fix. The acceptance rule is strict and non-negotiable: evidence first, statistical reproduction second, deterministic fault injection third, instrumentation showing the mechanism fourth, and only then a production change. A change that makes the test stop failing without a demonstrated mechanism is not a fix; it is a longer sleep wearing a disguise.

**Tech Stack:** Rust, tokio, `opentelemetry-otlp` HTTP exporter, the in-process fake collector in `rust/tests/otlp_runtime_test.rs`.

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2) — workstream E, and the "Rust flake acceptance rule" section.

## Global Constraints — read these before touching anything

- **No quarantine.** No `#[ignore]`, no `--skip`, no allowlist, no retry wrapper, no CI `continue-on-error`.
- **No longer sleeps.** Increasing a timeout or a poll budget to make a test pass is the failure mode this plan exists to prevent.
- **No speculative production change.** If the mechanism is not demonstrated, nothing in `rust/src/` changes. Inconclusive is an acceptable outcome; a guess is not.
- **Isolated branch.** Use `superpowers:using-git-worktrees` to get a worktree, or at minimum a dedicated branch. Do not interleave with plans 1–5.
- The regression test must **fail without the fix and pass with it**, demonstrated by temporarily reverting the fix.
- Both **parallel and serial** stress runs must pass afterwards.
- **777 LOC max per file**; **SPDX headers required**; Rust must keep 100% function coverage (`cargo llvm-cov … --fail-under-functions 100`) and pass `cargo mutants`.
- Commit messages must not mention AI assistance and must not carry a `Co-Authored-By: Claude` trailer.

## Candidate surfaces

The review did not name the test. These are the surfaces that could produce it:

| File | Notes |
|---|---|
| `rust/tests/otlp_runtime_test.rs` | **Most likely.** In-process fake collector, health-polled waits (`wait_for_export_health:222`, `assert_export_health_success:241`), three export tests from `:304`. Timing-sensitive by construction. |
| `rust/tests/otlp_collector_test.rs` | Single test `otlp_collector_smoke:63`; self-skips unless `PROVIDE_TEST_OTLP_ENDPOINT` is set, so it is unlikely to flake in a job that does not set it. |
| `rust/tests/shutdown_unreachable_endpoint_test.rs` | Deadline-bounded shutdown against a closed port (`:39`); a deadline test is a plausible flake source under load. |

Task 1 decides which one it actually is. Do not assume.

---

### Task 1: Preserve the original evidence

**Files:**
- Create: `docs/superpowers/plans/evidence/2026-08-20-rust-flake-original.txt`

**Interfaces:**
- Produces: the failing test's name, file, and the verbatim failure output that every later step is measured against.

- [ ] **Step 1: Find the original failure**

Look, in this order, for the actual recorded failure:

```bash
gh run list --workflow ci-rust.yml --limit 50
gh run view <id> --log-failed | tail -100
git log --oneline -20 -- rust/tests/
grep -rn "flake\|flaky\|intermittent" docs/ .provide/ CHANGELOG.md 2>/dev/null
```

- [ ] **Step 2: Write down what you found — verbatim**

Save the raw failure output, the run URL, the runner OS, the commit SHA, and the
exact `cargo test` invocation into the evidence file. Do not paraphrase, do not
tidy the output, and do not reconstruct it from memory.

- [ ] **Step 3: If no original evidence exists anywhere, say so**

Write that fact into the evidence file explicitly:

```
No original failure output was recorded in CI logs, git history, or repository
docs as of <date>. The investigation below starts from reproduction rather than
from a preserved failure.
```

This is not a blocker, but it changes what the rest of the plan can conclude, and
the checklist must not imply evidence that does not exist.

- [ ] **Step 4: Commit the evidence**

```bash
git add docs/superpowers/plans/evidence/2026-08-20-rust-flake-original.txt
git commit -m "docs: preserve the original Rust OTLP export failure evidence"
```

---

### Task 2: Reproduce it statistically

**Files:**
- Create: `docs/superpowers/plans/evidence/2026-08-20-rust-flake-reproduction.txt`

**Interfaces:**
- Produces: a failure rate — `N` runs, `K` failures — for a named test. Every later claim about "fixed" is measured against this number.

A flake with no measured rate cannot be shown fixed: one green run proves
nothing about a 1-in-50 failure.

- [ ] **Step 1: Establish a baseline rate, serially**

```bash
cd rust
fails=0
for i in $(seq 1 50); do
  if ! cargo test --test otlp_runtime_test -- --test-threads=1 >/tmp/run-$i.log 2>&1; then
    fails=$((fails + 1)); cp /tmp/run-$i.log "/tmp/fail-$i.log"
  fi
done
echo "serial: $fails / 50"
```

- [ ] **Step 2: Establish a rate under contention**

The failure is far likelier to appear when the machine is loaded, because that is
what perturbs task scheduling:

```bash
cd rust
fails=0
for i in $(seq 1 50); do
  if ! cargo test --test otlp_runtime_test >/tmp/par-$i.log 2>&1; then
    fails=$((fails + 1)); cp /tmp/par-$i.log "/tmp/parfail-$i.log"
  fi
done
echo "parallel: $fails / 50"
```

If both are 0/50, widen: run the whole suite (`cargo test --all-features`), raise
the iteration count, and run under artificial load (`stress-ng`, or a parallel
`cargo build` in another shell). Record every command and every count.

- [ ] **Step 3: Record the rate and the failing assertion**

Write into the reproduction evidence file: the test name, the serial rate, the
parallel rate, the loaded rate, and the *specific assertion* that fails — from
`wait_for_export_health`, `assert_export_health_success`, or elsewhere. A rate
plus an assertion is the minimum needed to proceed.

- [ ] **Step 4: If it does not reproduce at all**

Record every command, every count, and the environments tried (OS, core count,
load). Then go to Task 6 and close the investigation as inconclusive. Do **not**
change production code to fix something you cannot observe.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/evidence/2026-08-20-rust-flake-reproduction.txt
git commit -m "docs: measure the Rust OTLP export failure rate"
```

---

### Task 3: Instrument the lifecycle until the mechanism is visible

**Files:**
- Modify (temporarily): `rust/src/setup.rs`, `rust/src/otel/`, `rust/tests/otlp_runtime_test.rs`

**Interfaces:**
- Produces: a log or trace of one failing run showing *which* step did not complete and *why*.

Instrumentation here is temporary and must be reverted before the final commit,
except any piece that earns its place as permanent observability — and that
decision is explicit, not accidental.

- [ ] **Step 1: Add a lifecycle generation counter**

The repository has no generation concept in Rust today (`grep -rn "generation" rust/src/`
returns nothing). Add a process-global monotonic counter incremented by
`setup_telemetry` and read by `shutdown_telemetry` and by the export path, and log
it on every lifecycle transition. This is the single most useful instrument for
this class of bug: it makes "a drain worker from the *previous* test is still
running" visible, which is otherwise indistinguishable from "this test's export
was slow".

- [ ] **Step 2: Log the things the design requires the artifacts to identify**

For each run, capture:
- the stress command and iteration number,
- the lifecycle generation at setup, at each export, and at shutdown,
- the collector endpoint and the port actually bound,
- every outstanding drain worker at the moment of the failing assertion,
- the health snapshot the assertion read, in full.

- [ ] **Step 3: Run until you catch a failure with instrumentation on**

Reuse the loop from Task 2. Keep the log of the first failing run intact.

- [ ] **Step 4: State the root cause in one sentence, with the evidence line**

Write it into the reproduction evidence file in this form:

```
Root cause: <mechanism>, shown by <log line / file:line> in
/tmp/parfail-<i>.log at generation <n>.
```

If you cannot fill that template from observation — if the best you have is "it
seems like a race" — you do not have a root cause. Go to Task 6.

- [ ] **Step 5: Record rejected hypotheses too**

List what you ruled out and how. This is what stops the next person repeating the
work, and it is required by the acceptance rule.

---

### Task 4: Build a deterministic reproducer

**Files:**
- Create: `rust/tests/otlp_export_regression_test.rs`

**Interfaces:**
- Produces: a test that fails **every** time against the unfixed code, not 1-in-50.

- [ ] **Step 1: Turn the race into a controlled sequence**

Using the mechanism from Task 3, inject the fault deterministically rather than
waiting for the scheduler to produce it. Depending on what the mechanism turns
out to be, that means one of:
- a fault-injection hook that holds a drain worker open past the next setup,
- a collector stub that delays or drops the specific request the assertion waits on,
- an explicit ordering barrier that forces the interleaving the log showed.

Prefer a seam that already exists (`rust/src/testing.rs`, the existing collector
stub in `otlp_runtime_test.rs`) over adding a new public one. Do not widen the
public API to make the test possible — a `#[cfg(test)]` or `pub(crate)` seam is
the right shape.

- [ ] **Step 2: Prove it is deterministic**

```bash
cd rust
for i in $(seq 1 20); do cargo test --test otlp_export_regression_test || echo "FAIL $i"; done
```
Expected: 20 failures out of 20 against the unfixed code. Fewer than 20 means the
reproducer still depends on timing — tighten it before continuing.

- [ ] **Step 3: Commit the red reproducer**

```bash
git add rust/tests/otlp_export_regression_test.rs
git commit -m "test(rust): deterministic reproducer for the OTLP export race"
```

---

### Task 5: Fix it, and prove the test detects the regression

**Files:**
- Modify: whichever file in `rust/src/` the root cause names.

- [ ] **Step 1: Make the smallest change that addresses the mechanism**

Fix the cause the instrumentation showed. Not the symptom, not a nearby smell, and
nothing else in the same commit.

- [ ] **Step 2: Run the reproducer**

Run: `cd rust && cargo test --test otlp_export_regression_test`
Expected: PASS, 20 times out of 20.

- [ ] **Step 3: Negative control — revert the fix and watch it fail**

Temporarily revert the production change, run the reproducer, confirm it fails,
restore the fix, confirm it passes. Paste both outputs into the checklist. Without
this, the test may be passing for a reason unrelated to the fix.

- [ ] **Step 4: Re-measure the original flake rate**

Re-run both loops from Task 2 — serial and parallel, same iteration counts.
Expected: 0 failures in both. Compare against the recorded baseline rate; if the
baseline was 3/50 and you now see 0/50, say so with both numbers rather than
writing "fixed".

- [ ] **Step 5: Stress it both ways**

```bash
cd rust
cargo test --all-features -- --test-threads=1     # serial
cargo test --all-features                          # parallel
```
Expected: PASS both.

- [ ] **Step 6: Remove the temporary instrumentation**

Revert everything from Task 3 that is not permanently justified. For anything you
keep, say in its comment why it earns its place — a generation counter that made
this bug visible may well be worth keeping, but that has to be a decision, not
leftovers.

- [ ] **Step 7: Run the Rust gates**

```bash
cd rust
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-features
cargo llvm-cov --all-targets --all-features \
  --ignore-filename-regex '/rustlib/src/rust/library/|/\.rustup/|/toolchains/' \
  --fail-under-lines 100 --fail-under-functions 100
```
Expected: all pass. Use whichever coverage flags plan 2, Task 9 settled on.

- [ ] **Step 8: Run the Rust mutation gate**

Run: `cd rust && cargo mutants --in-place --all-features --shard 1/8`
Expected: no surviving mutants in the changed code. `--in-place` is required — the
default scratch copy breaks the three tests that resolve `spec/*.yaml` through
`concat!(env!("CARGO_MANIFEST_DIR"), "/../spec/…")` at compile time. Bound fan-out
with `CARGO_BUILD_JOBS=1` and `NEXTEST_TEST_THREADS=1` rather than `-j`.

- [ ] **Step 9: Commit**

```bash
git add rust/src rust/tests
git commit -m "fix(rust): <the mechanism, in plain words>

<What raced with what, and why the fix closes it. Reference the deterministic
reproducer and the measured before/after failure rates.>"
```

---

### Task 6: Or: close it as inconclusive

Take this path when Task 2 could not reproduce the failure, or Task 3 could not
fill the root-cause template. This is a legitimate outcome and must be recorded
as carefully as a fix.

- [ ] **Step 1: Write the inconclusive record**

Create `docs/superpowers/plans/evidence/2026-08-20-rust-flake-inconclusive.md`
containing:
- every command run, with iteration counts and observed failure counts,
- every environment tried: OS, core count, load, toolchain version,
- every hypothesis considered, and the observation that ruled each one out,
- what would make the investigation conclusive if it recurs — the exact log lines
  or instrumentation a future run should capture.

- [ ] **Step 2: Confirm nothing in `rust/src/` changed**

Run: `git diff --stat main -- rust/src`
Expected: empty. If it is not empty, you made a speculative change — revert it.

- [ ] **Step 3: Confirm nothing was quarantined**

Run: `git diff main -- rust/tests | grep -n "ignore\|skip\|sleep\|retry"`
Expected: no additions. A longer sleep or an `#[ignore]` is the outcome this plan
forbids.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/evidence/2026-08-20-rust-flake-inconclusive.md
git commit -m "docs: record the Rust OTLP flake investigation as inconclusive"
```

---

### Task 7: Update the umbrella checklist

- [ ] **Step 1: Record the outcome**

In `docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md`,
under recommendation 10, tick either the fix path or the inconclusive path — never
both, never neither.

- [ ] **Step 2: Paste the numbers, not adjectives**

The evidence block must contain the measured before-and-after failure rates, the
deterministic reproducer's 20/20 result in both directions, and the negative
control output. "Fixed" without a rate is not evidence.

- [ ] **Step 3: Confirm the worktree is clean and merge back**

```bash
git status --short
```
Expected: empty. Then follow `superpowers:finishing-a-development-branch` to
integrate, and remove the worktree or branch once merged.
