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

### Architecture: Hook-Based Integration & Strippable Files

Governance features (classification, consent, receipts) integrate with the core library via **callback hooks**, not direct imports. This achieves two goals: zero overhead when unconfigured, and safe file deletion for space-restricted environments.

#### Hook pattern

The PII engine and signal emission paths expose optional callback slots:

```
# PII engine (pii.py / pii.go / pii.ts)
_classification_hook: Callable | None = None   # called per field during traversal
_receipt_hook: Callable | None = None           # called per redaction action

# Signal paths (logger, tracing, metrics)
_consent_hook: Callable | None = None           # called before signal construction
```

Governance modules register their hooks on first use (e.g., `register_classification_rules()` sets `_classification_hook`). If no hook is registered, the core code skips the call entirely — a single `if hook is not None` check.

#### Strippable files

Each governance feature lives in its own file:

| File | Can be deleted? | What happens if deleted |
|------|----------------|------------------------|
| `classification.py/go/ts` | Yes | PII engine runs as today; `register_classification_rules` not exported |
| `consent.py/go/ts` | Yes | All signals pass through; `set_consent_level` not exported |
| `receipts.py/go/ts` | Yes | No receipts emitted; PII engine runs as today |
| `config.py` masking methods | No | Core file — masking is ~20 LOC inline, not worth separating |

#### Export handling for missing files

- **Python:** `__init__.py` uses `try: from .classification import ... except ImportError: pass` — missing governance files produce no export, no error.
- **Go:** Governance files are standalone `.go` files in the package. Deleting them removes the functions from the package. Consumers that don't call governance APIs need no changes. Consumers that do get a compile error (correct behavior — they depend on a feature that was stripped).
- **TypeScript:** Governance exports are re-exported from `index.ts` via dynamic checks or separate entrypoints. Tree shaking eliminates unused governance code in bundled consumers automatically.

#### Inert-by-default contract

Even when governance files are present, features are inert until configured:

- **Classification:** No rules registered = `_classification_hook` is `None` = zero overhead
- **Consent:** Default `FULL` = `_consent_hook` fast-returns `true` = single comparison
- **Receipts:** Default `PROVIDE_REDACTION_RECEIPTS=false` = `_receipt_hook` is `None` = zero overhead
- **Config masking:** Only executes on `__repr__`/`String()`/`toString()` — never on hot path

---

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

#### Integration with PII engine (via hook)

Add optional `classification: DataClass | None` field to `PIIRule` (default `None`). The classification module registers `_classification_hook` on the PII engine when `register_classification_rules()` is first called. If the classification file is deleted, `PIIRule.classification` remains `None` and the hook is never set — zero behavior change.

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

#### Integration points (via hook)

The consent module registers `_consent_hook` on each signal path. If the consent file is deleted, the hook is `None` and all signals pass through unconditionally.

- `get_logger()` — `if _consent_hook and not _consent_hook("logs", level): return`
- `@trace` decorator — `if _consent_hook and not _consent_hook("traces"): return noop_span`
- `counter()`/`gauge()`/`histogram()` — `if _consent_hook and not _consent_hook("metrics"): return`
- `bind_session_context()` / `bind_context()` — `if _consent_hook and not _consent_hook("context"): return`

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

#### Opt-in (via hook)

`PROVIDE_REDACTION_RECEIPTS=true` (default `false`). When enabled, the receipts module registers `_receipt_hook` on the PII engine. When disabled (or when the receipts file is deleted), `_receipt_hook` is `None` — PII engine skips receipt construction entirely, zero overhead.

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

### Performance & Size Overhead

#### Runtime cost when unconfigured (inert)

| Feature | Hot-path cost | Mechanism |
|---------|--------------|-----------|
| RuntimeOverrides | Zero | Type change only |
| Config masking | Zero | Only on repr/print |
| Classification | `if hook is not None` per PII-scanned field | ~1ns branch |
| Consent | `if hook is not None` per signal emission | ~1ns branch |
| Receipts | `if hook is not None` per redaction | ~1ns branch |

#### Runtime cost when active

| Feature | Cost | Notes |
|---------|------|-------|
| Classification | Enum lookup per field during PII traversal | No additional pass — piggybacks on existing traversal |
| Consent | Single enum comparison per signal | Fast-return on FULL (default) |
| Receipts | SHA-256 + HMAC per redacted field | Only for fields actually redacted, opt-in |

#### Code size per language

| Configuration | New LOC | New files | % increase over current ~2500 LOC |
|--------------|---------|-----------|-----------------------------------|
| Full install (all governance) | ~510-710 | 3 new + 4 modified | ~20-25% |
| Stripped (governance files deleted) | ~130-160 | 0 new + 4 modified | ~5-6% |
| Sub-project 1 only (no governance) | ~70-90 | 0 new + 3 modified | ~3% |

#### Strippability summary

To reduce footprint in space-restricted environments, delete these files per language:

- `classification.py` / `classification.go` / `classification.ts`
- `consent.py` / `consent.go` / `consent.ts`
- `receipts.py` / `receipts.go` / `receipts.ts`

Result: library works identically to pre-governance behavior. No runtime errors, no missing imports (handled by try/except in Python, compile-time in Go, tree shaking in TS). Only consumers that explicitly call governance APIs will see breakage (correct — they depend on a stripped feature).
