# Control-Plane Integrity & Data Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce hot/cold config boundary via `RuntimeOverrides` type across Python/Go/TypeScript, then add strippable data governance features (classification, consent, receipts, config masking) via callback hooks.

**Architecture:** Two sub-projects executed sequentially. Sub-project 1 introduces `RuntimeOverrides` type in all 3 languages, fixes mutable config leaks, and adds TS lint strictness. Sub-project 2 adds 3 hook slots to the PII engine and signal paths, then implements governance modules (classification, consent, receipts) as standalone strippable files plus inline config masking. Each governance module registers its hook on first use; if the file is deleted, hooks stay `None` and the library runs identically.

**Tech Stack:** Python 3.11+ (dataclasses, structlog, threading), Go 1.22+ (sync.Mutex, maps), TypeScript 5+ (vitest, eslint), SHA-256/HMAC from stdlib in all languages.

---

## File Map

### Sub-project 1: Control-Plane Integrity

| Action | Python | Go | TypeScript |
|--------|--------|----|------------|
| Modify | `src/provide/telemetry/runtime.py` | `go/runtime.go` | `typescript/src/runtime.ts` |
| Modify | `src/provide/telemetry/config.py` | `go/config.go` | `typescript/src/config.ts` |
| Modify | `src/provide/telemetry/__init__.py` | `go/setup.go` | `typescript/src/index.ts` |
| Modify | `spec/telemetry-api.yaml` | — | `typescript/package.json` |
| Test | `tests/runtime/test_runtime_overrides.py` | `go/runtime_test.go` | `typescript/tests/runtime.test.ts` |

### Sub-project 2: Data Governance

| Action | Python | Go | TypeScript |
|--------|--------|----|------------|
| Modify | `src/provide/telemetry/pii.py` | `go/pii.go` | `typescript/src/pii.ts` |
| Modify | `src/provide/telemetry/config.py` | `go/config.go` | `typescript/src/config.ts` |
| Modify | `src/provide/telemetry/__init__.py` | — | `typescript/src/index.ts` |
| Create | `src/provide/telemetry/classification.py` | `go/classification.go` | `typescript/src/classification.ts` |
| Create | `src/provide/telemetry/consent.py` | `go/consent.go` | `typescript/src/consent.ts` |
| Create | `src/provide/telemetry/receipts.py` | `go/receipts.go` | `typescript/src/receipts.ts` |
| Test | `tests/governance/test_classification.py` | `go/classification_test.go` | `typescript/tests/classification.test.ts` |
| Test | `tests/governance/test_consent.py` | `go/consent_test.go` | `typescript/tests/consent.test.ts` |
| Test | `tests/governance/test_receipts.py` | `go/receipts_test.go` | `typescript/tests/receipts.test.ts` |
| Test | `tests/governance/test_config_masking.py` | `go/config_masking_test.go` | `typescript/tests/config-masking.test.ts` |
| Test | `e2e/test_governance_integration.py` | `e2e/governance_integration_test.go` | `e2e/governance-integration.test.ts` |

---

## Sub-project 1: Control-Plane Integrity

### Task 1: Python — `RuntimeOverrides` type and `update_runtime_config` change

**Files:**
- Modify: `src/provide/telemetry/config.py`
- Modify: `src/provide/telemetry/runtime.py`
- Modify: `src/provide/telemetry/__init__.py`
- Create: `tests/runtime/test_runtime_overrides.py`

- [ ] **Step 1: Write failing test for RuntimeOverrides type**

```python
# tests/runtime/test_runtime_overrides.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for RuntimeOverrides type and hot/cold enforcement."""

from __future__ import annotations

import pytest

from provide.telemetry.config import RuntimeOverrides, SamplingConfig


def test_runtime_overrides_accepts_hot_fields() -> None:
    overrides = RuntimeOverrides(
        sampling=SamplingConfig(logs_rate=0.5, traces_rate=0.8, metrics_rate=0.9),
    )
    assert overrides.sampling is not None
    assert overrides.sampling.logs_rate == pytest.approx(0.5)


def test_runtime_overrides_has_no_cold_fields() -> None:
    """RuntimeOverrides must not have service_name, environment, version, tracing, or metrics."""
    assert not hasattr(RuntimeOverrides, "service_name")
    assert not hasattr(RuntimeOverrides, "environment")
    assert not hasattr(RuntimeOverrides, "version")
    # tracing and metrics are cold (provider config)
    assert "tracing" not in {f.name for f in __import__("dataclasses").fields(RuntimeOverrides)}
    assert "metrics" not in {f.name for f in __import__("dataclasses").fields(RuntimeOverrides)}


def test_runtime_overrides_all_fields_optional() -> None:
    """All fields default to None — passing nothing is valid."""
    overrides = RuntimeOverrides()
    assert overrides.sampling is None
    assert overrides.backpressure is None
    assert overrides.exporter is None
    assert overrides.security is None
    assert overrides.slo is None
    assert overrides.pii_max_depth is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_runtime_overrides"`
Expected: FAIL — `RuntimeOverrides` not defined.

- [ ] **Step 3: Implement RuntimeOverrides in config.py**

Add to `src/provide/telemetry/config.py` after the `SecurityConfig` class, before `TelemetryConfig`:

```python
@dataclass(slots=True)
class RuntimeOverrides:
    """Hot-reloadable config subset.

    Only fields that can be changed at runtime without restarting providers.
    All fields are optional (None = keep current value).
    """

    sampling: SamplingConfig | None = None
    backpressure: BackpressureConfig | None = None
    exporter: ExporterPolicyConfig | None = None
    security: SecurityConfig | None = None
    slo: SLOConfig | None = None
    pii_max_depth: int | None = None
```

Add `"RuntimeOverrides"` to the `__all__` list in `config.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_runtime_overrides"`
Expected: PASS

- [ ] **Step 5: Write failing test for update_runtime_config accepting RuntimeOverrides**

Add to `tests/runtime/test_runtime_overrides.py`:

```python
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry import health as health_mod
from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry.config import (
    RuntimeOverrides,
    SamplingConfig,
    BackpressureConfig,
    TelemetryConfig,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    with runtime_mod._lock:
        runtime_mod._active_config = None


def test_update_runtime_config_accepts_overrides() -> None:
    """update_runtime_config must accept RuntimeOverrides, not TelemetryConfig."""
    # First set up a base config
    runtime_mod.apply_runtime_config(TelemetryConfig())

    overrides = RuntimeOverrides(
        sampling=SamplingConfig(logs_rate=0.1, traces_rate=0.2, metrics_rate=0.3),
    )
    result = runtime_mod.update_runtime_config(overrides)
    assert result.sampling.logs_rate == pytest.approx(0.1)


def test_update_runtime_config_preserves_unset_fields() -> None:
    """Fields not set in RuntimeOverrides keep their current values."""
    base = TelemetryConfig(
        sampling=SamplingConfig(logs_rate=0.5),
    )
    runtime_mod.apply_runtime_config(base)

    # Only change backpressure, leave sampling alone
    overrides = RuntimeOverrides(
        backpressure=BackpressureConfig(logs_maxsize=100),
    )
    result = runtime_mod.update_runtime_config(overrides)
    assert result.sampling.logs_rate == pytest.approx(0.5)
    assert result.backpressure.logs_maxsize == 100
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_update_runtime_config_accepts"`
Expected: FAIL — `update_runtime_config` currently expects `TelemetryConfig`.

- [ ] **Step 7: Implement update_runtime_config with RuntimeOverrides**

Modify `src/provide/telemetry/runtime.py`:

