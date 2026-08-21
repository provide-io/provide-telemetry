# Runtime Contract Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Go's OpenTelemetry global-provider ownership identity-based so a host application's late provider registration survives our shutdown, and make `event_name` behave identically in all five languages.

**Architecture:** Two independent changes in one plan because both are runtime contracts covered by the same cross-language fixture corpus. Go ownership becomes an identity comparison (is the global still the exact pointer we installed?) rather than a boolean ("did we ever install one?"). `event_name` adopts the Python/TypeScript/Rust contract — relaxed accepts 1+ non-empty segments, strict accepts 3–5 grammar-checked segments — which is a **breaking loosening** for Go and C#. `Event()`/`event()` is explicitly out of scope and keeps its 3-or-4 rule.

**Tech Stack:** Go 1.26 (`go/`, `go/otel/` modules), C# .NET (`csharp/`), Python 3.11+, TypeScript, Rust; YAML fixture corpus under `spec/`.

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2) — workstream A.

## Global Constraints

- **777 LOC max per file**, enforced by `scripts/check_max_loc.py --max-lines 777`. New files must stay under it.
- **SPDX headers required** in every source file. Copy the three-line header from any neighbouring file in the same language.
- **100% branch coverage** (Python, TypeScript, Go) and **100% mutation kill** in every language. Every new branch added here needs a test that kills its mutants.
- **mypy strict** for Python: no `Any`, full annotations.
- **No OTel imports at module level** in non-`otel`-extra Python files.
- Segment grammar is `^[a-z][a-z0-9_]*$` and does **not** change.
- Strict segment range is 3–5 inclusive. Relaxed minimum is 1. Zero segments always fail. An empty segment always fails, in both modes, for both variadic and dotted-string entry points.
- `Event()` / `event()` keeps exactly-3-or-4 segments in every language. Do not touch it.
- Commit messages must not mention AI assistance and must not carry a `Co-Authored-By: Claude` trailer.

## File Structure

**Go provider ownership**
- Modify: `go/otel/backend.go:205-231` — capture installed providers before nil-out; identity-checked global reset.
- Modify: `go/otel/providers.go:19-77` — conflict warnings stop treating any concrete SDK provider as ours.
- Create: `go/otel/ownership_test.go` — late-host-replacement regression tests for all three signals.

**Event-name contract**
- Modify: `spec/telemetry-api.yaml:969-973` — `event_schema` restructured for both modes and both entry points.
- Modify: `spec/behavioral_fixtures.yaml` — new `event_name_contract` category.
- Modify: `spec/fixture_test_ids.yaml` — per-case test IDs for the new category.
- Modify: `spec/check_fixture_test_ids.py:110-121` — accept a list of per-case IDs.
- Modify: `go/internal/schemacore/schema.go:31-48` — `ValidateEventSegments` relaxed/strict split.
- Modify: `csharp/src/Provide.Telemetry/Schema.cs:62-93` — shared `ValidateSegments` helper; `ValidateEventName` reads strict mode.
- Create/modify per-language parity tests: `tests/parity/test_event_name_contract.py`, `typescript/tests/parity-event-name.test.ts`, `go/parity_event_name_test.go`, `rust/tests/parity_event_name_test.rs`, `csharp/tests/Provide.Telemetry.Tests/ParityEventNameTests.cs`.
- Modify: `CHANGELOG.md`, `go/README.md`, `csharp/README.md`.

---

### Task 1: Go — failing test for late host replacement (traces)

**Files:**
- Create: `go/otel/ownership_test.go`

**Interfaces:**
- Consumes: `telemetry.ShutdownTelemetry(ctx)`, `otel.SetTracerProvider`, the test helpers already used by `go/otel/adopt_test.go`.
- Produces: `TestShutdown_LeavesALateHostTracerProviderInstalled` — Task 2 makes it pass.

- [ ] **Step 1: Write the failing test**

```go
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// A host that installs its own provider AFTER our Setup owns the global from
// that moment on. Our Shutdown must not overwrite it: the ownership flag says
// "we set it once", but the global no longer holds the provider we set.
func TestShutdown_LeavesALateHostTracerProviderInstalled(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(_resetOTelProviders)

	// Our setup installs a provider and takes the global.
	ours := sdktrace.NewTracerProvider()
	_providersMu.Lock()
	_otelTracerProvider = ours
	otel.SetTracerProvider(ours)
	_weSetTracerGlobal = true
	_providersMu.Unlock()

	// The host replaces the global afterwards — an auto-instrumentation agent,
	// a vendor distro, a lazily-initialised SDK.
	hostTP := sdktrace.NewTracerProvider()
	otel.SetTracerProvider(hostTP)

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}

	if got := otel.GetTracerProvider(); got != hostTP {
		t.Fatalf("shutdown replaced the host's tracer provider: got %T, want the host's *sdktrace.TracerProvider", got)
	}
	_ = telemetry.TracingEnabled() // keep the root package linked for parity with sibling tests
}
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd go/otel && go test -run TestShutdown_LeavesALateHostTracerProviderInstalled -v ./...`
Expected: FAIL — `shutdown replaced the host's tracer provider: got *noop.TracerProvider`.

- [ ] **Step 3: Commit the red test**

```bash
git add go/otel/ownership_test.go
git commit -m "test(go): late host tracer provider must survive shutdown"
```

---

### Task 2: Go — identity-checked global reset

**Files:**
- Modify: `go/otel/backend.go:205-231`

**Interfaces:**
- Consumes: `_otelTracerProvider`, `_otelMeterProvider`, `_otelLoggerProvider` (`go/otel/backend.go:26-28`), `_weSetTracerGlobal` / `_weSetMeterGlobal` / `_weSetLoggerGlobal` (`:33-35`).
- Produces: `_resetGlobalsWeSet(tp *sdktrace.TracerProvider, mp *sdkmetric.MeterProvider, lp *sdklog.LoggerProvider)` — the signature changes; `ResetForTests` is unaffected because it resets unconditionally.

- [ ] **Step 1: Capture the installed providers before nil-ing them**

`Shutdown` currently nils the fields *before* calling `_resetGlobalsWeSet()`, so the reset has nothing to compare against. Replace the body of `func (b *_backend) Shutdown` between the `Lock()` and `Unlock()`:

```go
	_providersMu.Lock()
	providers := _installedProvidersLocked()
	// Capture before the nil-out: _resetGlobalsWeSet compares these against the
	// live globals to decide whether the registration is still ours to undo.
	installedTP, installedMP, installedLP := _otelTracerProvider, _otelMeterProvider, _otelLoggerProvider
	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil
	_resetGlobalsWeSet(installedTP, installedMP, installedLP)
	_providersMu.Unlock()
```

- [ ] **Step 2: Make the reset identity-checked**

Replace `_resetGlobalsWeSet` entirely:

```go
// _resetGlobalsWeSet returns to the API no-ops only for the globals this
// backend registered AND still owns.
//
// The ownership booleans alone are not enough. They record that we registered a
// provider once; they say nothing about whether the registration survived. A
// host that calls otel.SetTracerProvider after our Setup owns the global from
// that moment on — an auto-instrumentation agent, a vendor distro, a lazily
// initialised SDK — and overwriting it with a no-op would silently disable the
// host's telemetry. So we compare identity: reset only while the global still
// holds the exact provider we installed. Either way we relinquish the flag,
// because after this call we no longer have a registration to undo.
func _resetGlobalsWeSet(tp *sdktrace.TracerProvider, mp *sdkmetric.MeterProvider, lp *sdklog.LoggerProvider) {
	if _weSetTracerGlobal {
		if tp != nil && otel.GetTracerProvider() == oteltrace.TracerProvider(tp) {
			otel.SetTracerProvider(otelnooptrace.NewTracerProvider())
		}
		_weSetTracerGlobal = false
	}
	if _weSetMeterGlobal {
		if mp != nil && otel.GetMeterProvider() == otelmetric.MeterProvider(mp) {
			otel.SetMeterProvider(otelmetricnoop.NewMeterProvider())
		}
		_weSetMeterGlobal = false
	}
	if _weSetLoggerGlobal {
		if lp != nil && logglobal.GetLoggerProvider() == otellog.LoggerProvider(lp) {
			logglobal.SetLoggerProvider(otellognoop.NewLoggerProvider())
		}
		_weSetLoggerGlobal = false
	}
}
```

Add whichever of these imports `backend.go` does not already have:

```go
	otelmetric "go.opentelemetry.io/otel/metric"
	otellog "go.opentelemetry.io/otel/log"
	oteltrace "go.opentelemetry.io/otel/trace"
```

- [ ] **Step 3: Run the Task 1 test and confirm it passes**

Run: `cd go/otel && go test -run TestShutdown_LeavesALateHostTracerProviderInstalled -v ./...`
Expected: PASS.

- [ ] **Step 4: Add the metrics and logs siblings**

Append to `go/otel/ownership_test.go`. These are separate tests, not table rows, because each drives a different global and a mutation that breaks only one of them must fail only one test.

```go
func TestShutdown_LeavesALateHostMeterProviderInstalled(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(_resetOTelProviders)

	ours := sdkmetric.NewMeterProvider()
	_providersMu.Lock()
	_otelMeterProvider = ours
	otel.SetMeterProvider(ours)
	_weSetMeterGlobal = true
	_providersMu.Unlock()

	hostMP := sdkmetric.NewMeterProvider()
	otel.SetMeterProvider(hostMP)

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}
	if got := otel.GetMeterProvider(); got != hostMP {
		t.Fatalf("shutdown replaced the host's meter provider: got %T", got)
	}
}

func TestShutdown_LeavesALateHostLoggerProviderInstalled(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(_resetOTelProviders)

	ours := sdklog.NewLoggerProvider()
	_providersMu.Lock()
	_otelLoggerProvider = ours
	logglobal.SetLoggerProvider(ours)
	_weSetLoggerGlobal = true
	_providersMu.Unlock()

	hostLP := sdklog.NewLoggerProvider()
	logglobal.SetLoggerProvider(hostLP)

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}
	if got := logglobal.GetLoggerProvider(); got != hostLP {
		t.Fatalf("shutdown replaced the host's logger provider: got %T", got)
	}
}

// The other half of the contract: when the global still holds OUR provider,
// shutdown must still hand it back to the API no-op. Without this test the
// identity check could be mutated to `false` and nothing would notice.
func TestShutdown_StillResetsOurOwnTracerGlobal(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(_resetOTelProviders)

	ours := sdktrace.NewTracerProvider()
	_providersMu.Lock()
	_otelTracerProvider = ours
	otel.SetTracerProvider(ours)
	_weSetTracerGlobal = true
	_providersMu.Unlock()

	if err := (&_backend{}).Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown failed: %v", err)
	}
	if got := otel.GetTracerProvider(); got == oteltrace.TracerProvider(ours) {
		t.Fatal("shutdown left our own provider registered globally")
	}
}
```

Add the imports these need: `sdkmetric "go.opentelemetry.io/otel/sdk/metric"`, `sdklog "go.opentelemetry.io/otel/sdk/log"`, `logglobal "go.opentelemetry.io/otel/log/global"`, `oteltrace "go.opentelemetry.io/otel/trace"`.

- [ ] **Step 5: Run the full Go otel suite with the race detector**

Run: `cd go/otel && go test ./... -race`
Expected: PASS, including the pre-existing `adopt_test.go` and `conflict_test.go` suites.

- [ ] **Step 6: Negative control — prove the tests detect the regression**

Temporarily change the tracer branch back to the unconditional form:

```go
	if _weSetTracerGlobal {
		otel.SetTracerProvider(otelnooptrace.NewTracerProvider())
		_weSetTracerGlobal = false
	}
```

Run: `cd go/otel && go test -run TestShutdown_LeavesALateHost -v ./...`
Expected: FAIL on the tracer test. Restore the identity check and re-run: PASS.

- [ ] **Step 7: Commit**

```bash
git add go/otel/backend.go go/otel/ownership_test.go
git commit -m "fix(go): only reset OTel globals that still hold our provider

Shutdown reset the global whenever the ownership flag was set, without
checking the global still pointed at the provider we installed. A host that
registered its own provider after setup had it replaced with an API no-op,
silently disabling its telemetry. Compare identity before resetting."
```

---

### Task 3: Go — conflict warning stops mistaking host SDK providers for ours

**Files:**
- Modify: `go/otel/providers.go:19-77`
- Modify: `go/otel/conflict_test.go`

**Interfaces:**
- Consumes: `_otelTracerProvider` / `_otelMeterProvider` / `_otelLoggerProvider`, `telemetry.Logger()`.
- Produces: no signature change; only the suppression rule changes.

- [ ] **Step 1: Write the failing test**

Append to `go/otel/conflict_test.go`. `newCaptureHandler` and `_thirdPartyTracerProvider` already exist in that file.

```go
// A host-installed *sdktrace.TracerProvider is not ours. The old code suppressed
// the warning for any concrete SDK provider, so the one case most likely to be a
// real conflict — a host running the same SDK we do — was the one case that
// warned least.
func TestConflictWarning_FiresForAHostInstalledSDKProvider(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(_resetOTelProviders)

	handler := newCaptureHandler(slog.LevelWarn)
	restore := telemetry.SetLoggerForTests(slog.New(handler))
	t.Cleanup(restore)

	otel.SetTracerProvider(sdktrace.NewTracerProvider())

	_providersMu.Lock()
	_warnIfTracerProviderConflict()
	_providersMu.Unlock()

	if !strings.Contains(handler.buf.String(), "otel.tracer_provider_conflict") {
		t.Fatalf("no conflict warning for a host-installed SDK provider; got %q", handler.buf.String())
	}
}
```

If `telemetry.SetLoggerForTests` does not exist under that name, use whatever the existing tests in `conflict_test.go` use to install a capture logger — read the top of that file and copy the pattern verbatim rather than inventing one.

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd go/otel && go test -run TestConflictWarning_FiresForAHostInstalledSDKProvider -v ./...`
Expected: FAIL — no warning emitted.

- [ ] **Step 3: Delete the ownership-blind suppression**

In `_warnIfTracerProviderConflict`, remove:

```go
	if _, isSDK := existing.(*sdktrace.TracerProvider); isSDK {
		return
	}
