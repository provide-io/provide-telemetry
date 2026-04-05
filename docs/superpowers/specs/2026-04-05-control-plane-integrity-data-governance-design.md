# Control-Plane Integrity & Data Governance at the Edge

**Date:** 2026-04-05
**Status:** Approved
**Scope:** Two sub-projects — (1) hot/cold config enforcement + immutability fixes, (2) data classification, consent-aware collection, cryptographic redaction receipts, and config secret masking.

---

## Sub-project 1: Control-Plane Integrity (P1-P3 Fixes)

### Problem

The runtime update APIs accept and persist cold/provider fields even though only hot fields are applied. Mutable config objects leak through public APIs in Go and TypeScript. The TS lint gate allows warning accumulation.

Specific issues:

- **P1:** `updateRuntimeConfig()` and `reloadRuntimeFromEnv()` accept a full `TelemetryConfig` in all three languages, but `apply_runtime_config()` / `_applyRuntimePolicies()` only reapplies hot policies (sampling, backpressure, exporter). Cold fields (service_name, environment, version, tracing, metrics) are stored in the active snapshot without being applied, creating a divergence between what the control plane reports and what the data plane is doing.
- **P2:** Go `SetupTelemetry()` returns the live `_runtimeCfg` pointer on the idempotent path (`setup.go:99`). TypeScript `getRuntimeConfig()` returns `_activeConfig` by reference and `updateRuntimeConfig()` shallow-merges nested state. Callers can mutate returned objects and bypass validation.
- **P3:** TypeScript `package.json` runs `eslint src tests` without `--max-warnings=0`, allowing warning debt to accumulate while CI stays green.

### Solution: `RuntimeOverrides` Type + Frozen Returns

#### New `RuntimeOverrides` type (all 3 languages)

```
RuntimeOverrides {
  sampling?:      SamplingConfig
  backpressure?:  BackpressureConfig
  exporter?:      ExporterPolicyConfig
  security?:      SecurityConfig
  slo?:           SLOConfig
  pii_max_depth?: int
}
```

All fields are optional. Only hot-reloadable fields are representable. Cold fields (service_name, environment, version, tracing, metrics) are physically excluded from the type.

#### API changes

| Current | New |
|---------|-----|
| `updateRuntimeConfig(TelemetryConfig)` | `updateRuntimeConfig(RuntimeOverrides)` |
| `reloadRuntimeFromEnv() -> TelemetryConfig` | `reloadRuntimeFromEnv() -> FrozenTelemetryConfig` |
| `getRuntimeConfig() -> TelemetryConfig` | `getRuntimeConfig() -> FrozenTelemetryConfig` |
| `reconfigureTelemetry(TelemetryConfig)` | Unchanged (cold path — full config is correct) |

#### Frozen return types

`FrozenTelemetryConfig` is not a separate type — it is `TelemetryConfig` returned as an immutable defensive copy. The "Frozen" prefix is a documentation convention to signal the contract.

- **Python:** Return type is `TelemetryConfig` via `copy.deepcopy()` (already done). Formalize by documenting the return as a defensive copy.
- **Go:** `SetupTelemetry()` idempotent path (`setup.go:99`) returns `cloneTelemetryConfig(_runtimeCfg)` instead of the live pointer. `GetRuntimeConfig()` already clones (no change).
- **TypeScript:** `getRuntimeConfig()` returns `Readonly<TelemetryConfig>` with `Object.freeze()` applied to the snapshot. Deep freeze nested objects (otlpHeaders, etc.).

#### `reloadRuntimeFromEnv()` behavior

This function parses the full environment into a `TelemetryConfig`, extracts the hot-reloadable fields, applies them as a `RuntimeOverrides`, and returns the frozen full config snapshot. Cold fields in the parsed config are compared against the active snapshot — if they differ, a warning is logged (not an error) to alert operators that a process restart is needed to apply those changes.

#### TS lint fix

Add `--max-warnings=0` to the eslint script in `typescript/package.json`.

#### Spec update

Add `RuntimeOverrides` to `spec/telemetry-api.yaml` as a required type. Update `update_runtime_config` and `reload_runtime_from_env` signatures.