```python
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig
# ... (keep existing imports)

def _apply_overrides(base: TelemetryConfig, overrides: RuntimeOverrides) -> TelemetryConfig:
    """Merge non-None override fields into a copy of base config."""
    merged = copy.deepcopy(base)
    if overrides.sampling is not None:
        merged.sampling = overrides.sampling
    if overrides.backpressure is not None:
        merged.backpressure = overrides.backpressure
    if overrides.exporter is not None:
        merged.exporter = overrides.exporter
    if overrides.security is not None:
        merged.security = overrides.security
    if overrides.slo is not None:
        merged.slo = overrides.slo
    if overrides.pii_max_depth is not None:
        merged.pii_max_depth = overrides.pii_max_depth
    return merged


def update_runtime_config(overrides: RuntimeOverrides) -> TelemetryConfig:
    """Merge overrides into the active config and re-apply hot policies.

    Returns a defensive copy of the resulting config snapshot.
    """
    with _lock:
        base = _active_config if _active_config is not None else TelemetryConfig.from_env()
    merged = _apply_overrides(base, overrides)
    apply_runtime_config(merged)
    return get_runtime_config()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_update_runtime_config"`
Expected: PASS

- [ ] **Step 9: Write failing test for reload_runtime_from_env cold-field warning**

Add to `tests/runtime/test_runtime_overrides.py`:

```python
import logging


def test_reload_runtime_from_env_warns_on_cold_change(caplog: pytest.LogCaptureFixture) -> None:
    """If env vars changed cold fields, a warning is logged."""
    import os

    base = TelemetryConfig(service_name="original-service")
    runtime_mod.apply_runtime_config(base)

    with caplog.at_level(logging.WARNING):
        os.environ["PROVIDE_TELEMETRY_SERVICE_NAME"] = "new-service"
        try:
            result = runtime_mod.reload_runtime_from_env()
        finally:
            os.environ.pop("PROVIDE_TELEMETRY_SERVICE_NAME", None)

    assert "service_name" in caplog.text or "restart" in caplog.text.lower()
    # Hot fields were still applied
    assert result is not None
```

- [ ] **Step 10: Implement reload_runtime_from_env with cold-field warning**

Modify `reload_runtime_from_env` in `src/provide/telemetry/runtime.py`:

```python
import logging

_logger = logging.getLogger(__name__)


def reload_runtime_from_env() -> TelemetryConfig:
    """Reload environment config, apply hot fields, warn on cold-field drift."""
    fresh = TelemetryConfig.from_env()
    with _lock:
        current = _active_config
    if current is not None:
        changed_cold = [k for k in _COLD_KEYS if getattr(current, k) != getattr(fresh, k)]
        if changed_cold:
            _logger.warning(
                "runtime.cold_field_drift",
                extra={"fields": changed_cold, "action": "restart required to apply"},
            )
    # Extract hot fields into overrides and apply
    overrides = RuntimeOverrides(
        sampling=fresh.sampling,
        backpressure=fresh.backpressure,
        exporter=fresh.exporter,
        security=fresh.security,
        slo=fresh.slo,
        pii_max_depth=fresh.pii_max_depth,
    )
    return update_runtime_config(overrides)
```

- [ ] **Step 11: Run all runtime tests**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "runtime"`
Expected: PASS

- [ ] **Step 12: Update __init__.py exports**

Add `RuntimeOverrides` to the lazy registry in `src/provide/telemetry/__init__.py`:

```python
# In the TYPE_CHECKING block, add:
from provide.telemetry.config import RuntimeOverrides

# In _LAZY_REGISTRY registrations, add RuntimeOverrides alongside TelemetryConfig (config is eager, so just add to __all__):
# Since config.py is eagerly imported, add RuntimeOverrides to the eager import line:
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig

# Add "RuntimeOverrides" to __all__ list
```

- [ ] **Step 13: Update existing tests that pass TelemetryConfig to update_runtime_config**

Search for all test files that call `update_runtime_config` with a `TelemetryConfig` and update them to use `RuntimeOverrides`. Check `tests/runtime/test_runtime_mutations.py` — if it passes `TelemetryConfig` to `update_runtime_config`, change it.

- [ ] **Step 14: Commit**

```bash
git add src/provide/telemetry/config.py src/provide/telemetry/runtime.py \
  src/provide/telemetry/__init__.py tests/runtime/test_runtime_overrides.py \
  tests/runtime/test_runtime_mutations.py
git commit -m "feat(python): add RuntimeOverrides type, enforce hot/cold config boundary"
```

---

### Task 2: Go — `RuntimeOverrides` type and frozen `SetupTelemetry` return

**Files:**
- Modify: `go/config.go`
- Modify: `go/runtime.go`
- Modify: `go/setup.go`
- Modify: `go/runtime_test.go`
- Modify: `go/setup_test.go`

- [ ] **Step 1: Write failing test for RuntimeOverrides type**

Add to `go/runtime_test.go`:

```go
func TestRuntimeOverridesAppliesHotFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling: &SamplingConfig{LogsRate: 0.1, TracesRate: 0.2, MetricsRate: 0.3},
	})
	if err != nil {
		t.Fatalf("UpdateRuntimeConfig failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg.Sampling.LogsRate != 0.1 {
		t.Errorf("expected LogsRate 0.1, got %f", cfg.Sampling.LogsRate)
	}
}

func TestRuntimeOverridesPreservesUnsetFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	// Set a known sampling rate
	_ = UpdateRuntimeConfig(RuntimeOverrides{
		Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: 1.0, MetricsRate: 1.0},
	})

	// Now only change backpressure
	_ = UpdateRuntimeConfig(RuntimeOverrides{
		Backpressure: &BackpressureConfig{LogsMaxSize: 100},
	})

	cfg := GetRuntimeConfig()
	if cfg.Sampling.LogsRate != 0.5 {
		t.Errorf("expected LogsRate preserved at 0.5, got %f", cfg.Sampling.LogsRate)
	}
	if cfg.Backpressure.LogsMaxSize != 100 {
		t.Errorf("expected LogsMaxSize 100, got %d", cfg.Backpressure.LogsMaxSize)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run "TestRuntimeOverrides" -v ./...`
Expected: FAIL — `RuntimeOverrides` not defined.

- [ ] **Step 3: Implement RuntimeOverrides in config.go**

Add to `go/config.go` after `SecurityConfig`:

```go
// RuntimeOverrides contains only hot-reloadable fields.
// Nil pointer fields mean "keep current value".
type RuntimeOverrides struct {
	Sampling     *SamplingConfig
	Backpressure *BackpressureConfig
	Exporter     *ExporterPolicyConfig
	Security     *SecurityConfig
	SLO          *SLOConfig
	PIIMaxDepth  *int
}
```

- [ ] **Step 4: Change UpdateRuntimeConfig signature in runtime.go**

Replace the existing `UpdateRuntimeConfig` in `go/runtime.go`:

```go
// UpdateRuntimeConfig merges non-nil override fields into the active config
// and re-applies hot policies. Returns an error if telemetry is not set up.
func UpdateRuntimeConfig(overrides RuntimeOverrides) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone || _runtimeCfg == nil {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	next := cloneTelemetryConfig(_runtimeCfg)
	if overrides.Sampling != nil {
		next.Sampling = *overrides.Sampling
	}
	if overrides.Backpressure != nil {
		next.Backpressure = *overrides.Backpressure
	}
	if overrides.Exporter != nil {
		next.Exporter = *overrides.Exporter
	}
	if overrides.Security != nil {
		next.Security = *overrides.Security
	}
	if overrides.SLO != nil {
		next.SLO = *overrides.SLO
	}
	if overrides.PIIMaxDepth != nil {
		next.Logging.PIIMaxDepth = *overrides.PIIMaxDepth
	}
	_applyRuntimePolicies(next)
	_runtimeCfg = next
	return nil
}
```

- [ ] **Step 5: Fix SetupTelemetry idempotent path to return clone**

In `go/setup.go`, change line 99 from:

```go
return _runtimeCfg, nil
```

to:

```go
return cloneTelemetryConfig(_runtimeCfg), nil
```

- [ ] **Step 6: Write test for SetupTelemetry idempotent path returning clone**

Add to `go/setup_test.go`:

```go
func TestSetupTelemetryIdempotentReturnsCopy(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	cfg2, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}

	// Mutating cfg1 must not affect cfg2
	cfg1.ServiceName = "mutated"
	if cfg2.ServiceName == "mutated" {
		t.Fatal("idempotent SetupTelemetry must return independent copies")
	}
}
```

- [ ] **Step 7: Add ReloadRuntimeFromEnv cold-field warning**

Update `ReloadRuntimeFromEnv` in `go/runtime.go`:

```go
func ReloadRuntimeFromEnv() error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	cfg, err := ConfigFromEnv()
	if err != nil {
		return err
	}

	// Warn on cold-field drift
	if _runtimeCfg != nil {
		var drifted []string
		if cfg.ServiceName != _runtimeCfg.ServiceName {
			drifted = append(drifted, "ServiceName")
		}
		if cfg.Environment != _runtimeCfg.Environment {
			drifted = append(drifted, "Environment")
		}
		if cfg.Version != _runtimeCfg.Version {
			drifted = append(drifted, "Version")
		}
		if cfg.Tracing.Enabled != _runtimeCfg.Tracing.Enabled {
			drifted = append(drifted, "Tracing.Enabled")
		}
		if cfg.Metrics.Enabled != _runtimeCfg.Metrics.Enabled {
			drifted = append(drifted, "Metrics.Enabled")
		}
		if len(drifted) > 0 {
			_logWarn("runtime.cold_field_drift", map[string]any{
				"fields": drifted,
				"action": "restart required to apply",
			})
		}
	}

	// Apply only hot fields
	_applyRuntimePolicies(cfg)
	_runtimeCfg = cfg
	return nil
}
```

- [ ] **Step 8: Update existing tests that use old UpdateRuntimeConfig signature**

Search `go/runtime_test.go` and `go/setup_test.go` for calls to `UpdateRuntimeConfig` that pass a mutator function, and update them to use the new `RuntimeOverrides` struct.

- [ ] **Step 9: Run all Go tests**

Run: `cd go && go test -race -v ./...`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add go/config.go go/runtime.go go/setup.go go/runtime_test.go go/setup_test.go
git commit -m "feat(go): add RuntimeOverrides type, freeze SetupTelemetry idempotent return"
```

