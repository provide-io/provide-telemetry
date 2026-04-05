# Cross-Language Parity Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 additional cross-language behavioral divergences (OTLP header `+` parsing, Go backpressure 0=unlimited, Go cardinality clamping, sampling signal validation, Go EventName strict mode) so the same input produces the same output in all three languages.

**Architecture:** Five independent fixes, each implemented via TDD. Behavioral fixture test vectors were already added in the spec commit. Each task updates one language's implementation and its parity tests.

**Tech Stack:** Go 1.25 (slog, sync, regexp), TypeScript (Vitest), Python (pytest), YAML behavioral fixtures.

**Spec:** `docs/superpowers/specs/2026-04-04-cross-language-parity-alignment-design.md` sections 7–12.

**Depends on:** Phase 1 plan (`docs/superpowers/plans/2026-04-04-cross-language-parity-alignment.md`) does NOT need to be complete first — these tasks are independent.

**Task ordering:** Tasks 1-4 and 6-8 are fully independent. **Task 5 (Go sampling validation)** changes the signatures of `SetSamplingPolicy`, `GetSamplingPolicy`, and `ShouldSample` to return errors — this requires updating ALL existing callers in the Go codebase (tests, setup, logger, etc.). Execute Task 5 last among the Go tasks, or be prepared for a large caller-update step.

---

### Task 1: Fix Python OTLP header `+` parsing

**Files:**
- Modify: `src/provide/telemetry/config.py:412,415`
- Modify: `tests/parity/test_behavioral_fixtures.py`

- [ ] **Step 1: Update parity test to assert `+` is literal**

In `tests/parity/test_behavioral_fixtures.py`, find the existing `config_headers` parity tests. Add two new test cases:

```python
def test_parity_config_headers_plus_preserved() -> None:
    result = _parse_otlp_headers("a+b=c+d")
    assert result == {"a+b": "c+d"}


def test_parity_config_headers_percent_space() -> None:
    result = _parse_otlp_headers("a%20b=c%20d")
    assert result == {"a b": "c d"}
```

Also update the existing test that asserts `"Authorization=Bearer+token"` → `"Bearer token"` to instead assert `"Bearer+token"` (literal `+`):

```python
def test_parity_config_headers_normal_kv() -> None:
    result = _parse_otlp_headers("Authorization=Bearer+token")
    assert result == {"Authorization": "Bearer+token"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity_config_headers_plus" --no-cov -q`
Expected: FAIL — `unquote_plus` converts `+` to space.

- [ ] **Step 3: Fix `_parse_otlp_headers` to use `unquote` instead of `unquote_plus`**

In `src/provide/telemetry/config.py`, change the import and two call sites:

```python
# Change this import (near top of file):
from urllib.parse import unquote  # was: unquote_plus

# Line ~412: change unquote_plus to unquote
key = unquote(key.strip())

# Line ~415: change unquote_plus to unquote
headers[key] = unquote(raw.strip())
```

Verify `unquote_plus` is no longer imported anywhere in the file. If it was imported alongside other names, just remove `unquote_plus` from the import list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity_config_headers" --no-cov -q`
Expected: All config_headers parity tests PASS.

- [ ] **Step 5: Run full Python test suite**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: All tests pass with 100% coverage.

- [ ] **Step 6: Commit**

```bash
git add src/provide/telemetry/config.py tests/parity/test_behavioral_fixtures.py
git commit -m "fix(python): use percent-encoding for OTLP header parsing, preserve + as literal"
```

---

### Task 2: Fix TypeScript OTLP header `+` parsing

**Files:**
- Modify: `typescript/src/config.ts:487,490`
- Modify: `typescript/tests/parity.test.ts`

- [ ] **Step 1: Update parity test to assert `+` is literal**

In `typescript/tests/parity.test.ts`, find the `config_headers` describe block. Add two new test cases:

```typescript
it('plus sign preserved as literal', () => {
  expect(parseOtlpHeaders('a+b=c+d')).toEqual({ 'a+b': 'c+d' });
});

it('percent-encoded spaces decoded', () => {
  expect(parseOtlpHeaders('a%20b=c%20d')).toEqual({ 'a b': 'c d' });
});
```

Also update the existing test that asserts `"Bearer+token"` → `"Bearer token"` to instead assert `"Bearer+token"`:

