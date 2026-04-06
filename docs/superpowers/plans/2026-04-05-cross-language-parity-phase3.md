# Cross-Language Parity Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align health snapshot structure (25 canonical fields) and PII depth handling (default 8, env var configurable) across Go, TypeScript, and Python.

**Architecture:** Two independent workstreams: (A) health snapshot canonical alignment — rewrite Go struct, split TypeScript aggregates to per-signal, trim Python non-canonical fields; (B) PII depth — add maxDepth to TypeScript, change Go default from 32→8, add PROVIDE_LOG_PII_MAX_DEPTH env var to all 3.

**Tech Stack:** Go 1.25 (sync, slog), TypeScript (Vitest), Python (pytest, dataclasses), YAML behavioral fixtures.

**Spec:** `docs/superpowers/specs/2026-04-05-cross-language-parity-phase3-design.md`

**Task ordering:** Tasks 1-3 (health) should be done in order (Go first since it's the biggest rewrite, then TS, then Python). Tasks 4-6 (PII depth) are independent of each other and of tasks 1-3.

---

## Task 1: Rewrite Go HealthSnapshot to canonical 25-field layout

**Files:**
- Modify: `go/health.go`
- Modify: `go/health_test.go`
- Modify: all Go files that call health increment functions (search for `_inc`, `_addExportLatency`, `_setLastError`)

- [ ] **Step 1: Write parity test for canonical health fields**

Add to `go/parity_health_test.go` (new file):

```go
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "testing"

func TestParity_HealthSnapshot_Has25CanonicalFields(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	snap := GetHealthSnapshot()

	// Per-signal: 8 fields × 3 signals = 24
	// Logs
	_ = snap.LogsEmitted
	_ = snap.LogsDropped
	_ = snap.LogsExportFailures
	_ = snap.LogsRetries
	_ = snap.LogsExportLatencyMs
	_ = snap.LogsAsyncBlockingRisk
	_ = snap.LogsCircuitState
	_ = snap.LogsCircuitOpenCount

	// Traces
	_ = snap.TracesEmitted
	_ = snap.TracesDropped
	_ = snap.TracesExportFailures
	_ = snap.TracesRetries
	_ = snap.TracesExportLatencyMs
	_ = snap.TracesAsyncBlockingRisk
	_ = snap.TracesCircuitState
	_ = snap.TracesCircuitOpenCount

	// Metrics
	_ = snap.MetricsEmitted
	_ = snap.MetricsDropped
	_ = snap.MetricsExportFailures
	_ = snap.MetricsRetries
	_ = snap.MetricsExportLatencyMs
	_ = snap.MetricsAsyncBlockingRisk
	_ = snap.MetricsCircuitState
	_ = snap.MetricsCircuitOpenCount

	// Global
	_ = snap.SetupError
}

func TestParity_HealthSnapshot_CircuitStateDefault(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	snap := GetHealthSnapshot()
	for _, state := range []string{snap.LogsCircuitState, snap.TracesCircuitState, snap.MetricsCircuitState} {
		if state != "closed" {
			t.Errorf("expected default circuit state 'closed', got %q", state)
		}
	}
}

func TestParity_HealthSnapshot_ExportLatencyIsLatest(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_recordExportLatencyForSignal("logs", 100.0)
	_recordExportLatencyForSignal("logs", 200.0)
	snap := GetHealthSnapshot()
	if snap.LogsExportLatencyMs != 200.0 {
		t.Errorf("expected latest latency 200.0, got %f", snap.LogsExportLatencyMs)
	}
}
```

- [ ] **Step 2: Run test to verify it fails (struct fields don't exist yet)**

Run: `cd go && go test -run TestParity_HealthSnapshot -v -count=1`
Expected: Compilation error — fields like `LogsExportFailures`, `LogsCircuitState` don't exist.

- [ ] **Step 3: Rewrite HealthSnapshot struct**

Replace the entire `HealthSnapshot` struct in `go/health.go` with:

```go
// HealthSnapshot holds point-in-time counters for all telemetry signals.
// This is the canonical 25-field layout shared across Go, TypeScript, and Python.
type HealthSnapshot struct {
	// Logs (8 fields)
	LogsEmitted           int64
	LogsDropped           int64
	LogsExportFailures    int64
	LogsRetries           int64
	LogsExportLatencyMs   float64
	LogsAsyncBlockingRisk int64
	LogsCircuitState      string
	LogsCircuitOpenCount  int64

	// Traces (8 fields)
	TracesEmitted           int64
	TracesDropped           int64
	TracesExportFailures    int64
	TracesRetries           int64
	TracesExportLatencyMs   float64
	TracesAsyncBlockingRisk int64
	TracesCircuitState      string
	TracesCircuitOpenCount  int64

	// Metrics (8 fields)
	MetricsEmitted           int64
	MetricsDropped           int64
	MetricsExportFailures    int64
	MetricsRetries           int64
	MetricsExportLatencyMs   float64
	MetricsAsyncBlockingRisk int64
	MetricsCircuitState      string
	MetricsCircuitOpenCount  int64

	// Global (1 field)
	SetupError string
}
```

- [ ] **Step 4: Update module-level state and increment functions**

Replace the module-level `_health` variable and all increment functions. The key changes:

1. Add per-signal state maps instead of a single struct for mutable counters:

```go
var (
	_healthMu           sync.Mutex
	_emitted            = map[string]int64{"logs": 0, "traces": 0, "metrics": 0}
	_dropped            = map[string]int64{"logs": 0, "traces": 0, "metrics": 0}
	_exportFailures     = map[string]int64{"logs": 0, "traces": 0, "metrics": 0}
	_retries            = map[string]int64{"logs": 0, "traces": 0, "metrics": 0}
	_exportLatencyMs    = map[string]float64{"logs": 0, "traces": 0, "metrics": 0}
	_asyncBlockingRisk  = map[string]int64{"logs": 0, "traces": 0, "metrics": 0}
	_setupError         string
)
```

2. Replace 16 individual increment functions with signal-parameterized helpers:

```go
func _incEmitted(sig string)          { _healthMu.Lock(); _emitted[sig]++; _healthMu.Unlock() }
func _incDropped(sig string)          { _healthMu.Lock(); _dropped[sig]++; _healthMu.Unlock() }
func _incExportFailures(sig string)   { _healthMu.Lock(); _exportFailures[sig]++; _healthMu.Unlock() }
func _incRetries(sig string)          { _healthMu.Lock(); _retries[sig]++; _healthMu.Unlock() }
func _incAsyncBlockingRisk(sig string){ _healthMu.Lock(); _asyncBlockingRisk[sig]++; _healthMu.Unlock() }

func _recordExportLatencyForSignal(sig string, ms float64) {
	_healthMu.Lock()
	_exportLatencyMs[sig] = ms  // latest, not cumulative
	_healthMu.Unlock()
}

func _setSetupError(msg string) {
	_healthMu.Lock()
	_setupError = msg
	_healthMu.Unlock()
}
```

3. Keep backward-compatible wrappers for existing callers (temporary — remove in step 5):

```go
func _incLogsEmitted()      { _incEmitted(signalLogs) }
func _incLogsDropped()      { _incDropped(signalLogs) }
func _incSpansStarted()     { _incEmitted(signalTraces) }
func _incSpansDropped()     { _incDropped(signalTraces) }
func _incMetricsRecorded()  { _incEmitted(signalMetrics) }
func _incMetricsDropped()   { _incDropped(signalMetrics) }
// ... etc for all existing callers
```

4. Update `GetHealthSnapshot()` to assemble from per-signal maps + circuit state:

```go
func GetHealthSnapshot() HealthSnapshot {
	logsCS := GetCircuitState(signalLogs)
	tracesCS := GetCircuitState(signalTraces)
	metricsCS := GetCircuitState(signalMetrics)

	_healthMu.Lock()
	defer _healthMu.Unlock()
	return HealthSnapshot{
		LogsEmitted:           _emitted[signalLogs],
		LogsDropped:           _dropped[signalLogs],
		LogsExportFailures:    _exportFailures[signalLogs],
		LogsRetries:           _retries[signalLogs],
		LogsExportLatencyMs:   _exportLatencyMs[signalLogs],
		LogsAsyncBlockingRisk: _asyncBlockingRisk[signalLogs],
		LogsCircuitState:      logsCS.State,
		LogsCircuitOpenCount:  int64(logsCS.OpenCount),

		TracesEmitted:           _emitted[signalTraces],
		TracesDropped:           _dropped[signalTraces],
		TracesExportFailures:    _exportFailures[signalTraces],
		TracesRetries:           _retries[signalTraces],
		TracesExportLatencyMs:   _exportLatencyMs[signalTraces],
		TracesAsyncBlockingRisk: _asyncBlockingRisk[signalTraces],
		TracesCircuitState:      tracesCS.State,
		TracesCircuitOpenCount:  int64(tracesCS.OpenCount),

		MetricsEmitted:           _emitted[signalMetrics],
		MetricsDropped:           _dropped[signalMetrics],
		MetricsExportFailures:    _exportFailures[signalMetrics],
		MetricsRetries:           _retries[signalMetrics],
		MetricsExportLatencyMs:   _exportLatencyMs[signalMetrics],
		MetricsAsyncBlockingRisk: _asyncBlockingRisk[signalMetrics],
		MetricsCircuitState:      metricsCS.State,
		MetricsCircuitOpenCount:  int64(metricsCS.OpenCount),

		SetupError: _setupError,
	}
}
```

- [ ] **Step 5: Update all callers of old health functions**

Search: `cd go && grep -rn '_incLogsExport\|_incSpansExport\|_incMetricsExport\|_addExportLatency\|_setLastError\|_incCircuitBreakerTrips\|_incRetryAttempts\|_incSetupCount\|_incShutdownCount\|\.LogsExportErrors\|\.SpansExportErrors\|\.MetricsExportErrors\|\.LogsExportedOK\|\.SpansExportedOK\|\.MetricsExportedOK\|\.CircuitBreakerTrips\|\.RetryAttempts\|\.ExportLatencyMs\|\.SetupCount\|\.ShutdownCount\|\.LastError' --include='*.go'`

Update each caller:
- `_incLogsExportErrors()` → `_incExportFailures(signalLogs)`
- `_incRetryAttempts()` → `_incRetries(signal)` (pass the signal through)
- `_addExportLatency(ms)` → `_recordExportLatencyForSignal(signal, float64(ms))` (pass signal, change to latest not cumulative)
- `_setLastError(msg)` → `_setSetupError(msg)` (only for setup errors)
- `_incCircuitBreakerTrips()` → remove (circuit state derived from resilience module)
- `_incSetupCount()` / `_incShutdownCount()` → remove (not in canonical set)
- References to old struct fields in tests: `snap.LogsExportErrors` → `snap.LogsExportFailures`, etc.

- [ ] **Step 6: Update `_resetHealth()`**

```go
func _resetHealth() {
	_healthMu.Lock()
	defer _healthMu.Unlock()
	for _, sig := range []string{signalLogs, signalTraces, signalMetrics} {
		_emitted[sig] = 0
		_dropped[sig] = 0
		_exportFailures[sig] = 0
		_retries[sig] = 0
		_exportLatencyMs[sig] = 0
		_asyncBlockingRisk[sig] = 0
	}
	_setupError = ""
}
```

- [ ] **Step 7: Run full Go test suite**

Run: `cd go && go test -race -count=1 ./...`
Expected: All tests pass. Fix any remaining references to old field names.

- [ ] **Step 8: Run Go coverage gate**

Run: `cd go && go test -coverprofile=coverage.out -count=1 . && go tool cover -func=coverage.out | tail -1`
Expected: 100% coverage. Remove dead code (old compat wrappers) if all callers are updated.

- [ ] **Step 9: Commit**

```bash
git add go/health.go go/health_test.go go/parity_health_test.go
# Also add any other modified .go files
git commit -m "refactor(go): rewrite HealthSnapshot to canonical 25-field layout"
```

---

## Task 2: Align TypeScript HealthSnapshot to canonical 25 fields

**Files:**
- Modify: `typescript/src/health.ts`
- Modify: `typescript/tests/health.test.ts`
- Modify: any TS files that reference old field names (exportFailures, exportRetries, asyncBlockingRisk, exportLatencyMs)

- [ ] **Step 1: Write parity test for canonical per-signal fields**

Add to `typescript/tests/parity.test.ts`:

```typescript
describe('parity: health snapshot canonical fields', () => {
  afterEach(() => _resetHealthForTests());

  it('has all 25 canonical fields with correct defaults', () => {
    const snap = getHealthSnapshot();
    // Per-signal: 8 × 3 = 24
    expect(snap.logsEmitted).toBe(0);
    expect(snap.logsDropped).toBe(0);
    expect(snap.exportFailuresLogs).toBe(0);
    expect(snap.retriesLogs).toBe(0);
    expect(snap.exportLatencyMsLogs).toBe(0);
    expect(snap.asyncBlockingRiskLogs).toBe(0);
    expect(snap.circuitStateLogs).toBe('closed');
    expect(snap.circuitOpenCountLogs).toBe(0);

    expect(snap.tracesEmitted).toBe(0);
    expect(snap.tracesDropped).toBe(0);
    expect(snap.exportFailuresTraces).toBe(0);
    expect(snap.retriesTraces).toBe(0);
    expect(snap.exportLatencyMsTraces).toBe(0);
    expect(snap.asyncBlockingRiskTraces).toBe(0);
    expect(snap.circuitStateTraces).toBe('closed');
    expect(snap.circuitOpenCountTraces).toBe(0);

    expect(snap.metricsEmitted).toBe(0);
    expect(snap.metricsDropped).toBe(0);
    expect(snap.exportFailuresMetrics).toBe(0);
    expect(snap.retriesMetrics).toBe(0);
    expect(snap.exportLatencyMsMetrics).toBe(0);
    expect(snap.asyncBlockingRiskMetrics).toBe(0);
    expect(snap.circuitStateMetrics).toBe('closed');
    expect(snap.circuitOpenCountMetrics).toBe(0);

    // Global
    expect(snap.setupError).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd typescript && npx vitest run tests/parity.test.ts -t "canonical fields"`
Expected: FAIL — fields like `exportFailuresLogs` don't exist yet.

- [ ] **Step 3: Update HealthSnapshot interface to per-signal fields**

In `typescript/src/health.ts`, replace the `HealthSnapshot` interface:

```typescript
export interface HealthSnapshot {
  // Logs (8 fields)
  logsEmitted: number;
  logsDropped: number;
  exportFailuresLogs: number;
  retriesLogs: number;
  exportLatencyMsLogs: number;
  asyncBlockingRiskLogs: number;
  circuitStateLogs: string;
  circuitOpenCountLogs: number;

  // Traces (8 fields)
  tracesEmitted: number;
  tracesDropped: number;
  exportFailuresTraces: number;
  retriesTraces: number;
  exportLatencyMsTraces: number;
  asyncBlockingRiskTraces: number;
  circuitStateTraces: string;
  circuitOpenCountTraces: number;

  // Metrics (8 fields)
  metricsEmitted: number;
  metricsDropped: number;
  exportFailuresMetrics: number;
  retriesMetrics: number;
  exportLatencyMsMetrics: number;
  asyncBlockingRiskMetrics: number;
  circuitStateMetrics: string;
  circuitOpenCountMetrics: number;

  // Global (1 field)
  setupError: string | null;
}
```

- [ ] **Step 4: Update _state object and increment functions to per-signal**

Replace the `_state` object with per-signal fields:

```typescript
const _state = {
  logsEmitted: 0,
  logsDropped: 0,
  tracesEmitted: 0,
  tracesDropped: 0,
  metricsEmitted: 0,
  metricsDropped: 0,
  exportFailuresLogs: 0,
  exportFailuresTraces: 0,
  exportFailuresMetrics: 0,
  retriesLogs: 0,
  retriesTraces: 0,
  retriesMetrics: 0,
  exportLatencyMsLogs: 0,
  exportLatencyMsTraces: 0,
  exportLatencyMsMetrics: 0,
  asyncBlockingRiskLogs: 0,
  asyncBlockingRiskTraces: 0,
  asyncBlockingRiskMetrics: 0,
};
```

Update `NumericHealthField` type union to match the new field names.

Update `getHealthSnapshot()` to spread the new `_state` fields.

Update `_resetHealthForTests()` to reset all new fields.

- [ ] **Step 5: Update all callers of old aggregate fields**

Search: `cd typescript && grep -rn 'exportFailures\b\|exportRetries\b\|asyncBlockingRisk\b\|exportLatencyMs\b\|exemplarUnsupported\b\|lastExportError' --include='*.ts' | grep -v node_modules`

For each caller, update to the per-signal variant. For example:
- `_incrementHealth('exportFailures')` → `_incrementHealth('exportFailuresLogs')` (or traces/metrics depending on context)
- `_incrementHealth('exportRetries')` → `_incrementHealth('retriesLogs')` etc.
- `_incrementHealth('asyncBlockingRisk')` → `_incrementHealth('asyncBlockingRiskLogs')` etc.
- `_recordExportLatency(ms)` → `_recordExportLatency('logs', ms)` (add signal parameter)

Remove `exemplarUnsupported` and `lastExportError` from the canonical interface (keep internally if needed).

- [ ] **Step 6: Run full TypeScript test suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass. Fix any remaining references to old field names in tests.

- [ ] **Step 7: Commit**

```bash
git add typescript/src/health.ts typescript/tests/
git commit -m "refactor(typescript): align HealthSnapshot to canonical 25-field layout"
```

---

## Task 3: Trim Python HealthSnapshot to canonical 25 fields

**Files:**
- Modify: `src/provide/telemetry/health.py`
- Modify: `tests/health/` test files

- [ ] **Step 1: Write parity test for canonical fields**

Add to `tests/parity/test_behavioral_fixtures.py`:

```python
def test_parity_health_snapshot_has_25_canonical_fields() -> None:
    from provide.telemetry.health import get_health_snapshot, reset_health_for_tests

    reset_health_for_tests()
    snap = get_health_snapshot()
    # Per-signal: 8 × 3 = 24
    assert snap.emitted_logs == 0
    assert snap.dropped_logs == 0
    assert snap.export_failures_logs == 0
    assert snap.retries_logs == 0
    assert snap.export_latency_ms_logs == 0.0
    assert snap.async_blocking_risk_logs == 0
    assert snap.circuit_state_logs == "closed"
    assert snap.circuit_open_count_logs == 0
    # (same for traces and metrics)
    assert snap.setup_error is None
```

- [ ] **Step 2: Run test — should pass (Python already has these fields)**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity_health_snapshot_has_25" --no-cov -q`
Expected: PASS — Python already has all canonical fields plus extras.

- [ ] **Step 3: Remove non-canonical fields from HealthSnapshot**

In `src/provide/telemetry/health.py`, remove from the dataclass:
- `queue_depth_logs`, `queue_depth_traces`, `queue_depth_metrics`
- `last_error_logs`, `last_error_traces`, `last_error_metrics`
- `last_successful_export_logs`, `last_successful_export_traces`, `last_successful_export_metrics`
- `exemplar_unsupported_total`
- `circuit_cooldown_remaining_logs`, `circuit_cooldown_remaining_traces`, `circuit_cooldown_remaining_metrics`

Rename `dropped_*` → keep as-is (already matches canonical).

Also add `emitted_logs`, `emitted_traces`, `emitted_metrics` fields if not already present (Python may use `dropped` but not track emitted separately — check).

Remove the corresponding internal state dicts: `_queue_depth`, `_last_error`, `_last_success`, `_exemplar_unsupported_total`. Remove `set_queue_depth()`, `increment_exemplar_unsupported()`, `record_export_success()` from `__all__` and the module. Remove `record_export_failure`'s `_last_error` tracking.

Update `get_health_snapshot()` to not populate removed fields.

Update `reset_health_for_tests()` to not reset removed dicts.

- [ ] **Step 4: Update all Python callers of removed functions/fields**

Search: `grep -rn 'queue_depth\|last_error_\|last_successful_export\|exemplar_unsupported\|circuit_cooldown_remaining\|set_queue_depth\|increment_exemplar_unsupported\|record_export_success' src/ tests/`

Update each caller. Some callers may need to be removed (e.g., tests that only test removed fields).

- [ ] **Step 5: Run full Python test suite**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: All tests pass with 100% coverage.

- [ ] **Step 6: Commit**

```bash
git add src/provide/telemetry/health.py tests/
git commit -m "refactor(python): trim HealthSnapshot to canonical 25-field layout"
```

---

## Task 4: Add PII max depth to TypeScript

**Files:**
- Modify: `typescript/src/pii.ts`
- Modify: `typescript/src/config.ts`
- Modify: `typescript/tests/parity.test.ts`

- [ ] **Step 1: Write parity test for depth limiting**

Add to `typescript/tests/parity.test.ts`:

```typescript
describe('parity: pii depth limiting', () => {
  afterEach(() => resetPiiRulesForTests());

  it('redacts at depth < maxDepth, leaves depth >= maxDepth untouched', () => {
    const payload = {
      password: '  # pragma: allowlist secrettop',
      nested: {
        password: '  # pragma: allowlist secretmid',
        deep: {
          password: '  # pragma: allowlist secretbottom',
          tooDeep: {
            password: '  # pragma: allowlist secretshould_survive',
          },
        },
      },
    };
    const result = sanitizePayload(payload, { maxDepth: 3 });
    expect(result.password).toBe('***');
    expect(result.nested.password).toBe('***');
    expect(result.nested.deep.password).toBe('***');
    expect(result.nested.deep.tooDeep.password).toBe('should_survive');
  });

  it('defaults to maxDepth 8', () => {
    // Build 9-level deep payload
    let payload: any = { password: '  # pragma: allowlist secretlevel9' };
    for (let i = 8; i >= 0; i--) {
      payload = { [`level${i}`]: payload, password: `level${i}` };  // pragma: allowlist secret
    }
    const result = sanitizePayload(payload);
    // Depth 0-7 redacted, depth 8+ untouched
    expect(result.password).toBe('***');
    let node = result;
    for (let i = 0; i < 8; i++) {
      node = node[`level${i}`];
    }
    // At depth 8, the password should survive
    expect(node.password).toBe('level9');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd typescript && npx vitest run tests/parity.test.ts -t "pii depth"`
Expected: FAIL — `sanitizePayload` doesn't accept `maxDepth` option.

- [ ] **Step 3: Add maxDepth parameter to sanitizePayload**

In `typescript/src/pii.ts`, modify `sanitizePayload` to accept an options object or a maxDepth parameter. Add depth tracking to all recursive helpers (`_redactSecrets`, `_applyRuleFull`). At depth >= maxDepth, return the value unchanged.

The signature change: `sanitizePayload(payload: Record<string, unknown>, options?: { maxDepth?: number })`. Default maxDepth = 8.

- [ ] **Step 4: Add PROVIDE_LOG_PII_MAX_DEPTH to config**

In `typescript/src/config.ts`:
- Add `piiMaxDepth: number` to `TelemetryConfig` interface (default 8)
- Add `piiMaxDepth: envNonNegativeInt('PROVIDE_LOG_PII_MAX_DEPTH', DEFAULTS.piiMaxDepth)` to `fromEnv()`
- Wire through to `sanitizePayload` calls in the logger/middleware

- [ ] **Step 5: Run full TypeScript test suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add typescript/src/pii.ts typescript/src/config.ts typescript/tests/
git commit -m "feat(typescript): add pii max depth parameter, default 8, env var configurable"
```

---

## Task 5: Change Go PII default depth from 32 to 8

**Files:**
- Modify: `go/pii.go` (change `_piiDefaultMax`)
- Modify: `go/config.go` (add PROVIDE_LOG_PII_MAX_DEPTH env var)
- Modify: `go/parity_pii_test.go`

- [ ] **Step 1: Write parity test for depth=8 default**

Add to `go/parity_pii_test.go`:

```go
func TestParity_PIIDepth_DefaultIs8(t *testing.T) {
	resetPII(t)
	// Build 9-level deep payload with password at each level
	payload := map[string]any{
		"password":  # pragma: allowlist secret "level0",
		"nested": map[string]any{
			"password":  # pragma: allowlist secret "level1",
			"nested": map[string]any{
				"password":  # pragma: allowlist secret "level2",
				"nested": map[string]any{
					"password":  # pragma: allowlist secret "level3",
					"nested": map[string]any{
						"password":  # pragma: allowlist secret "level4",
						"nested": map[string]any{
							"password":  # pragma: allowlist secret "level5",
							"nested": map[string]any{
								"password":  # pragma: allowlist secret "level6",
								"nested": map[string]any{
									"password":  # pragma: allowlist secret "level7",
									"nested": map[string]any{
										"password":  # pragma: allowlist secret "level8_should_survive",
									},
								},
							},
						},
					},
				},
			},
		},
	}
	result := SanitizePayload(payload, true, 0) // 0 = use default
	// Depths 0-7 redacted
	if result["password"] != _piiRedacted {
		t.Errorf("depth 0: expected redacted, got %v", result["password"])
	}
	// Navigate to depth 8
	node := result
	for i := 0; i < 8; i++ {
		nested, ok := node["nested"].(map[string]any)
		if !ok {
			t.Fatalf("depth %d: expected nested map", i+1)
		}
		node = nested
	}
	// Depth 8 should survive (beyond max_depth=8)
	if node["password"] == _piiRedacted {
		t.Error("depth 8: expected NOT redacted with default max_depth=8")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run TestParity_PIIDepth_DefaultIs8 -v -count=1`
Expected: FAIL — current default is 32, so depth 8 is still redacted.

- [ ] **Step 3: Change default from 32 to 8**

In `go/pii.go`, change:
```go
const _piiDefaultMax = 8  // was: 32
```

Also add PROVIDE_LOG_PII_MAX_DEPTH env var parsing in `go/config.go` `DefaultTelemetryConfig()` or the config loading path.

- [ ] **Step 4: Run tests**

Run: `cd go && go test -race -count=1 ./...`
Expected: All tests pass. Some existing tests that rely on depth > 8 may need updating.

- [ ] **Step 5: Commit**

```bash
git add go/pii.go go/config.go go/parity_pii_test.go
git commit -m "fix(go): change PII default max depth from 32 to 8, add PROVIDE_LOG_PII_MAX_DEPTH env var"
```

---

## Task 6: Add PROVIDE_LOG_PII_MAX_DEPTH env var to Python

**Files:**
- Modify: `src/provide/telemetry/config.py`
- Modify: `tests/parity/test_behavioral_fixtures.py`

- [ ] **Step 1: Write parity test for env var**

Add to `tests/parity/test_behavioral_fixtures.py`:

```python
def test_parity_pii_max_depth_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_LOG_PII_MAX_DEPTH", "3")
    from provide.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.pii_max_depth == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity_pii_max_depth_env" --no-cov -q`
Expected: FAIL — `pii_max_depth` field doesn't exist on `TelemetryConfig`.

- [ ] **Step 3: Add pii_max_depth to TelemetryConfig**

In `src/provide/telemetry/config.py`:
- Add `pii_max_depth: int = 8` field to `TelemetryConfig` dataclass
- Add `pii_max_depth=_parse_env_int(os.environ.get("PROVIDE_LOG_PII_MAX_DEPTH"), 8, "PROVIDE_LOG_PII_MAX_DEPTH")` to `from_env()`
- Wire through to `sanitize_payload` calls in the logger pipeline (pass `config.pii_max_depth` as the `max_depth` argument)

- [ ] **Step 4: Run full Python test suite**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: All tests pass with 100% coverage.

- [ ] **Step 5: Commit**

```bash
git add src/provide/telemetry/config.py tests/parity/test_behavioral_fixtures.py
git commit -m "feat(python): add PROVIDE_LOG_PII_MAX_DEPTH env var support"
```

---

## Task 7: Update behavioral fixtures and API spec

**Files:**
- Modify: `spec/behavioral_fixtures.yaml`
- Modify: `spec/telemetry-api.yaml`

- [ ] **Step 1: Add health snapshot and PII depth fixtures**

Append to `spec/behavioral_fixtures.yaml`:

```yaml
health_snapshot:
  description: >
    Canonical 25-field health snapshot layout. All languages must return
    these fields with these default values after reset.
  canonical_fields:
    per_signal:
      - emitted
      - dropped
      - export_failures
      - retries
      - export_latency_ms
      - async_blocking_risk
      - circuit_state
      - circuit_open_count
    global:
      - setup_error
  defaults:
    emitted: 0
    dropped: 0
    export_failures: 0
    retries: 0
    export_latency_ms: 0.0
    async_blocking_risk: 0
    circuit_state: "closed"
    circuit_open_count: 0
    setup_error: null
  circuit_state_values: ["closed", "open", "half_open"]

pii_depth:
  description: >
    PII sanitization respects max_depth. Default 8.
    Configurable via PROVIDE_LOG_PII_MAX_DEPTH env var.
  default_max_depth: 8
  env_var: PROVIDE_LOG_PII_MAX_DEPTH
  cases:
    - description: "depth < maxDepth is redacted"
      max_depth: 3
      input_depth: 2
      expected: "redacted"
    - description: "depth >= maxDepth is untouched"
      max_depth: 3
      input_depth: 3
      expected: "untouched"
```

- [ ] **Step 2: Update telemetry-api.yaml**

Add to the `behavioral_parity` section:

```yaml
  health_snapshot_canonical:
    description: >
      Health snapshots return 25 canonical fields across all languages.
    rules:
      - 8 per-signal fields × 3 signals (logs, traces, metrics) + 1 global (setup_error)
      - circuit_state values: "closed", "open", "half_open"
      - export_latency_ms is latest per export, not cumulative

  pii_depth:
    description: >
      PII sanitization depth defaults to 8. Configurable via PROVIDE_LOG_PII_MAX_DEPTH.
    rules:
      - default max_depth is 8
      - at depth >= max_depth, return value unchanged (no redaction)
      - depth 0 is the top-level payload
      - applies to all sanitization (default keys, custom rules, secret detection)
```

- [ ] **Step 3: Commit**

```bash
git add spec/behavioral_fixtures.yaml spec/telemetry-api.yaml
git commit -m "spec: add health snapshot and PII depth behavioral fixtures"
```

---

## Task 8: Final cross-language verification

**Files:** None (verification only)

- [ ] **Step 1: Run all test suites**

```bash
uv run python scripts/run_pytest_gate.py
cd typescript && npx vitest run
cd go && go test -race -count=1 ./...
```
Expected: All pass.

- [ ] **Step 2: Verify health snapshot field count parity**

In each language, call `getHealthSnapshot()` / `get_health_snapshot()` / `GetHealthSnapshot()` and verify exactly 25 fields are returned (8 per signal × 3 + 1 global).

- [ ] **Step 3: Verify PII depth parity**

In each language, sanitize a 10-level nested payload with default depth (8) and verify depths 0-7 are redacted, depth 8+ is untouched.