---

### Task 3: TypeScript — `RuntimeOverrides`, frozen returns, lint fix

**Files:**
- Modify: `typescript/src/config.ts`
- Modify: `typescript/src/runtime.ts`
- Modify: `typescript/src/index.ts`
- Modify: `typescript/package.json`
- Modify: `typescript/tests/runtime.test.ts`

- [ ] **Step 1: Write failing test for RuntimeOverrides**

Add to `typescript/tests/runtime.test.ts`:

```typescript
import type { RuntimeOverrides } from '../src/config';

describe('RuntimeOverrides', () => {
  it('accepts only hot-reloadable fields', () => {
    const overrides: RuntimeOverrides = {
      samplingLogsRate: 0.5,
      samplingTracesRate: 0.8,
    };
    expect(overrides.samplingLogsRate).toBe(0.5);
  });

  it('all fields are optional', () => {
    const overrides: RuntimeOverrides = {};
    expect(Object.keys(overrides)).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd typescript && npx vitest run tests/runtime.test.ts`
Expected: FAIL — `RuntimeOverrides` not exported.

- [ ] **Step 3: Implement RuntimeOverrides interface in config.ts**

Add to `typescript/src/config.ts` after the `TelemetryConfig` interface:

```typescript
/**
 * Hot-reloadable config subset. Only fields that can be changed at runtime
 * without restarting providers. All fields are optional.
 */
export interface RuntimeOverrides {
  // Sampling
  samplingLogsRate?: number;
  samplingTracesRate?: number;
  samplingMetricsRate?: number;

  // Backpressure
  backpressureLogsMaxsize?: number;
  backpressureTracesMaxsize?: number;
  backpressureMetricsMaxsize?: number;

  // Exporter resilience
  exporterLogsRetries?: number;
  exporterLogsBackoffMs?: number;
  exporterLogsTimeoutMs?: number;
  exporterLogsFailOpen?: boolean;
  exporterTracesRetries?: number;
  exporterTracesBackoffMs?: number;
  exporterTracesTimeoutMs?: number;
  exporterTracesFailOpen?: boolean;
  exporterMetricsRetries?: number;
  exporterMetricsBackoffMs?: number;
  exporterMetricsTimeoutMs?: number;
  exporterMetricsFailOpen?: boolean;

  // Security
  securityMaxAttrValueLength?: number;
  securityMaxAttrCount?: number;

  // SLO
  sloEnableRedMetrics?: boolean;
  sloEnableUseMetrics?: boolean;

  // PII
  piiMaxDepth?: number;
}
```

- [ ] **Step 4: Change updateRuntimeConfig in runtime.ts**

Replace `updateRuntimeConfig` in `typescript/src/runtime.ts`:

```typescript
import { type RuntimeOverrides, type TelemetryConfig, configFromEnv, setupTelemetry } from './config';

/** Deep-freeze an object and all nested objects. */
function deepFreeze<T extends object>(obj: T): Readonly<T> {
  for (const val of Object.values(obj)) {
    if (typeof val === 'object' && val !== null && !Object.isFrozen(val)) {
      deepFreeze(val as object);
    }
  }
  return Object.freeze(obj);
}

/** Return the active runtime config as an immutable frozen copy. */
export function getRuntimeConfig(): Readonly<TelemetryConfig> {
  const cfg = _activeConfig ?? configFromEnv();
  return deepFreeze({ ...cfg });
}

/** Merge hot-reloadable overrides into the active config and re-apply policies. */
export function updateRuntimeConfig(overrides: RuntimeOverrides): void {
  const base = _activeConfig ?? configFromEnv();
  const merged: TelemetryConfig = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined) {
      (merged as Record<string, unknown>)[key] = value;
    }
  }
  _activeConfig = merged;
  setupTelemetry(_activeConfig);
}
```

- [ ] **Step 5: Write test for frozen getRuntimeConfig**

Add to `typescript/tests/runtime.test.ts`:

```typescript
describe('getRuntimeConfig frozen return', () => {
  it('returns a frozen object', () => {
    const cfg = getRuntimeConfig();
    expect(Object.isFrozen(cfg)).toBe(true);
  });

  it('mutations throw in strict mode', () => {
    const cfg = getRuntimeConfig();
    expect(() => {
      (cfg as Record<string, unknown>).serviceName = 'mutated';
    }).toThrow();
  });
});
```

- [ ] **Step 6: Add reloadRuntimeFromEnv cold-field warning**

Update `reloadRuntimeFromEnv` in `typescript/src/runtime.ts`:

```typescript
const _COLD_FIELDS: (keyof TelemetryConfig)[] = [
  'serviceName',
  'environment',
  'version',
  'otelEnabled',
  'otlpEndpoint',
  'otlpHeaders',
];

export function reloadRuntimeFromEnv(): void {
  const fresh = configFromEnv();
  if (_activeConfig) {
    const drifted = _COLD_FIELDS.filter(
      (k) => JSON.stringify(_activeConfig![k]) !== JSON.stringify(fresh[k]),
    );
    if (drifted.length > 0) {
      console.warn(
        '[provide-telemetry] runtime.cold_field_drift:',
        drifted.join(', '),
        '— restart required to apply',
      );
    }
  }
  // Apply only hot fields via overrides
  const overrides: RuntimeOverrides = {
    samplingLogsRate: fresh.samplingLogsRate,
    samplingTracesRate: fresh.samplingTracesRate,
    samplingMetricsRate: fresh.samplingMetricsRate,
    backpressureLogsMaxsize: fresh.backpressureLogsMaxsize,
    backpressureTracesMaxsize: fresh.backpressureTracesMaxsize,
    backpressureMetricsMaxsize: fresh.backpressureMetricsMaxsize,
    exporterLogsRetries: fresh.exporterLogsRetries,
    exporterLogsBackoffMs: fresh.exporterLogsBackoffMs,
    exporterLogsTimeoutMs: fresh.exporterLogsTimeoutMs,
    exporterLogsFailOpen: fresh.exporterLogsFailOpen,
    exporterTracesRetries: fresh.exporterTracesRetries,
    exporterTracesBackoffMs: fresh.exporterTracesBackoffMs,
    exporterTracesTimeoutMs: fresh.exporterTracesTimeoutMs,
    exporterTracesFailOpen: fresh.exporterTracesFailOpen,
    exporterMetricsRetries: fresh.exporterMetricsRetries,
    exporterMetricsBackoffMs: fresh.exporterMetricsBackoffMs,
    exporterMetricsTimeoutMs: fresh.exporterMetricsTimeoutMs,
    exporterMetricsFailOpen: fresh.exporterMetricsFailOpen,
    securityMaxAttrValueLength: fresh.securityMaxAttrValueLength,
    securityMaxAttrCount: fresh.securityMaxAttrCount,
    sloEnableRedMetrics: fresh.sloEnableRedMetrics,
    sloEnableUseMetrics: fresh.sloEnableUseMetrics,
    piiMaxDepth: fresh.piiMaxDepth,
  };
  updateRuntimeConfig(overrides);
}
```