```

Do the same for `*sdkmetric.MeterProvider` in `_warnIfMeterProviderConflict` and `*sdklog.LoggerProvider` in `_warnIfLoggerProviderConflict`. Replace the removed block with the reason it is gone:

```go
	// No type-based suppression. This function is only reached when
	// _otelTracerProvider is nil — we have not installed anything — so a live
	// concrete provider on the global belongs to the host by definition, and a
	// host running the same SDK we do is the most likely real conflict, not the
	// least. Ownership is the evidence, not the type.
```

Drop the now-unused `sdktrace` / `sdkmetric` / `sdklog` imports if nothing else in `providers.go` uses them — `_setupTracerProvider` and friends still do, so they stay.

- [ ] **Step 4: Run the conflict suite**

Run: `cd go/otel && go test -run TestConflict -v ./...`
Expected: PASS. If a pre-existing test asserted silence for an SDK provider, it encoded the bug — update it to assert the warning and note why in its comment.

- [ ] **Step 5: Run the whole Go workspace**

Run: `cd go && go test ./... -race && cd otel && go test ./... -race`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add go/otel/providers.go go/otel/conflict_test.go
git commit -m "fix(go): warn on host SDK provider conflicts

The conflict check suppressed its warning for any *sdktrace.TracerProvider,
treating every concrete SDK provider as one of ours. Ownership already
short-circuits this function, so reaching the type check means the provider is
the host's — exactly the case worth announcing before we overwrite it."
```

---

### Task 4: Spec — restructure the `event_schema` contract block

**Files:**
- Modify: `spec/telemetry-api.yaml:969-973`

**Interfaces:**
- Consumes: nothing — verify this first (Step 1).
- Produces: `event_schema.event_record`, `event_schema.event_name.relaxed`, `event_schema.event_name.strict`, `event_schema.empty_segment` for later documentation and review reference.

- [ ] **Step 1: Prove no tooling parses the current keys**

Run: `grep -rn "event_schema\|min_segments\|max_segments" spec/*.py scripts/*.py`
Expected: no hits that read these YAML keys (Python's `enforce_event_schema` function name is unrelated). If a hit *does* read them, update that consumer in this same task — do not leave it reading a key you removed.

- [ ] **Step 2: Replace the block**

```yaml
event_schema:
  segment_pattern: "^[a-z][a-z0-9_]*$"
  separator: "."

  # event() / Event(): positional DAS/DARS record builder. Its count rule is a
  # property of the record shape, not of the name, so it is independent of
  # strict mode and is NOT changed by the 2026-08-20 remediation.
  event_record:
    min_segments: 3
    max_segments: 4

  # event_name() / EventName() and validate_event_name() / ValidateEventName():
  # name builder and dotted-string validator. Relaxed is the default.
  event_name:
    relaxed:
      min_segments: 1
      max_segments: null        # unbounded
      grammar_enforced: false
    strict:
      min_segments: 3
      max_segments: 5
      grammar_enforced: true

  # An empty segment is rejected in BOTH modes, through BOTH the variadic and
  # the dotted-string entry points. Zero segments is only reachable through the
  # variadic form: splitting "" on "." yields one empty segment, not zero.
  empty_segment: reject
```

- [ ] **Step 3: Verify the spec still loads and conformance still runs**

Run: `uv run python -c "import yaml,pathlib;yaml.safe_load(pathlib.Path('spec/telemetry-api.yaml').read_text())" && uv run python spec/validate_conformance.py`
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add spec/telemetry-api.yaml
git commit -m "spec: split event_schema into record and name contracts

The single min/max pair could not express relaxed vs strict, and its
max_segments: 4 already disagreed with the 3-5 range every EventName
implementation ships."
```

---

### Task 5: Fixtures — add the `event_name_contract` category

**Files:**
- Modify: `spec/behavioral_fixtures.yaml`

**Interfaces:**
- Produces: category `event_name_contract`, a list of cases each with `id`, `description`, `mode`, `segments` or `name`, and either `expected` or `expected_error: true`. Tasks 6–10 consume the `id` values.

- [ ] **Step 1: Append the category**

Insert after the existing `event_dars` block (which ends at `spec/behavioral_fixtures.yaml:116`), keeping the file's two-space indentation and blank-line-between-cases style:

```yaml
event_name_contract:
  # Variadic entry point: event_name() / EventName().
  - id: relaxed_single_segment_ok
    description: "relaxed: 1 segment is accepted"
    mode: relaxed
    segments: ["startup"]
    expected: "startup"

  - id: relaxed_two_segments_ok
    description: "relaxed: 2 segments are accepted"
    mode: relaxed
    segments: ["app", "ready"]
    expected: "app.ready"

  - id: relaxed_six_segments_ok
    description: "relaxed: no upper bound"
    mode: relaxed
    segments: ["a", "b", "c", "d", "e", "f"]
    expected: "a.b.c.d.e.f"

  - id: relaxed_grammar_not_enforced
    description: "relaxed: segments that violate the strict grammar are accepted"
    mode: relaxed
    segments: ["User", "Login-OK"]
    expected: "User.Login-OK"

  - id: relaxed_zero_segments_error
    description: "relaxed: zero segments always fail"
    mode: relaxed
    segments: []
    expected_error: true

  - id: relaxed_empty_segment_error
    description: "relaxed: an empty segment always fails"
    mode: relaxed
    segments: ["user", "", "ok"]
    expected_error: true

  - id: strict_three_segments_ok
    description: "strict: 3 segments accepted"
    mode: strict
    segments: ["user", "login", "ok"]
    expected: "user.login.ok"

  - id: strict_five_segments_ok
    description: "strict: 5 segments accepted"
    mode: strict
    segments: ["a", "b", "c", "d", "e"]
    expected: "a.b.c.d.e"

  - id: strict_two_segments_error
    description: "strict: 2 segments rejected"
    mode: strict
    segments: ["too", "few"]
    expected_error: true

  - id: strict_six_segments_error
    description: "strict: 6 segments rejected"
    mode: strict
    segments: ["a", "b", "c", "d", "e", "f"]
    expected_error: true

  - id: strict_grammar_enforced
    description: "strict: a segment violating ^[a-z][a-z0-9_]*$ is rejected"
    mode: strict
    segments: ["user", "Login", "ok"]
    expected_error: true

  - id: strict_zero_segments_error
    description: "strict: zero segments rejected"
    mode: strict
    segments: []
    expected_error: true

  # Dotted-string entry point: validate_event_name() / ValidateEventName().
  - id: validate_relaxed_single_segment_ok
    description: "validate, relaxed: a 1-segment dotted name is accepted"
    mode: relaxed
    name: "startup"
    expected_error: false

  - id: validate_relaxed_empty_string_error
    description: "validate, relaxed: the empty string is one empty segment, and fails"
    mode: relaxed
    name: ""
    expected_error: true

  - id: validate_relaxed_interior_empty_segment_error
    description: "validate, relaxed: a..b has an empty interior segment, and fails"
    mode: relaxed
    name: "a..b"
    expected_error: true

  - id: validate_relaxed_grammar_not_enforced
    description: "validate, relaxed: grammar violations are accepted"
    mode: relaxed
    name: "User.Login-OK"
    expected_error: false

  - id: validate_strict_grammar_enforced
    description: "validate, strict: grammar violations are rejected"
    mode: strict
    name: "user.Login.ok"
    expected_error: true

  - id: validate_strict_two_segments_error
    description: "validate, strict: 2 segments rejected"
    mode: strict
    name: "too.few"
    expected_error: true
```

- [ ] **Step 2: Verify the file still parses and count the cases**

Run:
```bash
uv run python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('spec/behavioral_fixtures.yaml').read_text())
cases = d['event_name_contract']
print(len(cases), 'cases')
assert len({c['id'] for c in cases}) == len(cases), 'duplicate fixture id'
"
```
Expected: `18 cases` and no assertion error.

- [ ] **Step 3: Confirm the fixture gates now fail (they have no test IDs yet)**

Run: `uv run python spec/check_fixture_test_ids.py`
Expected: FAIL — `event_name_contract: missing fixture_test_ids entry`. This is the red state Tasks 6–10 clear.

- [ ] **Step 4: Commit**

```bash
git add spec/behavioral_fixtures.yaml
git commit -m "spec: add event_name_contract behavioral fixtures"
```

---

### Task 6: Gate — per-case test IDs, not per-category mentions

**Files:**
- Modify: `spec/check_fixture_test_ids.py:110-121`
- Create: `tests/tooling/test_fixture_test_ids_per_case.py`

**Interfaces:**
- Consumes: `spec/behavioral_fixtures.yaml`, `spec/fixture_test_ids.yaml`, the existing `_python_ids()` / `_typescript_ids()` / `_go_ids()` / `_rust_ids()` / `_csharp_ids()` discovery functions.
- Produces: `fixture_test_ids.<category>.<language>` may now be a **list** of identifiers; when it is, its length must equal the number of fixture cases in that category and every entry must resolve.

- [ ] **Step 1: Write the failing gate test**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The fixture-ID gate must count per-case evidence, not accept a category name."""

from __future__ import annotations

import pytest

from spec.check_fixture_test_ids import _resolve_ids


def test_list_shorter_than_case_count_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_b"],
        case_count=3,
        discovered={"test_a", "test_b"},
    )
    assert any("expected 3 test IDs" in error for error in errors)


def test_list_matching_case_count_with_all_ids_resolving_is_clean() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_b"],
        case_count=2,
        discovered={"test_a", "test_b"},
    )
    assert errors == []


def test_unresolved_id_inside_a_list_is_an_error() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=["test_a", "test_missing"],
        case_count=2,
        discovered={"test_a"},
    )
    assert any("test_missing" in error for error in errors)


def test_string_identifier_keeps_the_old_single_id_behaviour() -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier="test_a",
        case_count=7,
        discovered={"test_a"},
    )
    assert errors == []


@pytest.mark.parametrize("identifier", [None, "", []])
def test_missing_or_empty_identifier_is_an_error(identifier: object) -> None:
    errors = _resolve_ids(
        category="demo",
        language="python",
        identifier=identifier,
        case_count=1,
        discovered=set(),
    )
    assert any("missing test ID" in error for error in errors)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_fixture_test_ids_per_case.py`