---

## Sub-project 2: Data Governance at the Edge

### 2A: Config Secret Masking

#### Problem

`TelemetryConfig` objects contain OTLP headers (often bearer tokens) and endpoint URLs with credentials. If logged, serialized, or printed, credentials leak.

#### Solution

**Python:** Add `__repr__` to `TelemetryConfig`, `LoggingConfig`, `TracingConfig`, `MetricsConfig` that masks `otlp_headers` values and redacts credentials from `otlp_endpoint` URLs.

**Go:** Add `String()` and `GoString()` methods on `TelemetryConfig` (satisfies `fmt.Stringer` and `fmt.GoStringer`). Same masking logic.

**TypeScript:** Add `toJSON()` method that returns a redacted copy, plus `toString()` override. Prevents leakage via `JSON.stringify()`.

**Masking rules:**
- Header values: show first 4 chars + `****` (or `****` if value < 8 chars)
- URL userinfo: replace password with `****`
- Fields masked: all `otlp_headers` dicts, all `otlp_endpoint` strings containing userinfo

**Explicit API:** `redacted_repr()` / `RedactedString()` / `redactedString()` for callers who want a safe-to-log version programmatically.

---

### 2B: Data Classification Tags

#### Purpose

Label telemetry attributes with sensitivity classes so downstream systems can enforce policy based on labels.

#### Classification enum

```
DataClass {
  PUBLIC        // safe for any audience
  INTERNAL      // org-internal, not customer-facing
  PII           // personally identifiable information
  PHI           // protected health information (HIPAA)
  PCI           // payment card data (PCI-DSS)
  SECRET        // credentials, keys, tokens
}
```

#### Registration API

`register_classification_rules(rules: list[ClassificationRule])` — each rule maps a key pattern (glob or exact match) to a `DataClass`.

```
ClassificationRule {
  pattern:        string      // glob pattern, e.g. "user.*email*"
  classification: DataClass
}
```

#### Integration with PII engine

Add optional `classification: DataClass` field to `PIIRule`. When a PII rule matches, the classification tag propagates alongside the redaction action.

#### Attribute tagging

Classified attributes get a sibling key `__{key}__class: "PII"` in the telemetry payload. Downstream collectors/backends can filter on these tags.

#### Classification-driven policy

`ClassificationPolicy` defines actions per class:

```
ClassificationPolicy {
  PII:      "redact"
  PHI:      "drop"
  PCI:      "hash"
  PUBLIC:   "pass"
  SECRET:   "drop"  # pragma: allowlist secret
  INTERNAL: "pass"
}
```

This extends (not replaces) the existing PII rule engine — classification policy is evaluated after explicit PII rules, providing a fallback for fields that match a classification but have no explicit PII rule.

#### Extensibility

Residency hints attach to `DataClass` in a future iteration: `{PII: {action: "redact", residency: "eu-west-1"}}`. Retention policies attach similarly. The classification enum is the anchor point.

---

### 2C: Consent-Aware Collection

#### Purpose

Respect user consent preferences before telemetry enters the pipeline. Data that shouldn't be collected is never collected.

#### Consent model

```
ConsentLevel {
  FULL          // all signals collected
  FUNCTIONAL    // operational telemetry only (no user-identifying data)
  MINIMAL       // errors and health only
  NONE          // no telemetry emitted
}
```

#### API

`set_consent_level(level: ConsentLevel)` — hot-reloadable, added to `RuntimeOverrides`. Also settable via `PROVIDE_CONSENT_LEVEL` env var.

#### Signal mapping

| Consent Level | Logs | Traces | Metrics | User context binding |
|---------------|------|--------|---------|---------------------|
| FULL | all | all | all | yes |
| FUNCTIONAL | warn+ only | yes | yes | no (session/user IDs stripped) |
| MINIMAL | error+ only | error spans only | health counters only | no |
| NONE | none | none | none | no |

#### Pipeline position

Consent check is the **first gate** — before sampling, before PII scan, before backpressure. If consent says no, the signal is never constructed.

#### Integration points