- [ ] **Step 7: Fix lint gate — add --max-warnings=0**

In `typescript/package.json`, change:

```json
"lint": "eslint src tests",
```

to:

```json
"lint": "eslint src tests --max-warnings=0",
```

- [ ] **Step 8: Export RuntimeOverrides from index.ts**

Add to `typescript/src/index.ts`:

```typescript
export type { RuntimeOverrides } from './config';
```

- [ ] **Step 9: Update existing tests using old updateRuntimeConfig signature**

Search `typescript/tests/runtime.test.ts` for calls passing `Partial<TelemetryConfig>` with cold fields (like `serviceName`) and update them to pass `RuntimeOverrides` with only hot fields.

- [ ] **Step 10: Run all TypeScript tests**

Run: `cd typescript && npx vitest run`
Expected: PASS

- [ ] **Step 11: Run lint to verify --max-warnings=0 is enforced**

Run: `cd typescript && npm run lint`
Expected: PASS with zero warnings (or fail if existing warnings need fixing).

- [ ] **Step 12: Commit**

```bash
git add typescript/src/config.ts typescript/src/runtime.ts typescript/src/index.ts \
  typescript/package.json typescript/tests/runtime.test.ts
git commit -m "feat(typescript): add RuntimeOverrides type, frozen returns, strict lint gate"
```

---

### Task 4: Spec update — add RuntimeOverrides

**Files:**
- Modify: `spec/telemetry-api.yaml`

- [ ] **Step 1: Add RuntimeOverrides to spec**

Add under `types:` section in `spec/telemetry-api.yaml`:

```yaml
    - name: RuntimeOverrides
      kind: type
      required: true
      note: "Hot-reloadable config subset — sampling, backpressure, exporter, security, SLO, pii_max_depth"
```

Update `update_runtime_config` note:

```yaml
    - name: update_runtime_config
      kind: function
      required: true
      note: "Accepts RuntimeOverrides (hot fields only), not full TelemetryConfig"
```

- [ ] **Step 2: Run conformance validator**

Run: `uv run python spec/validate_conformance.py`
Expected: PASS — all three languages export `RuntimeOverrides`.

- [ ] **Step 3: Commit**

```bash
git add spec/telemetry-api.yaml
git commit -m "spec: add RuntimeOverrides type, update update_runtime_config signature"
```

---

## Sub-project 2: Data Governance

### Task 5: Hook slots in PII engine (all 3 languages)

**Files:**
- Modify: `src/provide/telemetry/pii.py`
- Modify: `go/pii.go`
- Modify: `typescript/src/pii.ts`

- [ ] **Step 1: Write failing test for classification hook slot (Python)**

Create `tests/governance/test_classification.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for PII engine hook slots."""

from __future__ import annotations

from provide.telemetry import pii as pii_mod


def test_classification_hook_defaults_to_none() -> None:
    assert pii_mod._classification_hook is None


def test_receipt_hook_defaults_to_none() -> None:
    assert pii_mod._receipt_hook is None


def test_classification_hook_called_during_sanitize() -> None:
    calls: list[tuple[str, object]] = []

    def hook(key: str, value: object) -> str | None:
        calls.append((key, value))
        return None  # no classification tag

    pii_mod._classification_hook = hook
    try:
        pii_mod.sanitize_payload({"username": "alice"}, enabled=True)
        assert len(calls) > 0
        assert any(k == "username" for k, _ in calls)
    finally:
        pii_mod._classification_hook = None


def test_receipt_hook_called_on_redaction() -> None:
    receipts: list[dict[str, object]] = []

    def hook(field_path: str, action: str, original_value: object) -> None:
        receipts.append({"path": field_path, "action": action})

    pii_mod._receipt_hook = hook
    try:
        # "password" is in default sensitive keys, so it gets redacted
        pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret  # pragma: allowlist secret
        assert len(receipts) > 0
        assert receipts[0]["path"] == "password"
        assert receipts[0]["action"] == "redact"
    finally:
        pii_mod._receipt_hook = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_classification_hook"`
Expected: FAIL — `_classification_hook` not defined.

- [ ] **Step 3: Add hook slots to Python pii.py**

Add module-level hooks after `_rules`:

```python
# Governance hooks — registered by classification.py / receipts.py if present.
# None = feature not loaded (zero overhead). Callable = active.
_classification_hook: Any = None  # (key: str, value: Any) -> str | None
_receipt_hook: Any = None  # (field_path: str, action: str, original_value: Any) -> None
```

Then modify `_apply_default_sensitive_key_redaction` to call hooks:

In the branch where `key.lower() in _DEFAULT_SENSITIVE_KEYS` and the value gets redacted:
```python
if _receipt_hook is not None:
    _receipt_hook(key, "redact", orig_value)
```

In `_apply_rule` where `_mask` is called:
```python
masked = _mask(value, rule.mode, rule.truncate_to)
if _receipt_hook is not None:
    _receipt_hook(".".join(child_path), rule.mode, value)
```

In `sanitize_payload`, before the traversal, if `_classification_hook is not None`, call it for each top-level key:
```python
if _classification_hook is not None:
    for key, value in payload.items():
        _classification_hook(key, value)
```

Also add to `reset_pii_rules_for_tests`:
```python
def reset_pii_rules_for_tests() -> None:
    global _classification_hook, _receipt_hook
    replace_pii_rules([])
    _classification_hook = None
    _receipt_hook = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_classification_hook or test_receipt_hook"`
Expected: PASS

- [ ] **Step 5: Add hook slots to Go pii.go**

Add to `go/pii.go`:

```go
// Governance hooks — set by classification.go / receipts.go if present.
var (
	_classificationHook func(key string, value any) string // returns class label or ""
	_receiptHook        func(fieldPath string, action string, originalValue any)
)

// SetClassificationHook registers a classification callback on the PII engine.
func SetClassificationHook(fn func(string, any) string) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_classificationHook = fn
}

// SetReceiptHook registers a redaction receipt callback on the PII engine.
func SetReceiptHook(fn func(string, string, any)) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_receiptHook = fn
}
```

Call `_receiptHook` in `_sanitizeValue` when a redaction occurs, and `_classificationHook` during key traversal.

- [ ] **Step 6: Add hook slots to TypeScript pii.ts**

Add to `typescript/src/pii.ts`:

```typescript
export let _classificationHook: ((key: string, value: unknown) => string | null) | null = null;
export let _receiptHook: ((fieldPath: string, action: string, originalValue: unknown) => void) | null = null;

export function setClassificationHook(fn: ((key: string, value: unknown) => string | null) | null): void {
  _classificationHook = fn;
}

export function setReceiptHook(fn: ((fieldPath: string, action: string, originalValue: unknown) => void) | null): void {
  _receiptHook = fn;
}
```

Call hooks in `sanitizePayload` and `_applyMode` similar to Python.

- [ ] **Step 7: Write Go and TS tests for hooks**

Create `go/pii_hooks_test.go` and add hook tests to `typescript/tests/pii.test.ts` following the same patterns as the Python tests.

- [ ] **Step 8: Run all tests in all 3 languages**

```bash
uv run python scripts/run_pytest_gate.py --no-cov -q
cd go && go test -race ./...
cd typescript && npx vitest run
```

Expected: PASS in all three.

- [ ] **Step 9: Commit**

