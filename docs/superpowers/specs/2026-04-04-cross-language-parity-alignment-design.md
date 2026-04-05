# Cross-Language Parity Alignment

**Date:** 2026-04-04
**Status:** Approved
**Scope:** Align observable behavior across Go, TypeScript, and Python implementations

## Problem

An audit of the three provide-telemetry implementations revealed 7 behavioral differences that go beyond language-idiomatic naming. These cause the same input to produce different output depending on which language is running — different PII fields redacted, different backpressure behavior under load, missing error fingerprints in Go logs, and different reconfiguration semantics.

## Scope Boundary

**In scope:** Observable behavior alignment — same input produces same output across all three languages.

**Out of scope:** Language-idiomatic API shapes (Go returning `bool` vs ticket struct, rule path syntax as tuple/string/slice, `Event` return types). These are fine as-is.

## Design

### 1. PII Alignment

**Current state:**
- Python: 5 default sensitive keys, 5 secret detection regex patterns, depth 8
- TypeScript: 11 default sensitive keys, 5 secret detection regex patterns, unlimited depth
- Go: 15 default sensitive keys, no secret detection, depth prunes at 1

**Changes:**

Canonical default sensitive key list (17 keys, union of all three):
```
password, passwd, secret, token, api_key, apikey, auth, authorization,
credential, private_key, ssn, credit_card, creditcard, cvv, pin,
account_number, cookie
```

Note: `email` from TypeScript's current list is excluded — email addresses are PII but are commonly needed in logs for user identification. Redacting by default would be surprising. Users who want email redaction can add a custom rule.

- **Python** (`src/provide/telemetry/pii.py`): Expand `_DEFAULT_SENSITIVE` from 5 to 17 keys
- **TypeScript** (`typescript/src/pii.ts`): Expand default list to 17 keys (add `credential`, `cvv`, `pin`, `account_number`, `apikey`, `creditcard`; remove `email`)  <!-- pragma: allowlist secret -->
- **Go** (`go/pii.go`): Add 5 secret detection regex patterns matching Python/TypeScript exactly:
  - `(?:AKIA|ASIA)[A-Z0-9]{16}` — AWS access key
  - `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` — JWT
  - `gh[pos]_[A-Za-z0-9_]{36,}` — GitHub token
  - `[0-9a-fA-F]{40,}` — Long hex string (40+ chars)
  - `[A-Za-z0-9+/]{40,}={0,2}` — Long base64 (40+ chars)
  - Minimum string length 20 before pattern matching (same as Python/TypeScript)
- **Go** (`go/pii.go`): Change depth pruning from 1 to configurable max depth (default 8, matching Python)

### 2. Backpressure Default Alignment

**Current state:** Go defaults to 1000 per-signal; TypeScript/Python default to 0 (unlimited).

**Change:** Set Go defaults to 0 (unlimited) to match TypeScript/Python.

- `go/config.go`: Change `DefaultTelemetryConfig()` queue sizes from 1000 to 0
- `go/backpressure.go`: Verify that 0 is handled as "unlimited" (no acquisition needed)
- Update tests that assert the 1000 default

Bounded queues become an explicit opt-in via `SetQueuePolicy()`.

### 3. Go Error Fingerprinting

**Current state:** Python/TypeScript compute `error_fingerprint` in the logger pipeline. Go has none.

**Algorithm** (must match Python/TypeScript exactly):
1. Input: exception type name (string) + top 3 stack frames
2. For each frame: extract `basename:function` (basename = filename without path/extension, lowercased; function = lowercased)
3. Join all parts with `:` separator: `exctype:base1:func1:base2:func2:base3:func3`
4. SHA-256 hash, take first 12 hex characters (lowercase)

**Implementation:**
- Add `_computeErrorFingerprint(excType string, pc uintptr) string` — uses `runtime.CallersFrames` to get frames from the program counter, applies the algorithm above
- Add `applyErrorFingerprint` method to `_telemetryHandler` — checks record attributes for `exc_info`, `exc_name`, or `exception` keys. If found, computes fingerprint and adds `error_fingerprint` attribute.
- Wire into `Handle` after `applyCallerFields`, before sampling
- If the file exceeds 500 LOC, extract to `go/fingerprint.go`

### 4. Go Required-Keys Schema Validation

**Current state:** Go's `applySchema` validates event name format only. Python/TypeScript also validate required keys.

**Change:**
- Add `ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error` to `go/schema.go`
- Returns `EventSchemaError` listing the first missing key
- Wire into `applySchema`: after `ValidateEventName` passes, call `ValidateRequiredKeys`
- Only enforced when `_strictSchema` is true (matching existing opt-in behavior)
- Verify `RequiredKeys []string` exists in Go's config; add if missing

### 5. Runtime Reconfigure Alignment

**Current state:** TypeScript throws `ConfigurationError` when provider-changing fields (otlpEndpoint, otlpHeaders) are modified after init. Go/Python allow full restart.

