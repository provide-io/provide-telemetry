# External Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the nine verified findings from the 2026-08-11 external review: two Python CI blockers, one TS secret-detection leak, two Python header-handling defects, four C# defects, and the docs/governance drift.

**Architecture:** Each fix is a small, self-contained TDD cycle in one runtime. No cross-runtime API changes; parity-sensitive fixes (traceparent, hardening caps) mirror the Python semantics that already exist. Fixture-corpus expansion across all five runtimes is explicitly deferred — noted per task.

**Tech Stack:** Python 3.11+/pytest/uv, TypeScript/vitest, C#/.NET/xUnit, existing repo gates (ruff, mypy, ty, bandit, Stryker, mutmut, dotnet format).

## Global Constraints

- 100% branch coverage enforced (Python, TS, Go); 100% function coverage (Rust).
- 100% mutation kill enforced in CI — every new branch needs a mutant-killing test. Full mutation runs are NOT executed locally in this plan (hours; CI enforces); tests are written to kill the obvious mutants.
- 500 LOC max per file (`scripts/check_max_loc.py`).
- SPDX headers required in new files.
- mypy strict; ty must also pass.
- After modifying a Python file: `ruff format`, `ruff check --fix --unsafe-fixes`, `mypy`, `bandit`, `ty` (user global rule).
- Event literals in log calls must match `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` unless exempted (Task 1 adds the exemption mechanism).
- Commits: no Co-Authored-By (user global rule).

---

### Task 1: Python CI blockers (finding 8)

**Files:**
- Modify: `scripts/check_event_literals.py` (add `# event-literal: allow` marker)
- Modify: `src/provide/telemetry/receipts.py:117` (attach marker)
- Modify: `src/provide/telemetry/logger/processors.py:234` (cast for ty)
- Test: `tests/tooling/` (existing checker tests, extend)

**Interfaces:**
- Produces: checker honors a trailing `# event-literal: allow` comment on the log-call line or the string-literal line.

- [ ] **Step 1: Locate existing checker tests** (`grep -rl check_event_literals tests/`) and add failing test: a log call with non-event literal plus trailing `# event-literal: allow` produces zero violations; the same call without the marker still fails.
- [ ] **Step 2: Run test — expect FAIL** (marker unsupported).
- [ ] **Step 3: Implement marker in `find_event_literal_violations`:** keep source lines (`source.splitlines()`); before appending a violation, check `"# event-literal: allow"` in the call line or the literal's line:

```python
_ALLOW_MARKER = "# event-literal: allow"
...
lines = source.splitlines()
...
marker_lines = {node.lineno, getattr(first_arg_node, "lineno", node.lineno)}
if any(_ALLOW_MARKER in lines[ln - 1] for ln in marker_lines if 0 < ln <= len(lines)):
    continue
```

- [ ] **Step 4: Add marker in `receipts.py`** on the format-string line of `LoggingReceiptSink.emit` with a short reason comment above (`diagnostic format string for stdlib logging, not an event name`).
- [ ] **Step 5: Fix ty failure:** in `processors.py:234`, `cast("dict[str, Any]", value)` before `_harden_keys` (import `cast` if absent). Confirm mypy strict still passes.
- [ ] **Step 6: Run gates:** checker clean, `ty check src` clean, `uv run python scripts/run_pytest_gate.py -k "event_literal or processors" --no-cov -q`, then full Python file toolchain on both modified files.
- [ ] **Step 7: Commit** `fix(python): unblock CI — event-literal exemption for receipt sink, ty invariance cast`

### Task 2: TypeScript stateful-regex secret leak (finding 1)

**Files:**
- Modify: `typescript/src/pii.ts:66` (`registerSecretPattern`)
- Test: `typescript/tests/pii.secrets.test.ts`

**Interfaces:**
- Produces: `registerSecretPattern(name, pattern)` stores a stateless clone; `_detectSecretInValue` is deterministic across calls.