```bash
git add src/provide/telemetry/pii.py go/pii.go typescript/src/pii.ts \
  tests/governance/test_classification.py go/pii_hooks_test.go typescript/tests/pii.test.ts
git commit -m "feat: add classification and receipt hook slots to PII engine (all languages)"
```

---

### Task 6: Config secret masking (all 3 languages)

**Files:**
- Modify: `src/provide/telemetry/config.py`
- Modify: `go/config.go`
- Modify: `typescript/src/config.ts`
- Create: `tests/governance/test_config_masking.py`
- Create: `go/config_masking_test.go`
- Create: `typescript/tests/config-masking.test.ts`

- [ ] **Step 1: Write failing test (Python)**

```python
# tests/governance/test_config_masking.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for config secret masking."""

from __future__ import annotations

from provide.telemetry.config import LoggingConfig, TelemetryConfig, TracingConfig


def test_repr_masks_otlp_header_values() -> None:
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"Authorization": "Bearer super-secret-token"}),
    )
    text = repr(cfg)
    assert "super-secret-token" not in text
    assert "Bear****" in text or "****" in text


def test_repr_masks_endpoint_userinfo() -> None:
    cfg = TelemetryConfig(
        tracing=TracingConfig(otlp_endpoint="https://user:p4ssw0rd@otel.example.com/v1/traces"),
    )
    text = repr(cfg)
    assert "p4ssw0rd" not in text
    assert "****" in text


def test_repr_safe_with_no_secrets() -> None:
    cfg = TelemetryConfig()
    text = repr(cfg)
    assert "provide-service" in text  # default service_name visible


def test_redacted_repr_returns_string() -> None:
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"X-Api-Key": "sk-1234567890abcdef"}),
    )
    safe = cfg.redacted_repr()
    assert isinstance(safe, str)
    assert "1234567890abcdef" not in safe  # pragma: allowlist secret


def test_short_header_value_fully_masked() -> None:
    cfg = TelemetryConfig(
        logging=LoggingConfig(otlp_headers={"X-Key": "short"}),
    )
    text = repr(cfg)
    assert "short" not in text
    assert "****" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_config_masking"`
Expected: FAIL — `__repr__` not defined, `redacted_repr` not found.

- [ ] **Step 3: Implement masking in Python config.py**

Add helper functions and `__repr__`/`redacted_repr` to `config.py`:

```python
def _mask_header_value(value: str) -> str:
    """Mask a header value: show first 4 chars + **** if >= 8 chars, else ****."""
    if len(value) < 8:
        return "****"
    return value[:4] + "****"


def _mask_endpoint_url(url: str) -> str:
    """Mask password in URL userinfo (user:password@host)."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.password:
        masked_netloc = f"{parsed.username}:****@{parsed.hostname}"
        if parsed.port:
            masked_netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=masked_netloc))
    return url


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: _mask_header_value(v) for k, v in headers.items()}
```

Add `__repr__` and `redacted_repr` to `TelemetryConfig`:

```python
def redacted_repr(self) -> str:
    """Return a string representation with secrets masked."""
    parts = []
    for f in __import__("dataclasses").fields(self):
        val = getattr(self, f.name)
        if hasattr(val, "otlp_headers") or hasattr(val, "otlp_endpoint"):
            val = _redact_sub_config(val)
        parts.append(f"{f.name}={val!r}")
    return f"TelemetryConfig({', '.join(parts)})"

def __repr__(self) -> str:
    return self.redacted_repr()
```

Add similar `__repr__` to `LoggingConfig`, `TracingConfig`, `MetricsConfig` that mask their own `otlp_headers` and `otlp_endpoint`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_config_masking"`
Expected: PASS

- [ ] **Step 5: Implement masking in Go config.go**

Add `String()` and `GoString()` to `TelemetryConfig`:

```go
func _maskHeaderValue(v string) string {
	if len(v) < 8 {
		return "****"
	}
	return v[:4] + "****"
}

func _maskHeaders(h map[string]string) map[string]string {
	masked := make(map[string]string, len(h))
	for k, v := range h {
		masked[k] = _maskHeaderValue(v)
	}
	return masked
}

func _maskEndpointURL(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.User == nil {
		return raw
	}
	if _, hasPass := u.User.Password(); hasPass {
		u.User = url.UserPassword(u.User.Username(), "****")
	}
	return u.String()
}

func (c *TelemetryConfig) RedactedString() string {
	// Build a safe string representation
	return fmt.Sprintf("TelemetryConfig{ServiceName:%q, Environment:%q, Logging.OTLPHeaders:%v, Tracing.OTLPHeaders:%v}",
		c.ServiceName, c.Environment,
		_maskHeaders(c.Logging.OTLPHeaders),
		_maskHeaders(c.Tracing.OTLPHeaders))
}

func (c *TelemetryConfig) String() string  { return c.RedactedString() }
func (c *TelemetryConfig) GoString() string { return c.RedactedString() }
```

- [ ] **Step 6: Write Go tests**

Create `go/config_masking_test.go` with tests mirroring the Python ones.

- [ ] **Step 7: Implement masking in TypeScript config.ts**

Add `redactedString()` and `toJSON()` as standalone functions (TS uses interfaces, not classes):

```typescript
export function redactConfig(config: TelemetryConfig): Record<string, unknown> {
  const redacted = { ...config } as Record<string, unknown>;
  if (config.otlpHeaders) {
    redacted.otlpHeaders = Object.fromEntries(
      Object.entries(config.otlpHeaders).map(([k, v]) => [k, maskHeaderValue(v)]),
    );
  }
  if (config.otlpEndpoint) {
    redacted.otlpEndpoint = maskEndpointUrl(config.otlpEndpoint);
  }
  return redacted;
}

function maskHeaderValue(v: string): string {
  return v.length < 8 ? '****' : v.slice(0, 4) + '****';
}

function maskEndpointUrl(raw: string): string {
  try {
    const u = new URL(raw);
    if (u.password) {
      u.password = '****';
      return u.toString();
    }
  } catch { /* not a URL */ }
  return raw;
}
```

- [ ] **Step 8: Write TypeScript tests**

Create `typescript/tests/config-masking.test.ts` mirroring the Python patterns.

- [ ] **Step 9: Run all tests in all 3 languages**

Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/provide/telemetry/config.py go/config.go typescript/src/config.ts \
  tests/governance/test_config_masking.py go/config_masking_test.go typescript/tests/config-masking.test.ts
git commit -m "feat: add config secret masking to __repr__/String/redactConfig (all languages)"
```

---

### Task 7: Classification module (all 3 languages)

**Files:**
- Create: `src/provide/telemetry/classification.py`
- Create: `go/classification.go`
- Create: `typescript/src/classification.ts`
- Create: `tests/governance/test_classification_module.py`
- Create: `go/classification_test.go`
- Create: `typescript/tests/classification.test.ts`
- Modify: `src/provide/telemetry/__init__.py`
- Modify: `typescript/src/index.ts`

- [ ] **Step 1: Write failing test (Python)**

```python
# tests/governance/test_classification_module.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for data classification module."""

from __future__ import annotations

import pytest

from provide.telemetry.classification import (
    ClassificationPolicy,
    ClassificationRule,
    DataClass,
    get_classification_policy,
    register_classification_rules,
    set_classification_policy,
)
from provide.telemetry import pii as pii_mod


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    from provide.telemetry.classification import _reset_classification_for_tests
    _reset_classification_for_tests()


def test_data_class_enum_values() -> None:
    assert DataClass.PUBLIC.value == "PUBLIC"
    assert DataClass.PII.value == "PII"
    assert DataClass.PHI.value == "PHI"
    assert DataClass.PCI.value == "PCI"
    assert DataClass.SECRET.value == "SECRET"
    assert DataClass.INTERNAL.value == "INTERNAL"


def test_register_classification_rules_installs_hook() -> None:
    register_classification_rules([
        ClassificationRule(pattern="user.*email*", classification=DataClass.PII),
    ])
    assert pii_mod._classification_hook is not None


def test_classification_tags_added_to_payload() -> None:
    register_classification_rules([
        ClassificationRule(pattern="email", classification=DataClass.PII),
    ])
    result = pii_mod.sanitize_payload({"email": "alice@example.com"}, enabled=True)
    assert "__email__class" in result
    assert result["__email__class"] == "PII"


