# Cross-Language Parity Phase 3 — Health Snapshots & PII Depth

**Date:** 2026-04-05
**Status:** Approved
**Scope:** Align health snapshot structure and PII depth handling across Go, TypeScript, and Python

## Problem

A third audit of the three provide-telemetry implementations found 2 remaining behavioral differences:

1. Health snapshots return incompatible structures across languages (Go: 14 fields, TypeScript: 20 fields, Python: 37 fields). Monitoring dashboards that consume health snapshots need consistent field names and semantics.
2. PII sanitization depth handling differs: Python defaults to depth 8, Go to 32, TypeScript has no limit. The same deeply nested payload gets different sanitization depending on which language is running.

## Scope Boundary

**In scope:** Canonical health snapshot field set, PII depth parameter alignment, env var configuration.

**Out of scope:** Language-idiomatic naming (Go `LogsEmitted` vs Python `emitted_logs`), internal-only counters that languages may keep beyond the canonical set.

## Design

### 1. Canonical Health Snapshot (25 fields)

**Per-signal fields** (repeated for logs, traces, metrics = 24 fields):

| Canonical Name | Type | Description |
|----------------|------|-------------|
| `emitted_{signal}` | int | Total items emitted/started/recorded |
| `dropped_{signal}` | int | Items dropped (backpressure or sampling) |
| `export_failures_{signal}` | int | Failed export attempts |
| `retries_{signal}` | int | Retry attempts |
| `export_latency_ms_{signal}` | float | Latest export latency in milliseconds (not cumulative) |
| `async_blocking_risk_{signal}` | int | Times blocking detected in async context |
| `circuit_state_{signal}` | string | `"closed"`, `"open"`, or `"half_open"` |
| `circuit_open_count_{signal}` | int | Times circuit breaker has tripped |

**Global field** (1 field):

| Canonical Name | Type | Description |
|----------------|------|-------------|
| `setup_error` | string\|null | Error message from last failed setup attempt, or null |

**Naming conventions** (language-idiomatic mappings):

| Canonical | Python | TypeScript | Go |
|-----------|--------|------------|-----|
| `emitted_logs` | `emitted_logs` | `logsEmitted` | `LogsEmitted` |
| `dropped_logs` | `dropped_logs` | `logsDropped` | `LogsDropped` |
| `export_failures_logs` | `export_failures_logs` | `exportFailuresLogs` | `LogsExportFailures` |
| `retries_logs` | `retries_logs` | `retriesLogs` | `LogsRetries` |
| `export_latency_ms_logs` | `export_latency_ms_logs` | `exportLatencyMsLogs` | `LogsExportLatencyMs` |
| `async_blocking_risk_logs` | `async_blocking_risk_logs` | `asyncBlockingRiskLogs` | `LogsAsyncBlockingRisk` |
| `circuit_state_logs` | `circuit_state_logs` | `circuitStateLogs` | `LogsCircuitState` |
| `circuit_open_count_logs` | `circuit_open_count_logs` | `circuitOpenCountLogs` | `LogsCircuitOpenCount` |
| `setup_error` | `setup_error` | `setupError` | `SetupError` |

(Same pattern for `_traces` and `_metrics` signals.)

#### Go Changes

**Add fields:**
- `LogsAsyncBlockingRisk`, `TracesAsyncBlockingRisk`, `MetricsAsyncBlockingRisk` — currently not tracked in Go. Add per-signal counters with `_incAsyncBlockingRisk(signal)` incrementer.
- `LogsCircuitState`, `TracesCircuitState`, `MetricsCircuitState` — currently Go tracks a single `CircuitBreakerTrips` counter. Change to per-signal circuit state strings derived from the existing `_circuit_tripped_at` and `_half_open_probing` state.
- `LogsCircuitOpenCount`, `TracesCircuitOpenCount`, `MetricsCircuitOpenCount` — per-signal open counts derived from existing `_open_count` dict.
- Per-signal `ExportLatencyMs` — currently a single cumulative value. Split to per-signal and track latest (not cumulative).
- Per-signal `Retries` — currently a single `RetryAttempts`. Split to per-signal.
- Per-signal `ExportFailures` — rename from `LogsExportErrors` to `LogsExportFailures` for cross-language consistency.
- `SetupError` — currently `LastError` serves a similar purpose. Rename and restrict to setup errors only.