Expected: FAIL — `ImportError: cannot import name '_resolve_ids'`.

- [ ] **Step 3: Extract and extend the resolver**

In `spec/check_fixture_test_ids.py`, add above `validate()`:

```python
def _resolve_ids(
    *,
    category: str,
    language: str,
    identifier: object,
    case_count: int,
    discovered: set[str],
) -> list[str]:
    """Resolve one category/language mapping to errors.

    A string is the legacy form: one test stands for the whole category. A list
    is per-case evidence: exactly one identifier per fixture case, which is what
    stops a category from passing on a single test that happens to mention it.
    """
    if isinstance(identifier, list):
        if len(identifier) != case_count:
            return [f"{category}:{language}: expected {case_count} test IDs, got {len(identifier)}"]
        errors: list[str] = []
        for entry in identifier:
            if not isinstance(entry, str) or not entry:
                errors.append(f"{category}:{language}: missing test ID in list")
            elif entry not in discovered and not _is_probe(entry):
                errors.append(f"{category}:{language}: unresolved test ID {entry!r}")
        return errors
    if not isinstance(identifier, str) or not identifier:
        return [f"{category}:{language}: missing test ID"]
    if identifier not in discovered and not _is_probe(identifier):
        return [f"{category}:{language}: unresolved test ID {identifier!r}"]
    return []
```

Then in `validate()`, replace the per-language body of the `for language in REQUIRED_LANGUAGES:` loop with:

```python
        for language in REQUIRED_LANGUAGES:
            errors.extend(
                _resolve_ids(
                    category=category,
                    language=language,
                    identifier=by_language.get(language),
                    case_count=len(fixtures[category]),
                    discovered=discovered[language],
                )
            )
```

- [ ] **Step 4: Run the gate test and confirm it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_fixture_test_ids_per_case.py`
Expected: PASS.

- [ ] **Step 5: Confirm the existing manifest still passes under the string form**

Run: `uv run python spec/check_fixture_test_ids.py`
Expected: still fails **only** on `event_name_contract: missing fixture_test_ids entry`. Every pre-existing category must still resolve — the string branch is unchanged behavior.

- [ ] **Step 6: Commit**

```bash
git add spec/check_fixture_test_ids.py tests/tooling/test_fixture_test_ids_per_case.py
git commit -m "test(spec): require per-case fixture test IDs

A category passed the gate on one test that mentioned it. A list of
identifiers, length-checked against the fixture case count, makes each case
carry its own executable evidence."
```

---

### Task 7: Go — relaxed mode in `schemacore`

**Files:**
- Modify: `go/internal/schemacore/schema.go:31-48`
- Create: `go/parity_event_name_test.go`

**Interfaces:**
- Consumes: `schemacore.MinSegments` (3), `schemacore.MaxSegments` (5), `schemacore.ValidateSegmentFormat`.
- Produces: `ValidateEventSegments(strictSchema bool, segments []string) error` — same signature, new relaxed behavior. `ValidateEventCall` is **not** touched.

- [ ] **Step 1: Write the failing parity tests**

Create `go/parity_event_name_test.go`. One test per fixture case, named to match the IDs registered in Task 10.

```go
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry_test