def test_classification_policy_drives_action() -> None:
    set_classification_policy(ClassificationPolicy(
        PII="redact",
        PHI="drop",
        PCI="hash",
    ))
    register_classification_rules([
        ClassificationRule(pattern="email", classification=DataClass.PII),
    ])
    result = pii_mod.sanitize_payload({"email": "alice@example.com"}, enabled=True)
    assert result["email"] == "***"


def test_no_rules_registered_means_no_overhead() -> None:
    assert pii_mod._classification_hook is None
    result = pii_mod.sanitize_payload({"email": "alice@example.com"}, enabled=True)
    assert "__email__class" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_classification_module"`
Expected: FAIL — `classification` module not found.

- [ ] **Step 3: Implement Python classification.py**

Create `src/provide/telemetry/classification.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Data classification engine — strippable governance module.

Registers a classification hook on the PII engine when rules are configured.
If this file is deleted, the PII engine runs unchanged (hook stays None).
"""

from __future__ import annotations

__all__ = [
    "ClassificationPolicy",
    "ClassificationRule",
    "DataClass",
    "get_classification_policy",
    "register_classification_rules",
    "set_classification_policy",
]

import enum
import fnmatch
import threading
from dataclasses import dataclass, field
from typing import Any

from provide.telemetry import pii as pii_mod


class DataClass(enum.Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PII = "PII"
    PHI = "PHI"
    PCI = "PCI"
    SECRET = "SECRET"  # pragma: allowlist secret


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    pattern: str
    classification: DataClass


@dataclass(slots=True)
class ClassificationPolicy:
    PUBLIC: str = "pass"
    INTERNAL: str = "pass"
    PII: str = "redact"
    PHI: str = "drop"
    PCI: str = "hash"
    SECRET: str = "drop"  # pragma: allowlist secret


_lock = threading.Lock()
_rules: list[ClassificationRule] = []
_policy: ClassificationPolicy = ClassificationPolicy()


def register_classification_rules(rules: list[ClassificationRule]) -> None:
    with _lock:
        _rules.extend(rules)
    # Install hook on PII engine
    pii_mod._classification_hook = _classify_field


def set_classification_policy(policy: ClassificationPolicy) -> None:
    global _policy
    with _lock:
        _policy = policy


def get_classification_policy() -> ClassificationPolicy:
    with _lock:
        return _policy


def _classify_field(key: str, value: Any) -> str | None:
    with _lock:
        for rule in _rules:
            if fnmatch.fnmatch(key, rule.pattern):
                return rule.classification.value
    return None


def _reset_classification_for_tests() -> None:
    global _policy
    with _lock:
        _rules.clear()
        _policy = ClassificationPolicy()
    pii_mod._classification_hook = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_classification_module"`
Expected: PASS

- [ ] **Step 5: Implement Go classification.go**

Create `go/classification.go` with the same types and hook registration pattern, using `sync.RWMutex` and `filepath.Match` for glob patterns.

- [ ] **Step 6: Write Go tests in go/classification_test.go**

Mirror the Python test patterns.

- [ ] **Step 7: Implement TypeScript classification.ts**

Create `typescript/src/classification.ts` with the same types. Use `minimatch` or simple glob matching. Register hook on `_classificationHook`.

- [ ] **Step 8: Write TypeScript tests in typescript/tests/classification.test.ts**

Mirror the Python test patterns.

- [ ] **Step 9: Update exports — Python __init__.py and TypeScript index.ts**

Python — add to `__init__.py` with `try/except ImportError` for strippability:

```python
try:
    _register(
        "provide.telemetry.classification",
        "ClassificationPolicy",
        "ClassificationRule",
        "DataClass",
        "register_classification_rules",
        "set_classification_policy",
        "get_classification_policy",
    )
except Exception:
    pass
```

TypeScript — add conditional re-export in `index.ts`.

- [ ] **Step 10: Run all tests in all 3 languages**

Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add src/provide/telemetry/classification.py go/classification.go \
  typescript/src/classification.ts tests/governance/test_classification_module.py \
  go/classification_test.go typescript/tests/classification.test.ts \
  src/provide/telemetry/__init__.py typescript/src/index.ts
git commit -m "feat: add data classification module with hook-based PII integration (all languages)"
```

---

### Task 8: Consent module (all 3 languages)

**Files:**
- Create: `src/provide/telemetry/consent.py`
- Create: `go/consent.go`
- Create: `typescript/src/consent.ts`
- Create: `tests/governance/test_consent.py`
- Create: `go/consent_test.go`
- Create: `typescript/tests/consent.test.ts`

- [ ] **Step 1: Write failing test (Python)**

```python
# tests/governance/test_consent.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for consent-aware collection."""

from __future__ import annotations

import pytest

from provide.telemetry.consent import ConsentLevel, get_consent_level, set_consent_level, should_allow


@pytest.fixture(autouse=True)
def _reset() -> None:
    from provide.telemetry.consent import _reset_consent_for_tests
    _reset_consent_for_tests()


def test_default_consent_is_full() -> None:
    assert get_consent_level() == ConsentLevel.FULL


def test_full_allows_all_signals() -> None:
    set_consent_level(ConsentLevel.FULL)
    assert should_allow("logs", "DEBUG") is True
    assert should_allow("traces") is True
    assert should_allow("metrics") is True
    assert should_allow("context") is True


def test_none_blocks_all_signals() -> None:
    set_consent_level(ConsentLevel.NONE)
    assert should_allow("logs", "ERROR") is False
    assert should_allow("traces") is False
    assert should_allow("metrics") is False
    assert should_allow("context") is False


def test_functional_allows_warn_and_above_logs() -> None:
    set_consent_level(ConsentLevel.FUNCTIONAL)
    assert should_allow("logs", "DEBUG") is False
    assert should_allow("logs", "INFO") is False
    assert should_allow("logs", "WARNING") is True
    assert should_allow("logs", "ERROR") is True
    assert should_allow("traces") is True
    assert should_allow("metrics") is True
    assert should_allow("context") is False


def test_minimal_allows_errors_and_health_only() -> None:
    set_consent_level(ConsentLevel.MINIMAL)
    assert should_allow("logs", "WARNING") is False
    assert should_allow("logs", "ERROR") is True
    assert should_allow("traces") is False  # only error spans, handled by decorator
    assert should_allow("metrics") is False  # only health counters, handled at metric layer
    assert should_allow("context") is False


def test_set_consent_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "MINIMAL")
    from provide.telemetry.consent import _load_consent_from_env
    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.MINIMAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_consent"`
Expected: FAIL — `consent` module not found.

- [ ] **Step 3: Implement Python consent.py**

Create `src/provide/telemetry/consent.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Consent-aware telemetry collection — strippable governance module.

When deleted, the consent hook stays None and all signals pass through.
"""

from __future__ import annotations

__all__ = [
    "ConsentLevel",
    "get_consent_level",
    "set_consent_level",
    "should_allow",
]

import enum
import os
import threading


class ConsentLevel(enum.Enum):
    FULL = "FULL"
    FUNCTIONAL = "FUNCTIONAL"
    MINIMAL = "MINIMAL"
    NONE = "NONE"


_LOG_LEVEL_ORDER = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}

_lock = threading.Lock()
_level: ConsentLevel = ConsentLevel.FULL


def set_consent_level(level: ConsentLevel) -> None:
    global _level
    with _lock:
        _level = level


def get_consent_level() -> ConsentLevel:
    with _lock:
        return _level


def should_allow(signal: str, log_level: str | None = None) -> bool:
    with _lock:
        level = _level

    if level == ConsentLevel.FULL:
        return True
    if level == ConsentLevel.NONE:
        return False
    if level == ConsentLevel.FUNCTIONAL:
        if signal == "logs":
            return _LOG_LEVEL_ORDER.get((log_level or "").upper(), 0) >= _LOG_LEVEL_ORDER["WARNING"]
        if signal == "context":
            return False
        return True  # traces and metrics allowed
    # MINIMAL
    if signal == "logs":
        return _LOG_LEVEL_ORDER.get((log_level or "").upper(), 0) >= _LOG_LEVEL_ORDER["ERROR"]
    return False  # traces/metrics/context blocked at MINIMAL


def _load_consent_from_env() -> None:
    raw = os.environ.get("PROVIDE_CONSENT_LEVEL", "FULL").strip().upper()
    try:
        set_consent_level(ConsentLevel(raw))
    except ValueError:
        pass  # invalid value, keep default


def _reset_consent_for_tests() -> None:
    global _level
    with _lock:
        _level = ConsentLevel.FULL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_consent"`