```typescript
it('plus sign preserved as literal (not space)', () => {
  expect(parseOtlpHeaders('Authorization=Bearer+token')).toEqual({
    Authorization: 'Bearer+token',
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd typescript && npx vitest run tests/parity.test.ts -t "plus sign preserved"`
Expected: FAIL — `.replace(/\+/g, ' ')` converts `+` to space.

- [ ] **Step 3: Remove `.replace(/\+/g, ' ')` from `parseOtlpHeaders`**

In `typescript/src/config.ts`, lines ~487 and ~490, remove the `.replace(/\+/g, ' ')` calls:

```typescript
// Line ~487: was: const key = decodeURIComponent(rawKey.replace(/\+/g, ' '));
const key = decodeURIComponent(rawKey);

// Line ~490: was: const val = decodeURIComponent(rawVal.replace(/\+/g, ' '));
const val = decodeURIComponent(rawVal);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd typescript && npx vitest run tests/parity.test.ts -t "config_headers"`
Expected: All config_headers parity tests PASS.

- [ ] **Step 5: Run full TypeScript test suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add typescript/src/config.ts typescript/tests/parity.test.ts
git commit -m "fix(typescript): use percent-encoding for OTLP header parsing, preserve + as literal"
```

---

### Task 3: Fix Go backpressure — 0 means truly unlimited

**Files:**
- Modify: `go/backpressure.go:29-35`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Add parity test for unlimited backpressure**

In `go/parity_test.go`, add:

```go
// ── Backpressure Unlimited ──────────────────────────────────────────────────

func TestParity_Backpressure_ZeroIsUnlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 0, TracesMaxSize: 0, MetricsMaxSize: 0})
	// 100 concurrent acquires must all succeed without release.
	for i := 0; i < 100; i++ {
		if !TryAcquire(signalLogs) {
			t.Fatalf("acquire %d failed with unlimited (0) queue", i)
		}
	}
}