**Remove from canonical struct** (may keep as internal if needed):
- `SetupCount`, `ShutdownCount` — lifecycle counters, not part of the cross-language contract
- `LogsExportedOK`, `TracesExportedOK`, `MetricsExportedOK` — success counters, not in canonical set
- `CircuitBreakerTrips` — replaced by per-signal circuit state

**Implementation notes:**
- Go's `HealthSnapshot` struct must be rewritten to match the 25-field canonical layout
- All increment functions (`_incLogsEmitted`, etc.) must be reviewed and aligned
- `GetHealthSnapshot()` must populate circuit state strings from `_circuit_tripped_at` / `_half_open_probing` / `_open_count` (matching how Python/TypeScript derive these)

#### TypeScript Changes

**Add fields:**
- Per-signal `exportLatencyMs` — split from single `exportLatencyMs` to `exportLatencyMsLogs`, `exportLatencyMsTraces`, `exportLatencyMsMetrics`
- Per-signal `retries` — split from single `exportRetries` to `retriesLogs`, `retriesTraces`, `retriesMetrics`
- Per-signal `exportFailures` — split from single `exportFailures` to `exportFailuresLogs`, `exportFailuresTraces`, `exportFailuresMetrics`
- Per-signal `asyncBlockingRisk` — split from single `asyncBlockingRisk` to per-signal

**Rename for consistency:**
- `logsEmitted` → already correct
- `logsDropped` → already correct

**Remove from canonical interface** (keep as internal if needed):
- `exemplarUnsupported` — not part of cross-language contract

#### Python Changes

**Remove from canonical dataclass** (keep as internal if needed):
- `queue_depth_{signal}` — backpressure queue depth is implementation detail, not cross-language observable
- `last_successful_export_{signal}` — timestamp of last success, not in canonical set
- `exemplar_unsupported_total` — not part of cross-language contract
- `circuit_cooldown_remaining_{signal}` — timing-dependent, hard to test deterministically, not in canonical set

**Rename for consistency:**
- Field names already follow the canonical pattern

### 2. PII Depth Alignment

**Canonical behavior:**
- All 3 languages accept a `max_depth` parameter in `sanitize_payload` / `SanitizePayload`
- Default value: **8**
- Configurable via `PROVIDE_LOG_PII_MAX_DEPTH` environment variable (parsed as non-negative integer)
- At depth >= max_depth, stop recursing and return the node unchanged
- Depth applies to **all** sanitization: default sensitive key redaction, custom PII rules, AND secret detection
- Depth counting starts at 0 for the top-level payload; each nested object/map increments by 1

**Python changes** (`src/provide/telemetry/pii.py`):
- Already has `max_depth` parameter with default 8 — no change to function signature
- Add `PROVIDE_LOG_PII_MAX_DEPTH` env var support in `TelemetryConfig.from_env()` / config parsing
- Wire config value through to `sanitize_payload` calls in the logger pipeline

**TypeScript changes** (`typescript/src/pii.ts`):
- Add `maxDepth` parameter to `sanitizePayload` (default 8)
- Add depth tracking during recursion in `_redactSecrets()` and `_applyRuleFull()`
- At depth >= maxDepth, return value unchanged (skip redaction, rules, and secret detection)
- Add `PROVIDE_LOG_PII_MAX_DEPTH` env var to `TelemetryConfig` interface and `fromEnv()` parser