Expected: PASS

- [ ] **Step 5: Implement Go consent.go**

Create `go/consent.go` with the same enum, `ShouldAllow`, and `SetConsentLevel` using `sync.RWMutex`.

- [ ] **Step 6: Write Go tests in go/consent_test.go**

Mirror the Python test patterns.

- [ ] **Step 7: Implement TypeScript consent.ts**

Create `typescript/src/consent.ts` with the same logic. Export from `index.ts`.

- [ ] **Step 8: Write TypeScript tests in typescript/tests/consent.test.ts**

Mirror the Python test patterns.

- [ ] **Step 9: Update exports — Python __init__.py and TypeScript index.ts**

Same pattern as classification — `try/except` in Python, conditional re-export in TS.

- [ ] **Step 10: Run all tests in all 3 languages**

Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add src/provide/telemetry/consent.py go/consent.go typescript/src/consent.ts \
  tests/governance/test_consent.py go/consent_test.go typescript/tests/consent.test.ts \
  src/provide/telemetry/__init__.py typescript/src/index.ts
git commit -m "feat: add consent-aware collection module (all languages)"
```

---

### Task 9: Receipts module (all 3 languages)

**Files:**
- Create: `src/provide/telemetry/receipts.py`
- Create: `go/receipts.go`
- Create: `typescript/src/receipts.ts`
- Create: `tests/governance/test_receipts.py`
- Create: `go/receipts_test.go`
- Create: `typescript/tests/receipts.test.ts`

- [ ] **Step 1: Write failing test (Python)**

```python
# tests/governance/test_receipts.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for cryptographic redaction receipts."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.receipts import (
    RedactionReceipt,
    enable_receipts,
    get_emitted_receipts_for_tests,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    from provide.telemetry.receipts import _reset_receipts_for_tests
    _reset_receipts_for_tests()


def test_receipts_disabled_by_default() -> None:
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    assert len(get_emitted_receipts_for_tests()) == 0


def test_receipts_emitted_when_enabled() -> None:
    enable_receipts(enabled=True, signing_key=None)
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) >= 1
    r = receipts[0]
    assert r.field_path == "password"
    assert r.action == "redact"
    assert r.receipt_id  # non-empty UUID


def test_receipt_original_hash_is_sha256() -> None:
    enable_receipts(enabled=True, signing_key=None)
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    expected_hash = hashlib.sha256("secret123".encode()).hexdigest()
    assert receipts[0].original_hash == expected_hash


