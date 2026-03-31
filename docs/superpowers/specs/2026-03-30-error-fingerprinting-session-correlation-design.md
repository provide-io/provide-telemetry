# Error Fingerprinting & Session Correlation Design

**Date:** 2026-03-30
**Status:** Draft

## Context

provide-telemetry has strong observability foundations but lacks two features that differentiate it from raw structlog + OTel: automatic error grouping and cross-service session tracking. Both are small additions (~60 lines total) that build on existing infrastructure.

## Feature 1: Structured Error Fingerprinting

### Problem

When the same error occurs across services or deploys, there's no stable identifier to group them. Backend deduplication (Sentry, Datadog) requires vendor lock-in. You can't `GROUP BY error_type` in a SQL-based observability tool because stack traces vary by deploy.

### Solution

A new structlog processor `add_error_fingerprint` generates a stable `error_fingerprint` field on error events.

**Fingerprint algorithm:**
1. Extract exception type name (e.g., `ValueError`, `TimeoutError`)
2. Extract top 3 stack frames as `filename:function_name` (no line numbers — those change between deploys)
3. Concatenate: `{exc_type}:{frame1}:{frame2}:{frame3}`
4. SHA256 hash, truncated to 12 hex chars

**Trigger condition:** Only fires when `exc_info`, `exc_name`, or `exception` is present in the event dict. Zero overhead on non-error paths.

**Output example:**
```json
{
  "event": "payment.charge.failed",
  "error_fingerprint": "a3f8c2d1e9b0",  <!-- pragma: allowlist secret -->
  "exc_name": "TimeoutError",
  "exc_info": "..."
}
```

### Files

- **Modify:** `src/provide/telemetry/logger/processors.py` — add `add_error_fingerprint` processor (~25 lines)
- **Modify:** `src/provide/telemetry/logger/core.py` — wire into processor chain after `add_standard_fields`, before `sanitize_sensitive_fields`
- **Add to spec:** `spec/telemetry-api.yaml` — `error_fingerprint` as an automatically-added field

### TypeScript parity

TypeScript implementation in `logger.ts` — same algorithm (SHA256 of `{type}:{frame1}:{frame2}:{frame3}`). Uses the `Error.stack` property to extract frames, normalized to match Python's `filename:function` format.

### Cross-language consistency

Both Python and TypeScript must produce identical fingerprints for equivalent errors:
- Same exception type + same call path = same fingerprint
- Frame format: `basename(filename):function_name` (no directory, no line number)
- Normalize: lowercase, strip file extensions

---

## Feature 2: Session Correlation

### Problem

`trace_id` tracks a single request. There's no built-in way to correlate all telemetry from a user's entire session (login → multiple requests → logout) across frontend and backend.

### Solution

Standardize `session_id` as a first-class context field that propagates via W3C baggage.

**Python API:**
```python
from provide.telemetry import bind_session_context, get_session_id

bind_session_context("user-session-abc123")
log.info("auth.login.success")  # automatically includes session_id
```

**TypeScript API:**
```typescript
import { bindSessionContext, getSessionId } from '@provide-io/telemetry';

bindSessionContext('user-session-abc123');
log.info({ event: 'auth.login.success' });  // automatically includes session_id
```

### Propagation

- Frontend sets `session_id` at initialization (explicit or auto-generated UUID)
- Frontend includes `session_id` in W3C `baggage` header on every request: `baggage: session_id=user-session-abc123`
- Backend ASGI middleware extracts `session_id` from baggage and auto-binds it to the request context
- All downstream logs/traces/metrics include `session_id` automatically

### Files

**Python:**
- **Modify:** `src/provide/telemetry/logger/context.py` — add `bind_session_context(session_id)`, `get_session_id()`, `clear_session_context()` using existing `_context_var` pattern (~15 lines)
- **Modify:** `src/provide/telemetry/asgi/middleware.py` — extract `session_id` from baggage header, call `bind_session_context` (~10 lines)
- **Modify:** `src/provide/telemetry/__init__.py` — export new functions

**TypeScript:**
- **Modify:** `typescript/src/context.ts` — add `bindSessionContext`, `getSessionId`, `clearSessionContext` (~15 lines)
- **Modify:** `typescript/src/index.ts` — export new functions

**Spec:**
- **Modify:** `spec/telemetry-api.yaml` — add `bind_session_context`, `get_session_id`, `clear_session_context` as required API surface

### ASGI middleware baggage extraction

The middleware already has access to request headers. Add:
```python
baggage = _extract_header(scope, "baggage")
if baggage:
    for pair in baggage.split(","):
        key, _, value = pair.strip().partition("=")
        if key == "session_id" and value:
            bind_session_context(value)
            break
```

---

## Testing

### Error Fingerprinting Tests
- Same exception type + same call path → same fingerprint (deterministic)
- Different call paths → different fingerprints
- Missing stack frames → graceful degradation (fewer frames in hash)
- Non-error events → no `error_fingerprint` field added (zero overhead)
- Cross-language: Python and TypeScript produce matching fingerprints for equivalent errors (E2E test)

### Session Correlation Tests
- `bind_session_context` → `get_session_id` roundtrip
- Session ID appears in log events after binding
- ASGI middleware extracts from baggage header
- `clear_session_context` removes it
- Async isolation: different tasks get different session IDs

## Verification

```bash
uv run python scripts/run_pytest_gate.py          # 100% coverage
uv run python spec/validate_conformance.py         # spec conformance
cd typescript && npm run test:coverage             # TS 100% coverage
```