- [ ] **Step 1: Failing tests:** register `/CUSTOMSECRETVALUE1234/g` → four consecutive `_detectSecretInValue` calls all `true`; same for `y` flag; nested payload + message-path regressions per review.
- [ ] **Step 2: Run — expect FAIL** (`[true,false,...]` alternation reproduced by probe already).
- [ ] **Step 3: Implement clone-on-register:**

```ts
export function registerSecretPattern(name: string, pattern: RegExp): void {
  // g/y make RegExp.test stateful via lastIndex — a matching value would be
  // detected only on alternate calls. Detection is a containment check, so
  // dropping the flags preserves semantics and removes the state.
  const flags = pattern.flags.replace(/[gy]/g, '');
  _customSecretPatterns.set(name, new RegExp(pattern.source, flags));
}
```

Also verify `_GENERATED_PATTERNS` contains no `g`/`y` flags (grep the generated file; if any exist, strip identically at `_SECRET_PATTERNS` construction).
- [ ] **Step 4: Run TS suite + typecheck + lint** (`npx vitest run tests/pii.secrets.test.ts`, `npm run typecheck`, `npm run lint`).
- [ ] **Step 5: Commit** `fix(ts): clone custom secret patterns without g/y — stateful lastIndex leaked alternate matches`

### Task 3: Python tracestate validation (finding 3)

**Files:**
- Modify: `src/provide/telemetry/propagation.py` (`extract_w3c_context` guard + `inject_traceparent` forward path)
- Test: `tests/test_propagation*.py` (locate exact file)

**Interfaces:**
- Produces: `_is_forwardable_tracestate(value: str) -> bool` — printable-ASCII, comma-separated `key=value` members, no control chars; applied at extraction (drop to `None`) and before injection (skip forwarding).

- [ ] **Step 1: Failing tests:** tracestate `"vendor=value\r\nX-Injected: yes"` extracted → `PropagationContext.tracestate is None`; bound CRLF tracestate never appears in `inject_traceparent` output; valid `"congo=t61,rojo=00f067aa"` still forwarded.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement validator** (module-level, near other guards):

```python
_TRACESTATE_MEMBER_RE = re.compile(r"^[ \t]*[a-z0-9][a-z0-9_\-*/@]{0,255}=[\x20-\x2b\x2d-\x3c\x3e-\x7e]*[ \t]*$")


def _is_forwardable_tracestate(value: str) -> bool:
    """True when every list member fits the W3C tracestate grammar closely
    enough to forward. This is a security boundary: a control character here
    lands in an outbound HTTP header."""
    return all(_TRACESTATE_MEMBER_RE.match(member) for member in value.split(","))
```

Apply in `extract_w3c_context` after the pair-count guard (`if tracestate and not _is_forwardable_tracestate(tracestate): tracestate = None`) and in `inject_traceparent` before `headers["tracestate"] = tracestate`.
- [ ] **Step 4: Run propagation tests + full Python toolchain on the file.**
- [ ] **Step 5: Commit** `fix(python): validate tracestate grammar at extraction and before fallback injection`
- Deferred: shared parity fixtures for these negative cases across all five runtimes (separate parity work).

### Task 4: ASGI baggage guard bypass (finding 4)

**Files:**
- Modify: `src/provide/telemetry/asgi/middleware.py:47-56,127-139`
- Test: `tests/asgi/` middleware tests

**Interfaces:**
- Consumes: `extract_w3c_context`, `parse_baggage` from `propagation`.
- Produces: middleware extracts context once; session comes from the guarded `context.baggage` via `parse_baggage`.

- [ ] **Step 1: Failing tests:** (a) 4 MiB baggage header → session not bound and no unbounded scan (assert via guarded context: `ctx.baggage is None`); (b) normal `baggage: session_id=abc` still binds session; (c) `x-session-id` header still wins.
- [ ] **Step 2: Run — expect FAIL** on (a) if asserting the scan path, at minimum restructure test.
- [ ] **Step 3: Restructure `__call__`:**