**Go changes** (`go/pii.go`):
- Change `_piiDefaultMax` from 32 to 8
- Add `PROVIDE_LOG_PII_MAX_DEPTH` env var support in `DefaultTelemetryConfig()` / config parsing
- Normalize depth semantics: currently counts down from maxDepth and stops at `<= 1`. Change to count up from 0 and stop at `>= maxDepth` for conceptual consistency with Python/TypeScript. (Either direction works as long as effective behavior is identical — counting up is clearer.)

### 3. Spec and Fixture Updates

**Update `spec/telemetry-api.yaml`:**
- Add `health_snapshot` section to `behavioral_parity` defining the 25 canonical fields
- Add `pii_depth` section to `behavioral_parity` defining depth semantics

**Add to `spec/behavioral_fixtures.yaml`:**

```yaml
health_snapshot:
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
  circuit_state_values: ["closed", "open", "half_open"]

pii_depth:
  default_max_depth: 8
  env_var: PROVIDE_LOG_PII_MAX_DEPTH
  cases:
    - description: "nested payload at depth 7 — all levels redacted"
      max_depth: 8
      payload:
        password: "s3cret"  # pragma: allowlist secret
        nested:
          password: "s3cret"  # pragma: allowlist secret
          deep:
            password: "s3cret"  # pragma: allowlist secret
            deeper:
              password: "s3cret"  # pragma: allowlist secret
              level5:
                password: "s3cret"  # pragma: allowlist secret
                level6:
                  password: "s3cret"  # pragma: allowlist secret
                  level7:
                    password: "s3cret"  # pragma: allowlist secret
      expected_redacted_depths: [0, 1, 2, 3, 4, 5, 6]

    - description: "nested payload beyond max_depth — deep levels untouched"
      max_depth: 3
      payload:
        password: "s3cret"  # pragma: allowlist secret
        nested:
          password: "s3cret"  # pragma: allowlist secret
          deep:
            password: "s3cret"  # pragma: allowlist secret
            too_deep:
              password: "should_survive"  # pragma: allowlist secret
      expected_redacted_depths: [0, 1, 2]
      expected_unredacted_depths: [3]

    - description: "max_depth=0 disables depth-based recursion entirely"
      max_depth: 0
      note: "Treat 0 as 'use default (8)' — same as Go's current behavior for <= 0"
```

### 4. Parity Tests

Add cross-language parity tests for:
- Health snapshot returns all 25 canonical fields with correct types
- Health snapshot field values change correctly after operations (emit, drop, export failure, retry, circuit trip)
- `sanitize_payload` with `max_depth=3` redacts depths 0-2, leaves depth 3+ untouched
- `sanitize_payload` with default depth (8) redacts depths 0-7
- `PROVIDE_LOG_PII_MAX_DEPTH` env var is respected

## Risk Assessment

- **Section 1 (Health):** Medium-high risk. Go's health struct is being rewritten. TypeScript's interface gains per-signal granularity. Python drops fields. All health-consuming code (tests, monitoring, dashboards) must be updated. Mitigated by keeping changes additive where possible.
- **Section 2 (PII Depth):** Low risk. Python already correct. Go changes a default. TypeScript adds a parameter. Behavioral fixtures provide clear test vectors.
- **Sections 3-4 (Spec/Tests):** No risk. Additive.

## Success Criteria

1. All three languages return health snapshots with the same 25 canonical fields
2. Circuit state is per-signal (`"closed"`, `"open"`, `"half_open"`) in all three languages
3. `export_latency_ms` is per-signal and reports latest (not cumulative) in all three languages
4. `sanitize_payload` defaults to max_depth=8 in all three languages
5. `PROVIDE_LOG_PII_MAX_DEPTH` env var is supported in all three languages
6. Nested payload at depth 9 with max_depth=8: depths 0-7 redacted, depth 8+ untouched in all three
7. All existing tests continue to pass
8. 100% coverage and mutation efficacy maintained