- `get_logger()` — returned logger checks consent before emitting
- `@trace` decorator — checks consent before starting span
- `counter()`/`gauge()`/`histogram()` — check consent before recording
- `bind_session_context()` / `bind_context()` — no-op when consent < FULL

#### Runtime behavior

When consent level drops, in-flight signals already past the gate are allowed to complete. New signals immediately respect the new level.

#### Extensibility

Per-user consent (instead of global) attaches consent level to context vars alongside session ID. The gate check becomes `get_consent_for_context()` instead of `get_global_consent()`.

---

### 2D: Cryptographic Redaction Receipts

#### Purpose

Provide tamper-evident proof that specific data was redacted, by which rule, at what time. Novel differentiator — no telemetry SDK ships this.

#### Receipt structure

```
RedactionReceipt {
  receipt_id:      string        // UUID v4
  timestamp:       string        // ISO-8601
  service_name:    string        // from TelemetryConfig
  field_path:      string        // e.g. "user.email"
  action:          string        // "redact" | "hash" | "drop" | "truncate"
  classification:  DataClass     // from 2B (if classified, else PUBLIC)
  rule_id:         string        // which rule matched
  original_hash:   string        // SHA-256 of original value
  hmac:            string        // HMAC-SHA256(receipt_fields, service_key)
}
```

#### Signing key

`PROVIDE_REDACTION_RECEIPT_KEY` env var. If unset, receipts are emitted unsigned (HMAC field is empty string). Zero-config by default, cryptographically strong when configured.

#### Emission

Receipts are emitted as structured log events at `DEBUG` level via the existing logger pipeline. Event name: `provide.pii.redaction_receipt`. They flow through the normal export path (OTLP, console, etc.).

#### Opt-in

`PROVIDE_REDACTION_RECEIPTS=true` (default `false`). When disabled, zero overhead — PII engine skips receipt construction entirely.

#### Batch mode

`PROVIDE_REDACTION_RECEIPT_MODE=single|batch` (default `single`).

- `single`: one receipt per redacted field
- `batch`: one receipt per redaction pass, listing all affected fields in an array

#### What this enables

- **Compliance auditors** verify PII handling without seeing original data
- **Incident response** proves what was redacted during breach investigation
- **`original_hash`** allows correlation: "was this specific value redacted?" without storing the value

#### Extensibility

Receipts become entries in a formal audit log stream in a future iteration. The audit stream adds: config changes, consent changes, provider lifecycle events — all signed with the same key.

---

## Cross-Cutting Concerns

### Spec updates

All new types and APIs must be added to `spec/telemetry-api.yaml`:
- `RuntimeOverrides` type
- `DataClass` enum
- `ClassificationRule` and `ClassificationPolicy` types
- `ConsentLevel` enum
- `RedactionReceipt` type
- Updated signatures for `update_runtime_config`, `reload_runtime_from_env`
- New APIs: `register_classification_rules`, `set_consent_level`, `set_classification_policy`

### Polyglot parity

All features must be implemented in Python, Go, and TypeScript with identical behavior. Use the existing conformance validator (`spec/validate_conformance.py`) to verify exports.

### Configuration

New env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROVIDE_CONSENT_LEVEL` | `FULL` | Global consent level |
| `PROVIDE_REDACTION_RECEIPTS` | `false` | Enable redaction receipts |
| `PROVIDE_REDACTION_RECEIPT_KEY` | (unset) | HMAC signing key for receipts |
| `PROVIDE_REDACTION_RECEIPT_MODE` | `single` | `single` or `batch` receipt mode |

### Testing

- 100% branch coverage for all new code paths
- 100% mutation kill score
- Consent gate tests must verify signals are never constructed (not just dropped)
- Receipt HMAC tests must verify tamper detection (modify receipt, verify HMAC fails)
- Classification + PII engine integration tests (classified field triggers correct policy action)

### Performance

- Consent gate: single enum comparison — negligible overhead
- Classification: runs during PII traversal — no additional pass needed
- Receipts: SHA-256 + HMAC per redacted field (opt-in only)
- Config masking: only on `__repr__`/`String()`/`toString()` — not on hot path