```python
w3c_context = extract_w3c_context(scope)
request_id = _extract_header(scope, b"x-request-id") or uuid.uuid4().hex
session_id = _extract_header(scope, b"x-session-id")
if session_id is None and w3c_context.baggage is not None:
    session_id = parse_baggage(w3c_context.baggage).get("session_id") or None
...
bind_propagation_context(w3c_context)
```

Delete `_extract_baggage_value`. Note behavior tightening: session keys must now be RFC 7230 tokens and values lose control chars (that is `parse_baggage`'s contract — desired).
- [ ] **Step 4: Run ASGI tests + coverage for the file + Python toolchain.**
- [ ] **Step 5: Commit** `fix(python): route ASGI session baggage through the guarded propagation parser`

### Task 5: C# console/pretty renderer escaping (finding 2)

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Logger.cs:119-140` (or extract a small `Rendering.cs` if it would push Logger.cs over limits)
- Test: `csharp/tests/Provide.Telemetry.Tests/` (new `RenderInjectionTests.cs`)

**Interfaces:**
- Produces: `FormatText` output is exactly one physical line; CR, LF, ESC, NUL, other C0, DEL escaped as `\r`, `\n`, ``, `\0`, `\uXXXX`; pretty-mode quotes escape embedded `"`.

- [ ] **Step 1: Failing tests:** event containing `"a\nINFO forged"`, key `"k\r"`, scalar value `"v[31m"`, nested value with NUL — each rendered record contains no raw control chars and stays one line; pretty mode escapes `"` inside values.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement `EscapeControl(string)`** (StringBuilder scan, fast-path return when no control chars) and apply to event, every key, every stringified value in `FormatText`; escape `"` when `quote != ""`.
- [ ] **Step 4: Run `dotnet test` for the suite; `dotnet build` warnings clean.**
- [ ] **Step 5: Commit** `fix(csharp): escape control characters in console/pretty renderers — log forging`

### Task 6: C# hardening budgets and containment (finding 6)

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Hardening.cs` (`FromSequence`, `FromDictionary`, `FromPairs`, catch clause)
- Test: `csharp/tests/Provide.Telemetry.Tests/HardeningShapeTests.cs`

**Interfaces:**
- Produces: `MaxSequenceElements = 1000` (documented const); over-budget sequences truncate and append `Pii.Redacted` sentinel; any exception from enumerator acquisition/`MoveNext`/`Current` yields `Pii.Redacted` for the sequence.

- [ ] **Step 1: Failing tests:** infinite `IEnumerable` (yield loop) → hardened value is a list of exactly 1000 elements + sentinel; iterator throwing `InvalidOperationException`/`IOException` mid-stream → `Pii.Redacted`, caller unfaulted; 1001-element list truncates.
- [ ] **Step 2: Run — expect hang risk on infinite case, so write throwing/oversized first, infinite last after budget exists.**
- [ ] **Step 3: Implement:** counter in `FromSequence` foreach with break + sentinel append; widen the `Normalize` catch to `catch (Exception)` EXCEPT `OutOfMemoryException`/`StackOverflowException`-class (catch general `Exception` is acceptable here — teardown-grade containment, mirror `Swallow` rationale) — keep the existing comment updated.
- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `fix(csharp): bound hostile enumerables and contain arbitrary iterator exceptions in hardening`
- Note: Python/TS/Go lists are caller-materialized (no lazy infinite case); no parity change needed there.

### Task 7: C# traceparent strictness (finding 7)

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Propagation.cs:17,128-137`
- Test: `csharp/tests/Provide.Telemetry.Tests/` propagation tests

**Interfaces:**
- Produces: `ParseTraceparent` rejects version `ff` and surrounding whitespace; case tolerance retained (parity with Python's `int(x, 16)` acceptance).

- [ ] **Step 1: Failing tests:** `ff-<32hex>-<16hex>-01` → empty ids; `" 00-...-01 "` (leading/trailing space) → empty ids; valid uppercase hex ids still parse (pin existing tolerance).
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement:** drop `.Trim()`; after match, `if (m.Groups[1].Value.Equals("ff", StringComparison.OrdinalIgnoreCase)) return ("", "");`.
- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `fix(csharp): reject reserved traceparent version ff and surrounding whitespace`

### Task 8: C# shutdown deadline through disposal (finding 5)

**Files:**
- Modify: `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackend.cs` (`DisposeDetached`, `DisposeLogPipeline`)
- Modify: `csharp/src/Provide.Telemetry/Setup.cs:87-88` if signature must carry deadline
- Test: backend lifecycle tests (locate; add non-cooperative-dispose case)

**Interfaces:**
- Produces: provider disposal preceded by `provider.Shutdown(remainingMs)` computed from the same absolute deadline; `Dispose()` keeps first-attempt rule but its drains cannot exceed the deadline the caller advertised.

- [ ] **Step 1: Read `Shutdown(DateTimeOffset)` implementation fully; confirm where deadline is dropped.**
- [ ] **Step 2: Failing test:** fake exporter whose flush blocks 30 s; `ShutdownTelemetry()` returns within deadline + small epsilon (use short configured deadline for the test).
- [ ] **Step 3: Implement:** thread the deadline into `DisposeDetached` (e.g. `DisposeDetached(DateTimeOffset deadline)`); before `tracerProvider.Dispose()`, call `tracerProvider.Shutdown(remainingMs)` (OTel .NET `Shutdown(int)` is deadline-bounded; post-shutdown `Dispose` is cheap). Same for meter/logger providers. Preserve the documented one-attempt Dispose path by clamping remaining to ≥0 → OTel treats 0 as immediate.
- [ ] **Step 4: Run C# suite.**
- [ ] **Step 5: Commit** `fix(csharp): bound provider disposal under the advertised shutdown deadline`

### Task 9: Docs corrections (finding 9 + bonus)

**Files:**
- Modify: `docs/CAPABILITY_MATRIX.md:33,98-101` (middleware TS/Go → missing/known gap)
- Modify: `spec/run_behavioral_parity.py:7` docstring four → five
- Modify: `CLAUDE.md` (add C# to polyglot structure; five languages)

- [ ] **Step 1: Fix matrix row and prose to match reality (only Python ships middleware).**
- [ ] **Step 2: Fix parity docstring count.**
- [ ] **Step 3: Update CLAUDE.md language list + add `csharp/` to structure section.**
- [ ] **Step 4: Run `uv run python scripts/check_docs_accuracy.py` if it exists (grep scripts/); run parity script `--help` smoke.**
- [ ] **Step 5: Commit** `docs: correct middleware capability claims, five-language counts, stale CLAUDE.md`

### Task 10: Governance (finding 10)

**Files:**
- Modify: 44 pragma sites listed by `scripts/check_pragma_reasons.py` (mostly `receipts.py`, `resilience.py`, others per output)
- Modify: `.github/workflows/ci-python.yml` (wire `check_pragma_reasons.py`)
- Modify: `.github/workflows/ci-csharp.yml` (add `dotnet format --verify-no-changes` gate)
- Run: `dotnet format` across `csharp/` to make the gate green

- [ ] **Step 1: Enumerate all 44 sites; write a real reason per pragma (read each site; no boilerplate reasons).**
- [ ] **Step 2: `check_pragma_reasons.py` exits clean; add it to ci-python.yml alongside the other custom gates.**
- [ ] **Step 3: `dotnet format csharp/Provide.Telemetry.sln`; review diff; add verify step to ci-csharp.yml.**
- [ ] **Step 4: Run Python + C# suites to confirm formatting/pragma edits changed nothing behavioral.**
- [ ] **Step 5: Commit** in two commits: `chore(python): reasons for every mutation pragma + CI gate` and `chore(csharp): dotnet format + CI format gate`.

---

## Deferred (explicitly out of scope, per-review items needing infra or cross-runtime programs)

- Shared parity fixture corpus for tracestate/traceparent negative cases across five runtimes.
- C# OpenObserve/collector delivery made CI-blocking (needs CI collector service).
- Review's adversarial campaigns 1–7.