def test_receipt_hmac_when_key_provided() -> None:
    enable_receipts(enabled=True, signing_key="test-key")
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    r = receipts[0]
    assert r.hmac != ""
    # Verify HMAC
    payload = f"{r.receipt_id}|{r.timestamp}|{r.field_path}|{r.action}|{r.original_hash}"
    expected = hmac.new("test-key".encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert r.hmac == expected


def test_receipt_hmac_empty_when_no_key() -> None:
    enable_receipts(enabled=True, signing_key=None)
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    assert receipts[0].hmac == ""


def test_receipt_tamper_detection() -> None:
    enable_receipts(enabled=True, signing_key="test-key")
    pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
    receipts = get_emitted_receipts_for_tests()
    r = receipts[0]
    # Tamper with the field_path
    tampered_payload = f"{r.receipt_id}|{r.timestamp}|TAMPERED|{r.action}|{r.original_hash}"
    tampered_hmac = hmac.new("test-key".encode(), tampered_payload.encode(), hashlib.sha256).hexdigest()
    assert r.hmac != tampered_hmac
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_receipts"`
Expected: FAIL — `receipts` module not found.

- [ ] **Step 3: Implement Python receipts.py**

Create `src/provide/telemetry/receipts.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cryptographic redaction receipts — strippable governance module.

When deleted, the receipt hook stays None and the PII engine skips receipt generation.
"""

from __future__ import annotations

__all__ = [
    "RedactionReceipt",
    "enable_receipts",
]

import hashlib
import hmac as hmac_mod
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from provide.telemetry import pii as pii_mod


@dataclass(frozen=True, slots=True)
class RedactionReceipt:
    receipt_id: str
    timestamp: str
    service_name: str
    field_path: str
    action: str
    classification: str
    rule_id: str
    original_hash: str
    hmac: str


_lock = threading.Lock()
_enabled: bool = False
_signing_key: str | None = None
_service_name: str = "unknown"
# For testing — captures receipts instead of logging them
_test_receipts: list[RedactionReceipt] = []
_test_mode: bool = False


def enable_receipts(
    enabled: bool = True,
    signing_key: str | None = None,
    service_name: str = "unknown",
) -> None:
    global _enabled, _signing_key, _service_name
    with _lock:
        _enabled = enabled
        _signing_key = signing_key
        _service_name = service_name
    if enabled:
        pii_mod._receipt_hook = _on_redaction
    else:
        pii_mod._receipt_hook = None


def _on_redaction(field_path: str, action: str, original_value: Any) -> None:
    receipt_id = str(uuid.uuid4())
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    original_hash = hashlib.sha256(str(original_value).encode("utf-8")).hexdigest()

    with _lock:
        key = _signing_key
        svc = _service_name

    hmac_value = ""
    if key:
        payload = f"{receipt_id}|{timestamp}|{field_path}|{action}|{original_hash}"
        hmac_value = hmac_mod.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    receipt = RedactionReceipt(
        receipt_id=receipt_id,
        timestamp=timestamp,
        service_name=svc,
        field_path=field_path,
        action=action,
        classification="PUBLIC",  # set by classification hook if active
        rule_id="default",
        original_hash=original_hash,
        hmac=hmac_value,
    )

    with _lock:
        if _test_mode:
            _test_receipts.append(receipt)
            return

    # In production, emit as structured log event
    import logging
    logging.getLogger("provide.telemetry.receipts").debug(
        "provide.pii.redaction_receipt",
        extra={"receipt": receipt.__dict__},
    )


def get_emitted_receipts_for_tests() -> list[RedactionReceipt]:
    with _lock:
        return list(_test_receipts)


def _reset_receipts_for_tests() -> None:
    global _enabled, _signing_key, _test_mode
    with _lock:
        _enabled = False
        _signing_key = None
        _test_receipts.clear()
        _test_mode = True
    pii_mod._receipt_hook = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_receipts"`
Expected: PASS

- [ ] **Step 5: Implement Go receipts.go**

Create `go/receipts.go` with the same `RedactionReceipt` struct, HMAC signing, and hook registration using `crypto/hmac` and `crypto/sha256` from stdlib.

- [ ] **Step 6: Write Go tests in go/receipts_test.go**

Mirror the Python test patterns — verify HMAC correctness, tamper detection, disabled-by-default.

- [ ] **Step 7: Implement TypeScript receipts.ts**

Create `typescript/src/receipts.ts` using Node.js `crypto.createHmac` and `crypto.createHash`. Register hook on `_receiptHook`.

- [ ] **Step 8: Write TypeScript tests in typescript/tests/receipts.test.ts**

Mirror the Python test patterns.

- [ ] **Step 9: Update exports**

Same pattern — `try/except` in Python `__init__.py`, conditional re-export in TS `index.ts`.

- [ ] **Step 10: Run all tests in all 3 languages**

Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add src/provide/telemetry/receipts.py go/receipts.go typescript/src/receipts.ts \
  tests/governance/test_receipts.py go/receipts_test.go typescript/tests/receipts.test.ts \
  src/provide/telemetry/__init__.py typescript/src/index.ts
git commit -m "feat: add cryptographic redaction receipts module (all languages)"
```

> **Note:** Batch receipt mode (`PROVIDE_REDACTION_RECEIPT_MODE=batch`) is spec'd but deferred to a follow-up task. The `single` mode (default) is implemented here. Batch mode aggregates receipts per `sanitize_payload` call rather than per-field — add a `_batch_receipts: list` accumulator and flush at the end of `sanitize_payload` when mode is `batch`.

---

### Task 10: Spec update — add governance types

**Files:**
- Modify: `spec/telemetry-api.yaml`

- [ ] **Step 1: Add governance types and APIs to spec**

Add under appropriate sections in `spec/telemetry-api.yaml`:

```yaml
  governance:
    - name: register_classification_rules
      kind: function
      required: false
      note: "Strippable — only present when classification module is installed"
    - name: set_classification_policy
      kind: function
      required: false
    - name: get_classification_policy
      kind: function
      required: false
    - name: set_consent_level
      kind: function
      required: false
      note: "Strippable — only present when consent module is installed"
    - name: get_consent_level
      kind: function
      required: false
    - name: enable_receipts
      kind: function
      required: false
      note: "Strippable — only present when receipts module is installed"

  # Under types:
    - name: DataClass
      kind: type
      required: false
    - name: ClassificationRule
      kind: type
      required: false
    - name: ClassificationPolicy
      kind: type
      required: false
    - name: ConsentLevel
      kind: type
      required: false
    - name: RedactionReceipt
      kind: type
      required: false
```

Add new config env vars:

```yaml
  - prefix: PROVIDE_
    keys:
      - CONSENT_LEVEL
      - REDACTION_RECEIPTS
      - REDACTION_RECEIPT_KEY
      - REDACTION_RECEIPT_MODE
```

- [ ] **Step 2: Run conformance validator**

Run: `uv run python spec/validate_conformance.py`
Expected: PASS (governance symbols are `required: false`).

- [ ] **Step 3: Commit**

```bash
git add spec/telemetry-api.yaml
git commit -m "spec: add governance types (classification, consent, receipts) as optional symbols"
```

---

### Task 11: Cross-language integration tests

**Files:**
- Create: `e2e/test_governance_integration.py`
- Create: `e2e/governance_integration_test.go`
- Create: `e2e/governance-integration.test.ts`

- [ ] **Step 1: Write Python integration test**

```python
# e2e/test_governance_integration.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Integration test: full governance pipeline.

Exercises classification → PII redaction → receipt generation in a single flow.
"""

from __future__ import annotations

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.classification import (
    ClassificationPolicy,
    ClassificationRule,
    DataClass,
    register_classification_rules,
    set_classification_policy,
)
from provide.telemetry.consent import ConsentLevel, set_consent_level, should_allow
from provide.telemetry.receipts import enable_receipts, get_emitted_receipts_for_tests


@pytest.fixture(autouse=True)
def _reset() -> None:
    pii_mod.reset_pii_rules_for_tests()
    from provide.telemetry.classification import _reset_classification_for_tests
    from provide.telemetry.consent import _reset_consent_for_tests
    from provide.telemetry.receipts import _reset_receipts_for_tests
    _reset_classification_for_tests()
    _reset_consent_for_tests()
    _reset_receipts_for_tests()


def test_full_governance_pipeline() -> None:
    """Classification tags + receipt generation in a single sanitize pass."""
    # 1. Configure classification
    register_classification_rules([
        ClassificationRule(pattern="email", classification=DataClass.PII),
        ClassificationRule(pattern="ssn", classification=DataClass.PHI),
    ])
    set_classification_policy(ClassificationPolicy(PII="redact", PHI="drop"))

    # 2. Enable receipts with signing
    enable_receipts(enabled=True, signing_key="integration-test-key", service_name="test-svc")

    # 3. Run the pipeline
    result = pii_mod.sanitize_payload(
        {"email": "alice@example.com", "ssn": "123-45-6789", "name": "Alice"},
        enabled=True,
    )

    # 4. Verify classification tags
    assert "__email__class" in result
    assert result["__email__class"] == "PII"

    # 5. Verify redaction
    assert result["email"] == "***"
    assert "ssn" not in result  # PHI → drop

    # 6. Verify receipts were generated with HMAC
    receipts = get_emitted_receipts_for_tests()
    assert len(receipts) >= 2  # at least email and ssn
    for r in receipts:
        assert r.hmac != ""  # signed
        assert r.service_name == "test-svc"


def test_consent_blocks_before_classification() -> None:
    """When consent is NONE, no signals should be processed at all."""
    set_consent_level(ConsentLevel.NONE)
    assert should_allow("logs", "INFO") is False
    assert should_allow("traces") is False
    assert should_allow("metrics") is False
```

- [ ] **Step 2: Write Go integration test**

Create `e2e/governance_integration_test.go` following the same pattern — register classification rules, enable receipts, run `SanitizePayload`, verify tags + receipts + HMAC.

- [ ] **Step 3: Write TypeScript integration test**

Create `e2e/governance-integration.test.ts` following the same pattern.

- [ ] **Step 4: Run all integration tests**

```bash
uv run python scripts/run_pytest_gate.py --no-cov -q e2e/test_governance_integration.py
cd go && go test -run "TestGovernance" -v ./...
cd typescript && npx vitest run e2e/governance-integration.test.ts
```

Expected: PASS in all three.

- [ ] **Step 5: Commit**

```bash
git add e2e/test_governance_integration.py e2e/governance_integration_test.go \
  e2e/governance-integration.test.ts
git commit -m "test: add cross-language governance integration tests"
```

---

### Task 12: Strippability verification test

**Files:**
- Create: `tests/governance/test_strippability.py`

- [ ] **Step 1: Write strippability test**

```python
# tests/governance/test_strippability.py
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Verify that deleting governance files doesn't break the core library."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch


def test_library_works_without_classification_module() -> None:
    """Simulate deletion of classification.py by blocking its import."""
    with patch.dict(sys.modules, {"provide.telemetry.classification": None}):
        from provide.telemetry import pii as pii_mod
        importlib.reload(pii_mod)
        result = pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
        assert result["password"] == "***"
        assert "__password__class" not in result


def test_library_works_without_consent_module() -> None:
    """Simulate deletion of consent.py — all signals pass through."""
    with patch.dict(sys.modules, {"provide.telemetry.consent": None}):
        from provide.telemetry import pii as pii_mod
        importlib.reload(pii_mod)
        result = pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
        assert result["password"] == "***"


def test_library_works_without_receipts_module() -> None:
    """Simulate deletion of receipts.py — no receipts emitted."""
    with patch.dict(sys.modules, {"provide.telemetry.receipts": None}):
        from provide.telemetry import pii as pii_mod
        importlib.reload(pii_mod)
        result = pii_mod.sanitize_payload({"password": "secret123"}, enabled=True)  # pragma: allowlist secret
        assert result["password"] == "***"
```

- [ ] **Step 2: Run test**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_strippability"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/governance/test_strippability.py
git commit -m "test: verify governance modules are safely strippable"
```

---

### Task 13: Full coverage and quality gates

- [ ] **Step 1: Run Python full coverage gate**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: 100% branch coverage, all tests pass.

- [ ] **Step 2: Run Python linting and type checking**

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run bandit -r src -ll
uv run codespell
```

Expected: PASS

- [ ] **Step 3: Run Go full test suite**

Run: `cd go && go test -race -coverprofile=coverage.out ./... && go tool cover -func=coverage.out`
Expected: All tests pass, high coverage.

- [ ] **Step 4: Run TypeScript full test suite**

Run: `cd typescript && npx vitest run --coverage`
Expected: All tests pass.

- [ ] **Step 5: Run LOC gate**

Run: `uv run python scripts/check_max_loc.py --max-lines 500`
Expected: PASS — no file exceeds 500 lines.

- [ ] **Step 6: Run SPDX header check**

Run: `uv run python scripts/check_spdx_headers.py`
Expected: PASS — all new files have headers.

- [ ] **Step 7: Fix any failures, commit**

```bash
git add -A
git commit -m "fix: resolve coverage/lint/type-check issues from governance implementation"
```