func TestParity_Backpressure_BoundedRejects(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	if !TryAcquire(signalLogs) {
		t.Fatal("first acquire must succeed")
	}
	if TryAcquire(signalLogs) {
		t.Fatal("second acquire must fail with queue size 1")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run TestParity_Backpressure_ZeroIsUnlimited -v -count=1`
Expected: FAIL at acquire 1 — `_buildQueue(0)` creates channel of size 1, so only one acquire succeeds.

- [ ] **Step 3: Fix `_buildQueue` to return nil for unlimited**

In `go/backpressure.go`, change `_buildQueue`:

```go
// _buildQueue returns a buffered channel of the given size, or nil for unlimited (size <= 0).
func _buildQueue(size int) chan struct{} {
	if size <= 0 {
		return nil
	}
	return make(chan struct{}, size)
}
```

The `TryAcquire` function (lines 98-128) already handles `maxSize <= 0` with an early return on line 115-117, bypassing the channel. The `Release` function (lines 131-154) already checks `maxSize <= 0 || ch == nil` on line 146. So a `nil` channel from `_buildQueue` is already safe — `TryAcquire` never reaches the `select` for unlimited queues, and `Release` no-ops.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd go && go test -run TestParity_Backpressure -v -count=1`
Expected: Both backpressure parity tests PASS.

- [ ] **Step 5: Run full Go test suite with race detector**

Run: `cd go && go test -race -count=1 ./...`
Expected: All tests pass, no races.

- [ ] **Step 6: Run Go coverage gate**

Run: `cd go && go test -coverprofile=coverage.out -count=1 ./... && go tool cover -func=coverage.out | tail -1`
Expected: 100% coverage.

- [ ] **Step 7: Commit**

```bash
git add go/backpressure.go go/parity_test.go
git commit -m "fix(go): backpressure size 0 is truly unlimited, not capacity 1"
```

---

### Task 4: Fix Go cardinality input clamping

**Files:**
- Modify: `go/cardinality.go:44-49`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Add parity tests for cardinality clamping**

In `go/parity_test.go`, add:

```go
// ── Cardinality Clamping ────────────────────────────────────────────────────

func TestParity_Cardinality_ZeroMaxValuesClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 0, TTLSeconds: 10.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 1 {
		t.Fatalf("expected MaxValues clamped to 1, got %d", got.MaxValues)
	}
	if got.TTLSeconds != 10.0 {
		t.Fatalf("expected TTLSeconds 10.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_NegativeMaxValuesClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: -5, TTLSeconds: 10.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 1 {
		t.Fatalf("expected MaxValues clamped to 1, got %d", got.MaxValues)
	}
}

func TestParity_Cardinality_ZeroTTLClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 10, TTLSeconds: 0.0})
	got := GetCardinalityLimit("k")
	if got.TTLSeconds != 1.0 {
		t.Fatalf("expected TTLSeconds clamped to 1.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_NegativeTTLClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 10, TTLSeconds: -3.0})
	got := GetCardinalityLimit("k")
	if got.TTLSeconds != 1.0 {
		t.Fatalf("expected TTLSeconds clamped to 1.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_ValidValuesUnchanged(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 50, TTLSeconds: 300.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 50 {
		t.Fatalf("expected MaxValues 50, got %d", got.MaxValues)
	}
	if got.TTLSeconds != 300.0 {
		t.Fatalf("expected TTLSeconds 300.0, got %f", got.TTLSeconds)
	}
}
```

- [ ] **Step 2: Run tests to verify clamping tests fail**

Run: `cd go && go test -run TestParity_Cardinality_ZeroMaxValues -v -count=1`
Expected: FAIL — `MaxValues` stored as 0, not clamped to 1.

- [ ] **Step 3: Add clamping to `SetCardinalityLimit`**

In `go/cardinality.go`, modify `SetCardinalityLimit`:

```go
// SetCardinalityLimit configures the max-values and TTL for a specific attribute key.
// Inputs are clamped: MaxValues to min 1, TTLSeconds to min 1.0.
func SetCardinalityLimit(key string, limit CardinalityLimit) {
	_cardinalityMu.Lock()
	defer _cardinalityMu.Unlock()
	limit.MaxValues = max(1, limit.MaxValues)
	limit.TTLSeconds = max(1.0, limit.TTLSeconds)
	_cardinalityLimits[key] = limit
	// Evict any existing cache so it is rebuilt with the new limit.
	delete(_cardinalityCaches, key)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd go && go test -run TestParity_Cardinality -v -count=1`
Expected: All 5 cardinality clamping tests PASS.

- [ ] **Step 5: Run full Go test suite with race detector**

Run: `cd go && go test -race -count=1 ./...`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add go/cardinality.go go/parity_test.go
git commit -m "fix(go): clamp cardinality limit inputs to min 1/1.0, matching Python/TypeScript"
```

---

### Task 5: Add sampling signal validation to Go

**Files:**
- Modify: `go/sampling.go:28-44`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Add parity tests for signal validation**

In `go/parity_test.go`, add:

```go
// ── Sampling Signal Validation ──────────────────────────────────────────────

func TestParity_Sampling_InvalidSignalErrors(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	invalidSignals := []string{"log", "trace", "metric", "events", ""}
	for _, sig := range invalidSignals {
		t.Run(sig, func(t *testing.T) {
			_, err := SetSamplingPolicy(sig, SamplingPolicy{DefaultRate: 1.0})
			if err == nil {
				t.Fatalf("SetSamplingPolicy(%q) should return error", sig)
			}
		})
	}
}

func TestParity_Sampling_ValidSignalsAccepted(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	validSignals := []string{"logs", "traces", "metrics"}
	for _, sig := range validSignals {
		t.Run(sig, func(t *testing.T) {
			_, err := SetSamplingPolicy(sig, SamplingPolicy{DefaultRate: 1.0})
			if err != nil {
				t.Fatalf("SetSamplingPolicy(%q) unexpected error: %v", sig, err)
			}
		})
	}
}

func TestParity_ShouldSample_InvalidSignalErrors(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	_, err := ShouldSample("invalid", "key")
	if err == nil {
		t.Fatal("ShouldSample with invalid signal must return error")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd go && go test -run TestParity_Sampling_InvalidSignal -v -count=1`
Expected: FAIL — compilation error because `SetSamplingPolicy` doesn't return error yet.

- [ ] **Step 3: Add signal validation to Go sampling functions**

In `go/sampling.go`, add a validation helper and update all three public functions. Note: changing `SetSamplingPolicy`, `GetSamplingPolicy`, and `ShouldSample` signatures to return errors is a **breaking API change**. All callers in the codebase and tests must be updated.

Add the validation set and helper after the signal constants:

```go
// _validSignals is the set of allowed signal names.
var _validSignals = map[string]struct{}{
	signalLogs:    {},
	signalTraces:  {},
	signalMetrics: {},
}

// _validateSignal returns a ConfigurationError if signal is not in the valid set.
func _validateSignal(signal string) error {
	if _, ok := _validSignals[signal]; !ok {
		return NewConfigurationError(
			fmt.Sprintf("unknown signal %q, expected one of [logs, metrics, traces]", signal),
		)
	}
	return nil
}
```

Add `"fmt"` to the import block.

Update `SetSamplingPolicy` to return error:

```go
// SetSamplingPolicy registers a sampling policy for a signal.
// Returns a ConfigurationError for unknown signal names.
func SetSamplingPolicy(signal string, policy SamplingPolicy) (SamplingPolicy, error) {
	if err := _validateSignal(signal); err != nil {
		return SamplingPolicy{}, err
	}
	_samplingMu.Lock()
	defer _samplingMu.Unlock()
	_samplingPolicies[signal] = policy
	return policy, nil
}
```

Update `GetSamplingPolicy` to return error:

```go
// GetSamplingPolicy returns the current policy for a signal.
// Returns a ConfigurationError for unknown signal names.
func GetSamplingPolicy(signal string) (SamplingPolicy, error) {
	if err := _validateSignal(signal); err != nil {
		return SamplingPolicy{}, err
	}
	_samplingMu.RLock()
	defer _samplingMu.RUnlock()
	if policy, ok := _samplingPolicies[signal]; ok {
		return policy, nil
	}
	return SamplingPolicy{DefaultRate: 1.0}, nil
}
```

Update `ShouldSample` to return error:

```go
// ShouldSample returns true if the given key should be sampled.
// Returns a ConfigurationError for unknown signal names.
func ShouldSample(signal, key string) (bool, error) {
	policy, err := GetSamplingPolicy(signal)
	if err != nil {
		return false, err
	}

	rate := policy.DefaultRate
	if policy.Overrides != nil {
		if override, ok := policy.Overrides[key]; ok {
			rate = override
		}
	}

	var sampled bool
	switch rate {
	case 0.0:
		sampled = false
	case 1.0:
		sampled = true
	default:
		sampled = _rollBelowRate(rate)
	}

	_recordSampleDecision(signal, sampled)

	return sampled, nil
}
```

- [ ] **Step 4: Fix all callers of the changed signatures**

Search the Go codebase for all calls to `SetSamplingPolicy`, `GetSamplingPolicy`, and `ShouldSample`. Update each to handle the new error return. Common patterns:

In test files (e.g., `go/sampling_test.go`, `go/parity_test.go`):
```go
// Before:
SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.5})
// After:
if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.5}); err != nil {
    t.Fatal(err)
}