**Change:** TypeScript's `reconfigureTelemetry` calls `shutdownTelemetry()` then `setupTelemetry(proposed)` when provider-changing fields change, instead of throwing.

- `typescript/src/runtime.ts`: Replace the throw path with shutdown+reinit
- Keep `_areProvidersRegistered()` check to decide whether shutdown is needed (fast path for non-provider changes stays as-is)
- Update `typescript/tests/runtime.test.ts`: change assertions from "throws ConfigurationError" to "successfully reconfigures"

### 6. Parity Test Expansion

**A. Add 15 missing Go parity test cases** to `go/parity_test.go`:
- PII truncate: longer than limit (truncated + "..."), at limit (unchanged), shorter (unchanged), non-string conversion (4 cases)
- PII drop: key removed entirely (1 case)
- Propagation guards: baggage at limit (kept), baggage over limit (discarded), tracestate 32 pairs (kept), tracestate 33 pairs (discarded), traceparent at 512 (kept), traceparent over 512 (discarded) (6 cases)
- SLO classify: timeout by exc name, 200 = unknown, 301 = unknown, additional boundary (4 cases)

**B. New parity tests for fixed behaviors** (in all 3 languages):
- Secret detection: AWS key string → redacted; JWT → redacted; plain string → untouched
- Default sensitive keys: `cookie`, `cvv`, `pin` all redacted
- Backpressure default: `GetQueuePolicy` returns unlimited (0) for all signals
- Error fingerprint: `hash("valueerror")` → deterministic 12-char hex (same across langs)
- Required keys: strict mode drops event missing required key
- Reconfigure: changing otlpEndpoint after init succeeds (no error)

**C. Extend `spec/behavioral_fixtures.yaml`** with test vectors for:
- Secret detection patterns (input string → redacted/not-redacted)
- Canonical default sensitive key list
- Error fingerprint test vectors

### 7. OTLP Header `+` Parsing Alignment

**Current state:**
- Python (`config.py:412,415`): Uses `unquote_plus()` — treats `+` as space
- TypeScript (`config.ts:487,490`): Uses `.replace(/\+/g, ' ')` before `decodeURIComponent()` — treats `+` as space
- Go (`config.go:773,777`): Uses `url.QueryUnescape()` — preserves `+` as literal

**Canonical behavior:** `+` is literal. OTLP headers use standard percent-encoding (`%20` for spaces), not `application/x-www-form-urlencoded` form-encoding where `+` means space.

**Changes:**
- **Python** (`src/provide/telemetry/config.py`): Replace `unquote_plus(key.strip())` with `unquote(key.strip())` and `unquote_plus(raw.strip())` with `unquote(raw.strip())` (import `unquote` from `urllib.parse`)
- **TypeScript** (`typescript/src/config.ts`): Remove `.replace(/\+/g, ' ')` from both key and value decoding lines
- Go: No change needed
- **Fixtures** (`spec/behavioral_fixtures.yaml`): Update existing `config_headers` test vector — `"Authorization=Bearer+token"` expected output changes from `{"Authorization": "Bearer token"}` to `{"Authorization": "Bearer+token"}`; add new vector for `"a+b=c+d"` → `{"a+b": "c+d"}`

### 8. Go Backpressure 0 = Truly Unlimited

**Current state:** Go's `_buildQueue()` (`backpressure.go:30-35`) maps size≤0 to a buffered channel of size 1. Python/TypeScript return an unlimited sentinel (token=0) when size≤0.

**Change:**
- **Go** (`go/backpressure.go`): When size≤0, `_buildQueue()` returns `nil` (no channel). Adjust `Acquire()` to short-circuit with success when the channel is nil (unlimited). Adjust `Release()` to no-op when channel is nil.
- This aligns with Section 2's default change — once Go defaults to 0, it must actually mean unlimited.

### 9. Go Cardinality Input Validation

**Current state:**
- Go (`cardinality.go:43-50`): `SetCardinalityLimit()` stores values directly with no validation. Zero or negative `MaxValues`/`TTLSeconds` are accepted.
- Python (`cardinality.py:40`): Clamps `max_values=max(1, max_values)` and `ttl_seconds=max(1.0, ttl_seconds)`
- TypeScript (`cardinality.ts:23-26`): Clamps `Math.max(1, limit.maxValues)` and `Math.max(1, limit.ttlSeconds)`

**Change:**
- **Go** (`go/cardinality.go`): In `SetCardinalityLimit()`, clamp `limit.MaxValues` to `max(1, limit.MaxValues)` and `limit.TTLSeconds` to `max(1.0, limit.TTLSeconds)` before storing.

### 10. Sampling Signal Validation