import (
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func relaxed(t *testing.T) {
	t.Helper()
	telemetry.SetStrictSchema(false)
	t.Cleanup(func() { telemetry.SetStrictSchema(false) })
}

func strict(t *testing.T) {
	t.Helper()
	telemetry.SetStrictSchema(true)
	t.Cleanup(func() { telemetry.SetStrictSchema(false) })
}

func TestParity_EventName_RelaxedSingleSegmentOK(t *testing.T) {
	relaxed(t)
	got, err := telemetry.EventName("startup")
	if err != nil {
		t.Fatalf("relaxed 1 segment rejected: %v", err)
	}
	if got != "startup" {
		t.Fatalf("got %q, want %q", got, "startup")
	}
}

func TestParity_EventName_RelaxedTwoSegmentsOK(t *testing.T) {
	relaxed(t)
	got, err := telemetry.EventName("app", "ready")
	if err != nil || got != "app.ready" {
		t.Fatalf("got %q, %v; want %q, nil", got, err, "app.ready")
	}
}

func TestParity_EventName_RelaxedSixSegmentsOK(t *testing.T) {
	relaxed(t)
	got, err := telemetry.EventName("a", "b", "c", "d", "e", "f")
	if err != nil || got != "a.b.c.d.e.f" {
		t.Fatalf("got %q, %v; want %q, nil", got, err, "a.b.c.d.e.f")
	}
}

func TestParity_EventName_RelaxedGrammarNotEnforced(t *testing.T) {
	relaxed(t)
	got, err := telemetry.EventName("User", "Login-OK")
	if err != nil || got != "User.Login-OK" {
		t.Fatalf("got %q, %v; want %q, nil", got, err, "User.Login-OK")
	}
}

func TestParity_EventName_RelaxedZeroSegmentsError(t *testing.T) {
	relaxed(t)
	if _, err := telemetry.EventName(); err == nil {
		t.Fatal("zero segments must fail in relaxed mode")
	}
}

func TestParity_EventName_RelaxedEmptySegmentError(t *testing.T) {
	relaxed(t)
	if _, err := telemetry.EventName("user", "", "ok"); err == nil {
		t.Fatal("an empty segment must fail in relaxed mode")
	}
}

func TestParity_EventName_StrictThreeSegmentsOK(t *testing.T) {
	strict(t)
	got, err := telemetry.EventName("user", "login", "ok")
	if err != nil || got != "user.login.ok" {
		t.Fatalf("got %q, %v; want %q, nil", got, err, "user.login.ok")
	}
}

func TestParity_EventName_StrictFiveSegmentsOK(t *testing.T) {
	strict(t)
	got, err := telemetry.EventName("a", "b", "c", "d", "e")
	if err != nil || got != "a.b.c.d.e" {
		t.Fatalf("got %q, %v; want %q, nil", got, err, "a.b.c.d.e")
	}
}

func TestParity_EventName_StrictTwoSegmentsError(t *testing.T) {
	strict(t)
	if _, err := telemetry.EventName("too", "few"); err == nil {
		t.Fatal("2 segments must fail in strict mode")
	}
}

func TestParity_EventName_StrictSixSegmentsError(t *testing.T) {
	strict(t)
	if _, err := telemetry.EventName("a", "b", "c", "d", "e", "f"); err == nil {
		t.Fatal("6 segments must fail in strict mode")
	}
}

func TestParity_EventName_StrictGrammarEnforced(t *testing.T) {
	strict(t)
	if _, err := telemetry.EventName("user", "Login", "ok"); err == nil {
		t.Fatal("a grammar violation must fail in strict mode")
	}
}

func TestParity_EventName_StrictZeroSegmentsError(t *testing.T) {
	strict(t)
	if _, err := telemetry.EventName(); err == nil {
		t.Fatal("zero segments must fail in strict mode")
	}
}

func TestParity_ValidateEventName_RelaxedSingleSegmentOK(t *testing.T) {
	relaxed(t)
	if err := telemetry.ValidateEventName("startup"); err != nil {
		t.Fatalf("relaxed 1-segment dotted name rejected: %v", err)
	}
}

func TestParity_ValidateEventName_RelaxedEmptyStringError(t *testing.T) {
	relaxed(t)
	if err := telemetry.ValidateEventName(""); err == nil {
		t.Fatal(`"" must fail: it is one empty segment`)
	}
}

func TestParity_ValidateEventName_RelaxedInteriorEmptySegmentError(t *testing.T) {
	relaxed(t)
	if err := telemetry.ValidateEventName("a..b"); err == nil {
		t.Fatal(`"a..b" must fail: interior empty segment`)
	}
}

func TestParity_ValidateEventName_RelaxedGrammarNotEnforced(t *testing.T) {
	relaxed(t)
	if err := telemetry.ValidateEventName("User.Login-OK"); err != nil {
		t.Fatalf("relaxed mode must not enforce grammar: %v", err)
	}
}

func TestParity_ValidateEventName_StrictGrammarEnforced(t *testing.T) {
	strict(t)
	if err := telemetry.ValidateEventName("user.Login.ok"); err == nil {
		t.Fatal("strict mode must enforce grammar")
	}
}

func TestParity_ValidateEventName_StrictTwoSegmentsError(t *testing.T) {
	strict(t)
	if err := telemetry.ValidateEventName("too.few"); err == nil {
		t.Fatal("2 segments must fail in strict mode")
	}
}

// Event() is out of scope and must not move.
func TestParity_Event_CountRuleUnchangedByRelaxedMode(t *testing.T) {
	relaxed(t)
	if _, err := telemetry.Event("only", "two"); err == nil {
		t.Fatal("Event() must still require 3 or 4 segments in relaxed mode")
	}
	if _, err := telemetry.Event("a", "b", "c", "d", "e"); err == nil {
		t.Fatal("Event() must still reject 5 segments")
	}
}
```

If the strict-mode setter is not exported as `telemetry.SetStrictSchema`, read `go/schema.go` for `_readStrictSchema` and use whatever the existing Go tests use to toggle it. Do not add a new exported setter — that would broaden the public API, which the spec forbids.

- [ ] **Step 2: Run and confirm the relaxed tests fail**

Run: `cd go && go test -run TestParity_EventName -v ./...`
Expected: the four relaxed-acceptance tests and both relaxed `ValidateEventName` acceptance tests FAIL with "event name must have 3–5 segments". The strict tests and the `Event()` test already PASS.

- [ ] **Step 3: Split relaxed from strict in `schemacore`**

Replace `ValidateEventSegments` in `go/internal/schemacore/schema.go`:

```go
// ValidateEventSegments validates event-name segments under the shared
// five-language contract.
//
// Relaxed (the default) accepts one or more segments and enforces no grammar.
// Strict accepts MinSegments..MaxSegments and requires every segment to match
// SegmentRe. An empty segment fails in both modes; zero segments fail in both
// modes. This is deliberately more permissive than the pre-2026-08-20 Go
// behavior, which enforced the 3–5 count regardless of mode — see CHANGELOG.
//
// ValidateEventCall is a separate contract and is not affected: event() builds
// a positional DAS/DARS record, so its 3-or-4 rule is a property of the record
// shape rather than of the name.
func ValidateEventSegments(strictSchema bool, segments []string) error {
	if len(segments) == 0 {
		return fmt.Errorf("event name requires at least 1 segment, got 0")
	}
	for _, seg := range segments {
		if seg == "" {
			return fmt.Errorf("event name segments must be non-empty")
		}
	}
	if !strictSchema {
		return nil
	}
	if n := len(segments); n < MinSegments || n > MaxSegments {
		return fmt.Errorf("event name must have %d–%d segments, got %d",
			MinSegments, MaxSegments, n)
	}
	for _, seg := range segments {
		if !ValidateSegmentFormat(seg) {
			return fmt.Errorf(
				"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg)
		}
	}
	return nil
}
```

- [ ] **Step 4: Run and confirm all parity tests pass**

Run: `cd go && go test -run TestParity_EventName -v ./... && go test -run TestParity_ValidateEventName -v ./... && go test -run TestParity_Event_ -v ./...`
Expected: PASS.

- [ ] **Step 5: Run the whole Go suite**

Run: `cd go && go test ./... -race`
Expected: PASS. Pre-existing tests that asserted relaxed-mode count rejection encoded the old contract — update them to assert the new one and add a comment naming this plan, rather than deleting them.

- [ ] **Step 6: Commit**

```bash
git add go/internal/schemacore/schema.go go/parity_event_name_test.go
git commit -m "fix(go)!: relaxed event names accept 1+ segments

BREAKING: EventName and ValidateEventName enforced the 3-5 segment count in
relaxed mode, where Python, TypeScript and Rust accept any non-empty segment
list. Go now matches the shared contract. Set strict schema to restore count
enforcement. Event() is unchanged."
```

---

### Task 8: C# — relaxed mode, and `ValidateEventName` honours strict mode

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Schema.cs:62-93`
- Create: `csharp/tests/Provide.Telemetry.Tests/ParityEventNameTests.cs`

**Interfaces:**
- Consumes: `Schema.GetStrictSchema()` (`csharp/src/Provide.Telemetry/Schema.cs:21-24`), `SegmentPattern` (`:12`).
- Produces: `Schema.EventName(params string[])`, `Schema.ValidateEventName(string)` — same signatures, new behavior. `Schema.Event` is not touched.

This task fixes **two** defects: the count rule (shared with Go) and `ValidateEventName` never reading `GetStrictSchema()`, which is C#-only.

- [ ] **Step 1: Write the failing tests**

```csharp
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using Provide.Telemetry;
using Xunit;

namespace Provide.Telemetry.Tests;

public sealed class ParityEventNameTests : IDisposable
{
    public ParityEventNameTests() => Schema.SetStrictSchema(false);
    public void Dispose() => Schema.SetStrictSchema(false);

    [Fact]
    public void EventName_RelaxedSingleSegment_Ok()
        => Assert.Equal("startup", Schema.EventName("startup"));

    [Fact]
    public void EventName_RelaxedTwoSegments_Ok()
        => Assert.Equal("app.ready", Schema.EventName("app", "ready"));

    [Fact]
    public void EventName_RelaxedSixSegments_Ok()
        => Assert.Equal("a.b.c.d.e.f", Schema.EventName("a", "b", "c", "d", "e", "f"));

    [Fact]
    public void EventName_RelaxedGrammarNotEnforced_Ok()
        => Assert.Equal("User.Login-OK", Schema.EventName("User", "Login-OK"));

    [Fact]
    public void EventName_RelaxedZeroSegments_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.EventName());

    [Fact]
    public void EventName_RelaxedEmptySegment_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.EventName("user", "", "ok"));

    [Fact]
    public void EventName_StrictThreeSegments_Ok()
    {
        Schema.SetStrictSchema(true);
        Assert.Equal("user.login.ok", Schema.EventName("user", "login", "ok"));
    }

    [Fact]
    public void EventName_StrictFiveSegments_Ok()
    {
        Schema.SetStrictSchema(true);
        Assert.Equal("a.b.c.d.e", Schema.EventName("a", "b", "c", "d", "e"));
    }

    [Fact]
    public void EventName_StrictTwoSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName("too", "few"));
    }

    [Fact]
    public void EventName_StrictSixSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName("a", "b", "c", "d", "e", "f"));
    }

    [Fact]
    public void EventName_StrictGrammarEnforced_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName("user", "Login", "ok"));
    }

    [Fact]
    public void EventName_StrictZeroSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.EventName());
    }

    [Fact]
    public void ValidateEventName_RelaxedSingleSegment_Ok()
        => Schema.ValidateEventName("startup");

    [Fact]
    public void ValidateEventName_RelaxedEmptyString_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName(""));

    [Fact]
    public void ValidateEventName_RelaxedInteriorEmptySegment_Throws()
        => Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName("a..b"));

    // The C#-only defect: ValidateEventName applied the segment regex on every
    // call, never reading GetStrictSchema(), so relaxed mode was strict here and
    // relaxed everywhere else.
    [Fact]
    public void ValidateEventName_RelaxedGrammarNotEnforced_Ok()
        => Schema.ValidateEventName("User.Login-OK");

    [Fact]
    public void ValidateEventName_StrictGrammarEnforced_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName("user.Login.ok"));
    }

    [Fact]
    public void ValidateEventName_StrictTwoSegments_Throws()
    {
        Schema.SetStrictSchema(true);
        Assert.Throws<EventSchemaError>(() => Schema.ValidateEventName("too.few"));
    }

    // Event() is out of scope and must not move.
    [Fact]
    public void Event_CountRuleUnchangedByRelaxedMode_Throws()
    {
        Assert.Throws<EventSchemaError>(() => Schema.Event("only", "two"));
        Assert.Throws<EventSchemaError>(() => Schema.Event("a", "b", "c", "d", "e"));
    }
}
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd csharp && dotnet test --filter FullyQualifiedName~ParityEventNameTests`
Expected: FAIL on the six relaxed-acceptance tests plus `ValidateEventName_RelaxedGrammarNotEnforced_Ok`.

- [ ] **Step 3: Implement the shared validator**

In `csharp/src/Provide.Telemetry/Schema.cs`, replace both `EventName` and `ValidateEventName` with:

```csharp
    /// <summary>
    /// Validates event-name segments under the shared five-language contract.
    /// Relaxed (default) accepts one or more non-empty segments and enforces no
    /// grammar; strict accepts 3-5 segments each matching the segment pattern.
    /// Zero segments and empty segments fail in both modes.
    /// </summary>
    private static void ValidateSegments(string[] segments)
    {
        if (segments.Length == 0)
        {
            throw new EventSchemaError("event name requires at least 1 segment, got 0");
        }
        foreach (var seg in segments)
        {
            if (seg.Length == 0)
            {
                throw new EventSchemaError("event name segments must be non-empty");
            }
        }
        if (!GetStrictSchema())
        {
            return;
        }
        if (segments.Length is < 3 or > 5)
        {
            throw new EventSchemaError($"event name requires 3-5 segments, got {segments.Length}");
        }
        foreach (var seg in segments)
        {
            if (!SegmentPattern.IsMatch(seg))
            {
                throw new EventSchemaError($"invalid event segment: {seg}");
            }
        }
    }

    public static string EventName(params string[] segments)
    {
        ValidateSegments(segments);
        return string.Join(".", segments);
    }

    public static void ValidateEventName(string message)
    {
        // Splitting "" on '.' yields one empty segment, never zero, so the
        // empty-segment rule is what rejects an empty name here.
        ValidateSegments(message.Split('.'));
    }
```

- [ ] **Step 4: Run and confirm the tests pass**

Run: `cd csharp && dotnet test --filter FullyQualifiedName~ParityEventNameTests`
Expected: PASS.

- [ ] **Step 5: Run the whole C# suite**

Run: `cd csharp && dotnet test`
Expected: PASS. Existing tests asserting the old unconditional grammar check in `ValidateEventName` encoded the defect — update them and comment why.

- [ ] **Step 6: Commit**

```bash
git add csharp/src/Provide.Telemetry/Schema.cs csharp/tests/Provide.Telemetry.Tests/ParityEventNameTests.cs
git commit -m "fix(csharp)!: relaxed event names, and ValidateEventName reads strict mode

BREAKING: EventName enforced the 3-5 count in relaxed mode, unlike Python,
TypeScript and Rust. Separately, ValidateEventName applied the segment grammar
on every call without ever reading GetStrictSchema, so one C# entry point was
strict while its sibling was not. Both now share one validator."
```

---

### Task 9: Python, TypeScript, Rust — prove the contract, change nothing

**Files:**
- Create: `tests/parity/test_event_name_contract.py`
- Create: `typescript/tests/parity-event-name.test.ts`
- Create: `rust/tests/parity_event_name_test.rs`

**Interfaces:**
- Consumes: `provide.telemetry.schema.events.event_name` / `validate_event_name`; the TypeScript and Rust equivalents (read their public exports before writing — do not guess the names).
- Produces: per-case test IDs consumed by Task 10.

These three languages already implement the contract
(`src/provide/telemetry/schema/events.py:110-126`). The tests are not a
formality: without them the fixture-ID gate has no per-case evidence for these
languages, and a future refactor could regress them silently.

- [ ] **Step 1: Write the Python tests**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""event_name contract parity — one test per spec/behavioral_fixtures.yaml case."""

from __future__ import annotations

import pytest

from provide.telemetry.exceptions import TelemetryError
from provide.telemetry.schema.events import event, event_name, validate_event_name


def test_parity_event_name_relaxed_single_segment_ok() -> None:
    assert event_name("startup") == "startup"


def test_parity_event_name_relaxed_two_segments_ok() -> None:
    assert event_name("app", "ready") == "app.ready"


def test_parity_event_name_relaxed_six_segments_ok() -> None:
    assert event_name("a", "b", "c", "d", "e", "f") == "a.b.c.d.e.f"


def test_parity_event_name_relaxed_grammar_not_enforced() -> None:
    assert event_name("User", "Login-OK") == "User.Login-OK"


def test_parity_event_name_relaxed_zero_segments_error() -> None:
    with pytest.raises(TelemetryError):
        event_name()


def test_parity_event_name_relaxed_empty_segment_error() -> None:
    with pytest.raises(TelemetryError):
        event_name("user", "", "ok")


def test_parity_event_name_strict_three_segments_ok(strict_schema: None) -> None:
    assert event_name("user", "login", "ok") == "user.login.ok"


def test_parity_event_name_strict_five_segments_ok(strict_schema: None) -> None:
    assert event_name("a", "b", "c", "d", "e") == "a.b.c.d.e"


def test_parity_event_name_strict_two_segments_error(strict_schema: None) -> None:
    with pytest.raises(TelemetryError):
        event_name("too", "few")


def test_parity_event_name_strict_six_segments_error(strict_schema: None) -> None:
    with pytest.raises(TelemetryError):
        event_name("a", "b", "c", "d", "e", "f")


def test_parity_event_name_strict_grammar_enforced(strict_schema: None) -> None:
    with pytest.raises(TelemetryError):
        event_name("user", "Login", "ok")


def test_parity_event_name_strict_zero_segments_error(strict_schema: None) -> None:
    with pytest.raises(TelemetryError):
        event_name()


def test_parity_validate_event_name_relaxed_single_segment_ok() -> None:
    validate_event_name("startup", strict_event_name=False)


def test_parity_validate_event_name_relaxed_empty_string_error() -> None:
    with pytest.raises(TelemetryError):
        validate_event_name("", strict_event_name=False)


def test_parity_validate_event_name_relaxed_interior_empty_segment_error() -> None:
    with pytest.raises(TelemetryError):
        validate_event_name("a..b", strict_event_name=False)


def test_parity_validate_event_name_relaxed_grammar_not_enforced() -> None:
    validate_event_name("User.Login-OK", strict_event_name=False)


def test_parity_validate_event_name_strict_grammar_enforced() -> None:
    with pytest.raises(TelemetryError):
        validate_event_name("user.Login.ok", strict_event_name=True)


def test_parity_validate_event_name_strict_two_segments_error() -> None:
    with pytest.raises(TelemetryError):
        validate_event_name("too.few", strict_event_name=True)


def test_parity_event_count_rule_unchanged_by_relaxed_mode() -> None:
    with pytest.raises(TelemetryError):
        event("only", "two")
    with pytest.raises(TelemetryError):
        event("a", "b", "c", "d", "e")
```

`validate_event_name` takes `strict_event_name` as a parameter
(`src/provide/telemetry/schema/events.py:129`), so it needs no fixture. The
`strict_schema` fixture toggles the module-level strict flag `event_name` reads
— check `tests/conftest.py` for an existing fixture with that job and reuse it;
add one only if none exists, and reset the flag in its teardown.

- [ ] **Step 2: Run the Python tests**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/parity/test_event_name_contract.py`
Expected: PASS with no source change. If any test fails, Python does **not** already implement the contract — stop, and report which case diverges before changing anything.

- [ ] **Step 3: Write the TypeScript tests**

Mirror the Python cases one-for-one in `typescript/tests/parity-event-name.test.ts`, using `describe('parity: event_name_contract', ...)` and one `it(...)` per fixture case whose name is the fixture `id`. Read `typescript/src/schema.ts` (or wherever `eventName` is exported from `typescript/src/index.ts`) for the exact export names and the strict-mode toggle before writing. Do not add exports.

- [ ] **Step 4: Run the TypeScript tests**

Run: `cd typescript && npx vitest run tests/parity-event-name.test.ts`
Expected: PASS with no source change.

- [ ] **Step 5: Write the Rust tests**

Mirror the same cases in `rust/tests/parity_event_name_test.rs`, one `#[test] fn` per fixture case named after the fixture `id` with a `parity_` prefix. Read `rust/src/schema.rs` for the exact function names and the strict-mode toggle before writing.

- [ ] **Step 6: Run the Rust tests**

Run: `cd rust && cargo test --test parity_event_name_test`
Expected: PASS with no source change.

- [ ] **Step 7: Commit**

```bash
git add tests/parity/test_event_name_contract.py typescript/tests/parity-event-name.test.ts rust/tests/parity_event_name_test.rs
git commit -m "test: per-case event_name contract coverage for python, typescript, rust"
```

---

### Task 10: Register the test IDs, run every gate, document the break

**Files:**
- Modify: `spec/fixture_test_ids.yaml`
- Modify: `CHANGELOG.md`
- Modify: `go/README.md`, `csharp/README.md`

**Interfaces:**
- Consumes: every test name created in Tasks 7–9, and the 18 fixture IDs from Task 5.
- Produces: a green `spec/check_fixture_test_ids.py`.

- [ ] **Step 1: Register per-case IDs**

Add to `spec/fixture_test_ids.yaml` under `fixture_test_ids:`. **The list order must match the fixture case order in `spec/behavioral_fixtures.yaml`**, and each list must hold exactly 18 entries — the gate from Task 6 enforces the count, not the order, so getting the order right is on you.

```yaml
  event_name_contract:
    python:
      - test_parity_event_name_relaxed_single_segment_ok
      - test_parity_event_name_relaxed_two_segments_ok
      - test_parity_event_name_relaxed_six_segments_ok
      - test_parity_event_name_relaxed_grammar_not_enforced
      - test_parity_event_name_relaxed_zero_segments_error
      - test_parity_event_name_relaxed_empty_segment_error
      - test_parity_event_name_strict_three_segments_ok
      - test_parity_event_name_strict_five_segments_ok
      - test_parity_event_name_strict_two_segments_error
      - test_parity_event_name_strict_six_segments_error
      - test_parity_event_name_strict_grammar_enforced
      - test_parity_event_name_strict_zero_segments_error
      - test_parity_validate_event_name_relaxed_single_segment_ok
      - test_parity_validate_event_name_relaxed_empty_string_error
      - test_parity_validate_event_name_relaxed_interior_empty_segment_error
      - test_parity_validate_event_name_relaxed_grammar_not_enforced
      - test_parity_validate_event_name_strict_grammar_enforced
      - test_parity_validate_event_name_strict_two_segments_error
    typescript: []   # fill with the 18 `it(...)` names, in fixture order
    go:
      - TestParity_EventName_RelaxedSingleSegmentOK
      - TestParity_EventName_RelaxedTwoSegmentsOK
      - TestParity_EventName_RelaxedSixSegmentsOK
      - TestParity_EventName_RelaxedGrammarNotEnforced
      - TestParity_EventName_RelaxedZeroSegmentsError
      - TestParity_EventName_RelaxedEmptySegmentError
      - TestParity_EventName_StrictThreeSegmentsOK
      - TestParity_EventName_StrictFiveSegmentsOK
      - TestParity_EventName_StrictTwoSegmentsError
      - TestParity_EventName_StrictSixSegmentsError
      - TestParity_EventName_StrictGrammarEnforced
      - TestParity_EventName_StrictZeroSegmentsError
      - TestParity_ValidateEventName_RelaxedSingleSegmentOK
      - TestParity_ValidateEventName_RelaxedEmptyStringError
      - TestParity_ValidateEventName_RelaxedInteriorEmptySegmentError
      - TestParity_ValidateEventName_RelaxedGrammarNotEnforced
      - TestParity_ValidateEventName_StrictGrammarEnforced
      - TestParity_ValidateEventName_StrictTwoSegmentsError
    rust: []         # fill with the 18 `fn` names, in fixture order
    csharp:
      - EventName_RelaxedSingleSegment_Ok
      - EventName_RelaxedTwoSegments_Ok
      - EventName_RelaxedSixSegments_Ok
      - EventName_RelaxedGrammarNotEnforced_Ok
      - EventName_RelaxedZeroSegments_Throws
      - EventName_RelaxedEmptySegment_Throws
      - EventName_StrictThreeSegments_Ok
      - EventName_StrictFiveSegments_Ok
      - EventName_StrictTwoSegments_Throws
      - EventName_StrictSixSegments_Throws
      - EventName_StrictGrammarEnforced_Throws
      - EventName_StrictZeroSegments_Throws
      - ValidateEventName_RelaxedSingleSegment_Ok
      - ValidateEventName_RelaxedEmptyString_Throws
      - ValidateEventName_RelaxedInteriorEmptySegment_Throws
      - ValidateEventName_RelaxedGrammarNotEnforced_Ok
      - ValidateEventName_StrictGrammarEnforced_Throws
      - ValidateEventName_StrictTwoSegments_Throws
```

The `go` discovery glob is `go/parity*_test.go` and the `csharp` glob is
`csharp/tests/**/Parity*.cs`, so `go/parity_event_name_test.go` and
`ParityEventNameTests.cs` are both already in the corpus. The Rust glob is
`rust/tests/parity*.rs` and the TypeScript glob is
`typescript/tests/parity*.test.ts` — both match the files from Task 9.

- [ ] **Step 2: Run the fixture gates**

Run:
```bash
uv run python spec/check_fixture_test_ids.py
uv run python spec/check_fixture_coverage.py --strict
```
Expected: both PASS. A `expected 18 test IDs, got N` error means a list is short — fill it, do not shrink the fixture set.

- [ ] **Step 3: Run cross-language parity and conformance**

Run:
```bash
uv run python spec/run_behavioral_parity.py
uv run python spec/validate_conformance.py
uv run python spec/check_config_parity.py
```
Expected: PASS for all five languages.

- [ ] **Step 4: Record the breaking change**

Add to `CHANGELOG.md` under the unreleased heading:

```markdown
### Changed

- **BREAKING (Go, C#):** `EventName` / `ValidateEventName` now accept one or
  more non-empty segments in relaxed mode. They previously enforced the 3–5
  segment count regardless of mode, unlike Python, TypeScript and Rust, which
  have always accepted 1+ in relaxed mode. All five languages now share one
  contract: relaxed accepts 1+ non-empty segments with no grammar check; strict
  accepts 3–5 segments each matching `^[a-z][a-z0-9_]*$`. Zero segments and
  empty segments fail in both modes. To restore count enforcement, enable strict
  schema mode. `Event()` / `event()` is unchanged and still requires exactly 3
  or 4 segments.
- **Fixed (C#):** `Schema.ValidateEventName` applied the segment grammar on
  every call without reading `GetStrictSchema()`, so it was strict while its
  sibling `EventName` was not.
```

- [ ] **Step 5: Document the rule in the affected language READMEs**

Add a short paragraph to the event-naming section of `go/README.md` and
`csharp/README.md` stating the relaxed and strict rules and that `Event()` is
unchanged. Keep it to three or four sentences — `scripts/check_docs_accuracy.py`
enforces heading structure and link validity, and plan 4 will widen it to cover
these files.

- [ ] **Step 6: Run the mutation gates**

Run these **one at a time** — concurrently they will exhaust memory:

```bash
scripts/run_gremlins_gate.sh          # Go root package (schemacore surface)
GOTOOLCHAIN=go1.26.1 scripts/run_gremlins_gate.sh   # go/otel module
cd csharp && dotnet stryker
```
Expected: zero surviving, uncovered, or timed-out mutants. A survivor in the new
relaxed/strict branch means a fixture case is missing — add the case to
`spec/behavioral_fixtures.yaml` and to all five languages, not just a local test.

- [ ] **Step 7: Run the repository gates**

```bash
uv run python scripts/check_max_loc.py --max-lines 777
uv run python scripts/check_spdx_headers.py
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests
cd go && go test ./... -race && cd otel && go test ./... -race
cd csharp && dotnet test
git status --short
```
Expected: all pass; `git status --short` empty after the commit below.

- [ ] **Step 8: Commit**

```bash
git add spec/fixture_test_ids.yaml CHANGELOG.md go/README.md csharp/README.md
git commit -m "docs: record the breaking event_name contract change

Registers per-case fixture evidence for all five languages and documents the
relaxed-mode loosening in Go and C#."
```

- [ ] **Step 9: Update the umbrella checklist**

Tick recommendations 1 and 4 in
`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md`
and paste the observed command output into their evidence blocks. Do not tick
anything whose evidence block is still empty.