// Before:
if ShouldSample(signalLogs, "evt") {
// After:
sampled, err := ShouldSample(signalLogs, "evt")
if err != nil {
    t.Fatal(err)
}
if sampled {
```

Run: `cd go && grep -rn 'SetSamplingPolicy\|GetSamplingPolicy\|ShouldSample' --include='*.go' | grep -v '_test.go'`
to find non-test callers that also need updating (e.g., in `setup.go`, `logger.go`, etc.).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd go && go test -run TestParity_Sampling -v -count=1`
Expected: All sampling parity tests PASS (including the new signal validation tests).

- [ ] **Step 6: Run full Go test suite with race detector**

Run: `cd go && go test -race -count=1 ./...`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add go/sampling.go go/parity_test.go go/sampling_test.go
# Also add any other .go files that were updated for signature changes
git commit -m "feat(go): add sampling signal validation, reject unknown signal names"
```

---

### Task 6: Add sampling signal validation to TypeScript

**Files:**
- Modify: `typescript/src/sampling.ts`
- Modify: `typescript/tests/parity.test.ts`

- [ ] **Step 1: Add parity tests for signal validation**

In `typescript/tests/parity.test.ts`, add inside the `parity: sampling` describe block:

```typescript
it('rejects unknown signal name', () => {
  expect(() => shouldSample('invalid')).toThrow();
  expect(() => shouldSample('log')).toThrow();
  expect(() => shouldSample('')).toThrow();
});

it('accepts valid signal names', () => {
  setSamplingPolicy('logs', { defaultRate: 1.0 });
  expect(() => shouldSample('logs')).not.toThrow();
  expect(() => shouldSample('traces')).not.toThrow();
  expect(() => shouldSample('metrics')).not.toThrow();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd typescript && npx vitest run tests/parity.test.ts -t "rejects unknown signal"`
Expected: FAIL — `shouldSample('invalid')` doesn't throw, returns `true` (default policy).

- [ ] **Step 3: Add signal validation to TypeScript sampling**

In `typescript/src/sampling.ts`, add validation:

```typescript
import { ConfigurationError } from './exceptions';

const VALID_SIGNALS = new Set(['logs', 'traces', 'metrics']);

function _validateSignal(signal: string): void {
  if (!VALID_SIGNALS.has(signal)) {
    throw new ConfigurationError(
      `unknown signal "${signal}", expected one of [logs, metrics, traces]`,
    );
  }
}
```

Add `_validateSignal(signal)` as the first line in `setSamplingPolicy`, `getSamplingPolicy`, and `shouldSample`:

```typescript
export function setSamplingPolicy(signal: string, policy: SamplingPolicy): void {
  _validateSignal(signal);
  // ... rest unchanged
}

export function getSamplingPolicy(signal: string): SamplingPolicy {
  _validateSignal(signal);
  // ... rest unchanged
}

export function shouldSample(signal: string, key?: string): boolean {
  _validateSignal(signal);
  // ... rest unchanged
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd typescript && npx vitest run tests/parity.test.ts -t "sampling"`
Expected: All sampling parity tests PASS.

- [ ] **Step 5: Run full TypeScript test suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add typescript/src/sampling.ts typescript/tests/parity.test.ts
git commit -m "feat(typescript): add sampling signal validation, reject unknown signal names"
```

---

### Task 7: Fix Go EventName strict mode consistency

**Files:**
- Modify: `go/schema.go:103-109`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Add parity tests for lenient EventName**

In `go/parity_test.go`, add:

```go
// ── Schema Strict Mode ──────────────────────────────────────────────────────

func TestParity_EventName_LenientAcceptsUppercase(t *testing.T) {
	// Save and restore strict mode.
	origStrict := _strictSchema
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("A", "B", "C")
	if err != nil {
		t.Fatalf("lenient EventName should accept uppercase, got error: %v", err)
	}
	if name != "A.B.C" {
		t.Fatalf("expected A.B.C, got %s", name)
	}
}

func TestParity_EventName_LenientAcceptsMixedCase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = false
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("User", "Login", "Ok")
	if err != nil {
		t.Fatalf("lenient EventName should accept mixed case, got error: %v", err)
	}
	if name != "User.Login.Ok" {
		t.Fatalf("expected User.Login.Ok, got %s", name)
	}
}

func TestParity_EventName_StrictRejectsUppercase(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = origStrict })

	_, err := EventName("User", "login", "ok")
	if err == nil {
		t.Fatal("strict EventName should reject uppercase segment")
	}
}

func TestParity_EventName_StrictAcceptsValid(t *testing.T) {
	origStrict := _strictSchema
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = origStrict })

	name, err := EventName("user", "login", "ok")
	if err != nil {
		t.Fatalf("strict EventName should accept valid segments, got: %v", err)
	}
	if name != "user.login.ok" {
		t.Fatalf("expected user.login.ok, got %s", name)
	}
}
```

- [ ] **Step 2: Run tests to verify lenient tests fail**

Run: `cd go && go test -run TestParity_EventName_LenientAcceptsUppercase -v -count=1`
Expected: FAIL — `EventName` always validates, rejects uppercase `"A"`.

- [ ] **Step 3: Gate `validateSegments` behind `_strictSchema` in `EventName`**

In `go/schema.go`, modify `EventName` (lines 103-109):

```go
// EventName validates and returns a dotted event name from segments.
// Accepts 3–5 segments. Format validation is only applied when _strictSchema is true.
func EventName(segments ...string) (string, error) {
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return "", NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d",
			_minSegments, _maxSegments, n,
		))
	}
	if _strictSchema {
		for _, seg := range segments {
			if !_segmentRe.MatchString(seg) {
				return "", NewEventSchemaError(fmt.Sprintf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg,
				))
			}
		}
	}
	return strings.Join(segments, "."), nil
}
```

Note: Segment **count** validation (3–5) is always enforced. Only **format** validation (regex) is gated behind `_strictSchema`. This matches Python/TypeScript behavior. Also update `ValidateEventName` to follow the same pattern:

```go
// ValidateEventName splits a dotted event name string and validates its segments.
// Returns an *EventSchemaError if invalid, nil otherwise.
func ValidateEventName(name string) error {
	segments := strings.Split(name, ".")
	n := len(segments)
	if n < _minSegments || n > _maxSegments {
		return NewEventSchemaError(fmt.Sprintf(
			"event name must have %d–%d segments, got %d",
			_minSegments, _maxSegments, n,
		))
	}
	if _strictSchema {
		for _, seg := range segments {
			if !_segmentRe.MatchString(seg) {
				return NewEventSchemaError(fmt.Sprintf(
					"invalid event name segment %q: must match ^[a-z][a-z0-9_]*$", seg,
				))
			}
		}
	}
	return nil
}
```

The old `validateSegments` helper can be removed if no other callers remain. Check with: `cd go && grep -rn 'validateSegments' --include='*.go'`. If only `EventName` and `ValidateEventName` used it, delete the function.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd go && go test -run TestParity_EventName -v -count=1`
Expected: All 4 EventName parity tests PASS.

- [ ] **Step 5: Run full Go test suite with race detector**

Run: `cd go && go test -race -count=1 ./...`
Expected: All tests pass. Some existing schema tests may need updating if they relied on `EventName` always validating — check for failures and update assertions.

- [ ] **Step 6: Run Go coverage gate**

Run: `cd go && go test -coverprofile=coverage.out -count=1 ./... && go tool cover -func=coverage.out | tail -1`
Expected: 100% coverage. If the removed `validateSegments` function was the only thing covering certain branches, the inlined code should cover them. If coverage drops, add a test for the missing branch.

- [ ] **Step 7: Commit**

```bash
git add go/schema.go go/parity_test.go
# Also add go/schema_test.go if existing tests were updated
git commit -m "fix(go): gate EventName format validation behind strict mode, matching Python/TypeScript"
```

---

### Task 8: Add Go parity test for header `+` parsing

**Files:**
- Modify: `go/parity_test.go`

- [ ] **Step 1: Add header `+` parity tests to Go**

Go already preserves `+` as literal (no fix needed), but we need parity tests to lock this in. In `go/parity_test.go`, add:

```go
// ── Config Headers Plus Literal ─────────────────────────────────────────────

func TestParity_ConfigHeaders_PlusPreserved(t *testing.T) {
	result := ParseOTLPHeaders("a+b=c+d")
	if val, ok := result["a+b"]; !ok || val != "c+d" {
		t.Fatalf("expected {a+b: c+d}, got %v", result)
	}
}

func TestParity_ConfigHeaders_PercentSpace(t *testing.T) {
	result := ParseOTLPHeaders("a%20b=c%20d")
	if val, ok := result["a b"]; !ok || val != "c d" {
		t.Fatalf("expected {a b: c d}, got %v", result)
	}
}
```

Note: Check the exact function name for Go's header parser — it may be `ParseOTLPHeaders` or `_parseOTLPHeaders`. Search with: `cd go && grep -rn 'func.*[Pp]arse.*[Hh]eader' --include='*.go'`

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd go && go test -run TestParity_ConfigHeaders -v -count=1`
Expected: PASS — Go already uses `url.QueryUnescape` which preserves `+`.

- [ ] **Step 3: Commit**

```bash
git add go/parity_test.go
git commit -m "test(go): add parity tests for OTLP header + literal preservation"
```

---

### Task 9: Final cross-language verification

**Files:** None (verification only)

- [ ] **Step 1: Run full Python suite**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: All tests pass, 100% coverage.

- [ ] **Step 2: Run full TypeScript suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass.

- [ ] **Step 3: Run full Go suite with race detector and coverage**

Run: `cd go && go test -race -coverprofile=coverage.out -count=1 ./... && go tool cover -func=coverage.out | tail -1`
Expected: All tests pass, 100% coverage.

- [ ] **Step 4: Run lint across all languages**

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests
cd typescript && npx eslint src tests && npx prettier --check .
cd go && golangci-lint run ./...
```
Expected: All linters pass.

- [ ] **Step 5: Verify parity fixture coverage**

Count the parity test cases across all three languages and verify they match. Each language should have tests for:
- `config_headers` including `+` literal (3+ cases)
- `backpressure_unlimited` (2 cases: unlimited succeeds, bounded rejects)
- `cardinality_clamping` (5 cases: zero/negative max, zero/negative ttl, valid)
- `sampling_signal_validation` (5 invalid signals, 3 valid signals)
- `schema_strict_mode` (4 cases: lenient uppercase, lenient mixed, strict rejects, strict accepts)