**Current state:**
- Python (`sampling.py:44-47`): Validates signal against `_VALID_SIGNALS` frozenset, raises `ValueError` on unknown signal
- Go (`sampling.go`): No validation — accepts any string key, falls back silently
- TypeScript (`sampling.ts:37-42`): No validation — accepts any string, falls back to `DEFAULT_POLICY`

**Valid signals:** `"logs"`, `"traces"`, `"metrics"`

**Changes:**
- **Go** (`go/sampling.go`): Add signal validation in `ShouldSample()`, `SetSamplingPolicy()`, and `GetSamplingPolicy()`. Return error for unknown signals.
- **TypeScript** (`typescript/src/sampling.ts`): Add signal validation in `shouldSample()`, `setSamplingPolicy()`, and `getSamplingPolicy()`. Throw `ConfigurationError` for unknown signals.
- Python: No change needed

### 11. Go Event/EventName Strict Mode Consistency

**Current state:**
- Go (`schema.go:103-109`): `EventName()` always calls `validateSegments()` regardless of `_strictSchema`. `Event()` gates validation behind `_strictSchema`.
- Python (`events.py:105-111`): `event_name()` gates validation behind `_is_strict_event_name()`
- TypeScript (`schema.ts:79-93`): `eventName()` gates validation behind `getConfig().strictSchema`

**Change:**
- **Go** (`go/schema.go`): Gate `validateSegments()` in `EventName()` behind `_strictSchema` check, matching Python/TypeScript behavior. When strict mode is off, `EventName()` joins segments without validation.

### 12. Parity Test Expansion (Phase 2)

**New parity tests for fixed behaviors** (in all 3 languages):

- **Header `+` literal:** `"a+b=c+d"` → key `"a+b"`, value `"c+d"`
- **Header percent-space:** `"a%20b=c%20d"` → key `"a b"`, value `"c d"`
- **Backpressure unlimited:** `SetQueuePolicy(signal, 0)` then `Acquire()` → always succeeds (no blocking)
- **Cardinality clamping:** `RegisterCardinalityLimit(key, 0, 0)` → stored as `(1, 1.0)`
- **Sampling unknown signal:** `ShouldSample("invalid")` → error/exception
- **Sampling valid signals:** `ShouldSample("logs")`, `ShouldSample("traces")`, `ShouldSample("metrics")` → no error
- **Schema lenient mode:** `EventName("A","B","C")` with strict=false → succeeds (no validation)
- **Schema lenient mode:** `EventName("UPPER","case","ok")` with strict=false → succeeds

**Extend `spec/behavioral_fixtures.yaml`** with test vectors for all of the above.

## Risk Assessment

- **Section 1 (PII):** Low risk. Additive changes to Python/TypeScript key lists. Go secret detection is new code with clear test vectors.
- **Section 2 (Backpressure):** Low risk. Default change only; existing tests verify bounded behavior when explicitly configured.
- **Section 3 (Fingerprinting):** Medium risk. New Go code, but algorithm is well-specified with cross-language test vectors.
- **Section 4 (Required keys):** Low risk. Small addition to existing schema validation path.
- **Section 5 (Reconfigure):** Medium risk. Relaxing an unnecessary restriction in TypeScript — Go/Python already prove that shutdown+reinit is safe. Any TS consumers catching `ConfigurationError` from `reconfigureTelemetry` will see different control flow (success instead of error), but that's the intended improvement.
- **Section 6 (Tests):** No risk. Additive test coverage.
- **Section 7 (Header parsing):** Low risk. Small change to URL decoding in Python/TypeScript. Existing fixture must be updated — the `Bearer+token` test vector changes expected output.
- **Section 8 (Backpressure unlimited):** Low risk. Go-only change; Python/TypeScript already correct. Builds on Section 2.
- **Section 9 (Cardinality validation):** Low risk. Go-only, two lines of clamping.
- **Section 10 (Sampling validation):** Low risk. Additive validation in Go/TypeScript. May break callers passing invalid signal names — but those were bugs anyway.
- **Section 11 (Schema strict mode):** Low risk. Go-only, gating one function call behind existing flag.
- **Section 12 (Tests):** No risk. Additive test coverage.

## Success Criteria

1. All three languages redact the same 17 default sensitive keys
2. All three languages detect the same 5 secret patterns
3. Go logs include `error_fingerprint` matching Python/TypeScript output for same input
4. Go validates required keys in strict schema mode
5. `reconfigureTelemetry` with provider changes succeeds in all three languages
6. Default backpressure is unlimited in all three languages
7. Go parity tests: 39+ cases (up from 24)
8. All existing tests continue to pass
9. 100% Go coverage, 100% mutation efficacy maintained
10. OTLP header parsing preserves `+` as literal in all three languages
11. Go backpressure with size=0 is truly unlimited (acquire always succeeds)
12. Go cardinality limits clamped to min 1 / 1.0, matching Python/TypeScript
13. All three languages reject unknown sampling signal names
14. Go `EventName()` respects strict mode flag, matching Python/TypeScript
