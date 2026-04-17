# Cross-Language Parity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 verified cross-language parity bugs spanning the parity runner, TypeScript lifecycle/logging, Go lazy-init, Rust cold-field warnings, and documentation accuracy.

**Architecture:** Each task is independent and targets a specific file or small group of files. TypeScript has the most fixes (5 tasks) because its config/lifecycle state model has the most gaps. The parity runner and docs tasks are pure Python/Markdown.

**Tech Stack:** Python (parity runner), TypeScript (pino/config/runtime), Go (slog/config), Rust (runtime), Markdown (docs)

---

### Task 1: Fix parity runner normalizer dropping Go keys before rename

The `_normalize_log_record()` function checks the raw key against `_NOISE_FIELDS` *before* applying the rename, so `service.name` is dropped before it becomes the canonical `service`. The fix: remove the Go-style dotted keys from `_NOISE_FIELDS` since they're already handled by `_FIELD_RENAMES`.

**Files:**
- Modify: `spec/run_behavioral_parity.py:220-222`

- [ ] **Step 1: Fix `_NOISE_FIELDS` to not include renamed keys**

In `spec/run_behavioral_parity.py`, change `_NOISE_FIELDS` at line 220 to remove keys that are in `_FIELD_RENAMES`. Those keys get renamed to canonical names — they should survive normalization, not be dropped.

```python
# Fields to drop after renaming (pino metadata, structlog internals).
_NOISE_FIELDS: frozenset[str] = frozenset(
    {"pid", "hostname", "v", "event"}
)
```

The removed keys (`service.name`, `service.env`, `service.version`, `trace.id`, `span.id`) are all in `_FIELD_RENAMES` and will be renamed to their canonical form (`service`, `env`, `version`, `trace_id`, `span_id`). Previously they were dropped before the rename could take effect.

- [ ] **Step 2: Verify the fix logic**

Run:
```bash
uv run python -c "
from spec.run_behavioral_parity import _normalize_log_record
rec = {'service.name': 'probe', 'message': 'test', 'level': 'INFO', 'pid': 123}
result = _normalize_log_record(rec)
assert 'service' in result, f'service missing: {result}'
assert result['service'] == 'probe', f'wrong value: {result}'
assert 'pid' not in result, f'pid should be dropped: {result}'
print('OK:', result)
"
```

Expected: `OK: {'service': 'probe', 'message': 'test', 'level': 'INFO'}`

- [ ] **Step 3: Commit**

```bash
git add spec/run_behavioral_parity.py
git commit -m "fix(parity): stop dropping Go-style dotted keys before rename in normalizer"
```

---

### Task 2: Fix TypeScript `setupTelemetry()` to reset root logger and set `_activeConfig`

`setupTelemetry()` only updates `_config` but never sets `_activeConfig` and never resets the cached pino root logger. This causes two bugs: (a) `reloadRuntimeFromEnv()` skips cold-field drift detection, and (b) calling `getLogger()` before `setupTelemetry()` permanently caches stale identity.

**Files:**
- Modify: `typescript/src/config.ts:511-520`
- Modify: `typescript/src/config.ts` (add import)

- [ ] **Step 1: Add import for `_resetRootLogger`**

At the top of `typescript/src/config.ts`, add the import. Find the existing import block and add:

```typescript
import { _resetRootLogger } from './logger';
```

Note: check for circular dependency. `logger.ts` imports `getConfig` from `config.ts`, and now `config.ts` would import `_resetRootLogger` from `logger.ts`. This IS a circular dependency. To break it, we need a different approach.

Instead, we'll have `setupTelemetry()` set a version counter that `getRootLogger()` checks, so the root is lazily rebuilt on next access.

- [ ] **Step 2: Add config version counter to `config.ts`**

In `typescript/src/config.ts`, after `let _config: TelemetryConfig = { ...DEFAULTS };` (line 219), add:

```typescript
/** Incremented on every setupTelemetry() call so getRootLogger() knows to rebuild. */
let _configVersion = 0;

/** Return the current config version (used by logger to detect stale root). */
export function _getConfigVersion(): number {
  return _configVersion;
}
```

- [ ] **Step 3: Update `setupTelemetry()` to increment version and set `_activeConfig`**

In `typescript/src/config.ts`, modify `setupTelemetry()` at line 511:

```typescript
export function setupTelemetry(overrides?: Partial<TelemetryConfig>): void {
  _config = { ...configFromEnv(), ...overrides };
  _configVersion++;
  try {
    applyConfigPolicies(_config);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    setSetupError(message);
    console.warn(`setupTelemetry: applyConfigPolicies failed: ${message}`);
  }
}
```

- [ ] **Step 4: Update `_resetConfig()` to reset the version counter**

```typescript
export function _resetConfig(): void {
  _config = { ...DEFAULTS };
  _configVersion = 0;
}
```

- [ ] **Step 5: Update `getRootLogger()` in `logger.ts` to detect stale config**

In `typescript/src/logger.ts`, add import at the top:

```typescript
import { getConfig, _getConfigVersion } from './config';
```

Then modify `getRootLogger()` to track which config version the root was built with:

```typescript
let _rootConfigVersion = -1;

function getRootLogger(): pino.Logger {
  const currentVersion = _getConfigVersion();
  if (_root && _rootConfigVersion === currentVersion) return _root;
  _root = null; // Force rebuild
  _rootConfigVersion = currentVersion;
  // ... rest of the function unchanged
```

Also update `_resetRootLogger()`:

```typescript
export function _resetRootLogger(): void {
  _root = null;
  _rootConfigVersion = -1;
}
```

- [ ] **Step 6: Set `_activeConfig` from `setupTelemetry()`**

In `typescript/src/runtime.ts`, export a setter for `_activeConfig`:

```typescript
/** Called by setupTelemetry to keep _activeConfig in sync. */
export function _setActiveConfig(cfg: TelemetryConfig): void {
  _activeConfig = cfg;
}
```

In `typescript/src/config.ts`, import and call it:

```typescript
import { _setActiveConfig } from './runtime';
```

Update `setupTelemetry()`:

```typescript
export function setupTelemetry(overrides?: Partial<TelemetryConfig>): void {
  _config = { ...configFromEnv(), ...overrides };
  _configVersion++;
  _setActiveConfig(_config);
  try {
    applyConfigPolicies(_config);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    setSetupError(message);
    console.warn(`setupTelemetry: applyConfigPolicies failed: ${message}`);
  }
}
```

- [ ] **Step 7: Run TypeScript tests**

```bash
cd typescript && npx vitest run
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add typescript/src/config.ts typescript/src/logger.ts typescript/src/runtime.ts
git commit -m "fix(typescript): setupTelemetry sets _activeConfig and invalidates cached root logger"
```

---

### Task 3: Fix TypeScript `consoleOutput` default for local-dev parity

TypeScript defaults `consoleOutput: false`, making `setupTelemetry(); getLogger().info(...)` produce no visible output — unlike Python which always emits to stderr. Change the default to `true` to match Python's dual-emission behavior.

**Files:**
- Modify: `typescript/src/config.ts:184`
- Modify: `typescript/src/config.ts:337` (if `configFromEnv` also hardcodes it)

- [ ] **Step 1: Change the default**

In `typescript/src/config.ts`, change line 184 in the DEFAULTS object:

```typescript
  consoleOutput: true,
```

Also check `configFromEnv()` — if it hardcodes `consoleOutput: false`, change that too.

- [ ] **Step 2: Update the TS probe to not explicitly set `consoleOutput: false`**

In `spec/probes/emit_log_typescript.ts`, the probe sets `consoleOutput: false` at line 30. Since the probe captures output via its own custom stream (not console), this is fine — the probe's custom stream writes directly to stderr. But with the default now `true`, the write hook will also try to emit to console. The probe should keep `consoleOutput: false` to avoid double-output.

No change needed to the probe — it already explicitly sets `consoleOutput: false`.

- [ ] **Step 3: Run TypeScript tests**

```bash
cd typescript && npx vitest run
```

Expected: Tests pass. Some tests may need `consoleOutput: false` added if they were implicitly relying on the old default. Fix any failures by adding explicit `consoleOutput: false` to test configs that don't want console output.

- [ ] **Step 4: Commit**

```bash
git add typescript/src/config.ts
git commit -m "fix(typescript): default consoleOutput to true for local-dev parity with Python"
```

---

### Task 4: Fix TypeScript `shutdownTelemetry()` to clear `_activeConfig` and root logger

`shutdownTelemetry()` only clears provider registration state but doesn't clear `_activeConfig` or the cached root logger. After shutdown, `getRuntimeConfig()` still returns the pre-shutdown config and the logger still uses stale identity.

**Files:**
- Modify: `typescript/src/shutdown.ts:14-19`
- Modify: `typescript/src/runtime.ts:216-219`

- [ ] **Step 1: Expand `_clearProviderState()` to also clear `_activeConfig`**

In `typescript/src/runtime.ts`, modify `_clearProviderState()`:

```typescript
export function _clearProviderState(): void {
  _providersRegistered = false;
  _registeredProviders = [];
  _activeConfig = null;
}
```

- [ ] **Step 2: Import and call `_resetRootLogger` from shutdown**

In `typescript/src/shutdown.ts`, add:

```typescript
import { _clearProviderState, _getRegisteredProviders } from './runtime';
import { _resetRootLogger } from './logger';

export async function shutdownTelemetry(): Promise<void> {
  const providers = _getRegisteredProviders();
  await Promise.allSettled(providers.map((p) => p.forceFlush?.() ?? Promise.resolve()));
  await Promise.allSettled(providers.map((p) => p.shutdown?.() ?? Promise.resolve()));
  _clearProviderState();
  _resetRootLogger();
}
```

- [ ] **Step 3: Run TypeScript tests**

```bash
cd typescript && npx vitest run
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add typescript/src/shutdown.ts typescript/src/runtime.ts
git commit -m "fix(typescript): shutdownTelemetry clears _activeConfig and resets root logger"
```

---

### Task 5: Fix Go `GetLogger()` lazy-init to use `ConfigFromEnv()` instead of defaults

Go's `GetLogger()` calls `DefaultTelemetryConfig()` which ignores environment variables. Python's equivalent reads env vars during lazy init. Change Go to match.

**Files:**
- Modify: `go/logger.go:294-295`

- [ ] **Step 1: Change `GetLogger` to use `ConfigFromEnv`**

In `go/logger.go`, change line 295 from:

```go
cfg := DefaultTelemetryConfig()
```

to:

```go
cfg, err := ConfigFromEnv()
if err != nil {
    cfg = DefaultTelemetryConfig()
}
```

This matches Python's pattern: try env first, fall back to defaults on error.

- [ ] **Step 2: Run Go tests**

```bash
cd go && go test ./... -race -count=1
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add go/logger.go
git commit -m "fix(go): GetLogger reads env vars during lazy init instead of using hardcoded defaults"
```

---

### Task 6: Add cold-field-drift warning to Rust `reload_runtime_from_env()`

Python, TypeScript, and Go all warn when cold fields (service_name, environment, version, etc.) change during `reload_runtime_from_env()`. Rust silently overwrites them. Add the warning.

**Files:**
- Modify: `rust/src/runtime.rs:87-116`

- [ ] **Step 1: Add cold-field-drift detection**

In `rust/src/runtime.rs`, modify `reload_runtime_from_env()`:

```rust
pub fn reload_runtime_from_env() -> Result<TelemetryConfig, TelemetryError> {
    let fresh = TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?;
    let current = get_runtime_config()
        .ok_or_else(|| TelemetryError::new("telemetry not set up: call setup_telemetry first"))?;

    // Warn on cold-field drift (matches Python/TypeScript/Go behavior).
    let mut drifted: Vec<&str> = Vec::new();
    if current.service_name != fresh.service_name { drifted.push("service_name"); }
    if current.environment != fresh.environment { drifted.push("environment"); }
    if current.version != fresh.version { drifted.push("version"); }
    if current.tracing.enabled != fresh.tracing.enabled { drifted.push("tracing.enabled"); }
    if current.metrics.enabled != fresh.metrics.enabled { drifted.push("metrics.enabled"); }
    if !drifted.is_empty() {
        eprintln!(
            "[provide-telemetry] runtime.cold_field_drift: {} — restart required to apply",
            drifted.join(", ")
        );
    }

    let overrides = RuntimeOverrides {
        sampling: Some(fresh.sampling),
        backpressure: Some(fresh.backpressure),
        exporter: Some(fresh.exporter),
        security: Some(fresh.security),
        slo: Some(fresh.slo),
        pii_max_depth: Some(fresh.pii_max_depth),
        strict_schema: Some(fresh.strict_schema),
    };

    let mut next = update_runtime_config(overrides)?;
    next.service_name = current.service_name;
    next.environment = current.environment;
    next.version = current.version;
    next.logging.level = current.logging.level;
    next.logging.fmt = current.logging.fmt;
    next.logging.otlp_headers = current.logging.otlp_headers;
    next.tracing.enabled = current.tracing.enabled;
    next.tracing.otlp_headers = current.tracing.otlp_headers;
    next.metrics.enabled = current.metrics.enabled;
    next.metrics.otlp_headers = current.metrics.otlp_headers;

    set_active_config(Some(next.clone()));
    Ok(next)
}
```

- [ ] **Step 2: Run Rust tests**

```bash
cd rust && cargo test
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add rust/src/runtime.rs
git commit -m "fix(rust): add cold-field-drift warning to reload_runtime_from_env"
```

---

### Task 7: Rewrite parity probes to use public APIs

The TypeScript probe builds its own pino instance + makeWriteHook() instead of using `getLogger()`. The Go probe imports `go/logger` subpackage instead of the top-level telemetry package. Both should exercise the documented public API.

**Files:**
- Modify: `spec/probes/emit_log_typescript.ts`
- Modify: `spec/probes/emit_log_go/main.go`

- [ ] **Step 1: Rewrite TypeScript probe to use `getLogger()`**

Replace `spec/probes/emit_log_typescript.ts` with:

```typescript
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit one canonical JSON log line to stderr for cross-language parity checking.

import process from 'node:process';
import { setupTelemetry, getLogger } from '../../typescript/src/index.js';

const serviceName = process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] ?? 'probe';
const includeTimestamp = !['false', '0', 'no'].includes(
  (process.env['PROVIDE_LOG_INCLUDE_TIMESTAMP'] ?? '').toLowerCase(),
);

setupTelemetry({
  serviceName,
  environment: process.env['PROVIDE_TELEMETRY_ENVIRONMENT'] ?? '',
  version: process.env['PROVIDE_TELEMETRY_VERSION'] ?? '',
  logFormat: 'json',
  logLevel: 'info',
  logIncludeTimestamp: includeTimestamp,
  consoleOutput: false,
});

// Use the public API — getLogger() returns the canonical Logger interface.
const log = getLogger('probe');
log.info({ event: 'log.output.parity' }, 'log.output.parity');
```

Note: This requires the write hook to emit to stderr even when `consoleOutput` is false. Currently the hook only emits to console. For the parity probe, we need stdout/stderr output. The probe may need a different approach — check if the write hook supports an OTLP or file sink. If not, we need to add a stderr JSON sink to the write hook for `logFormat: 'json'` mode.

Actually, re-reading the write hook: when `consoleOutput` is false and no OTLP is configured, logs go nowhere. The probe needs console output to produce stderr output for the parity runner to capture. So the probe should set `consoleOutput: true` and the parity runner captures stderr.

Wait — pino in Node writes to its destination stream (which is the hook), and the hook decides where to emit. With `consoleOutput: true`, it emits via `console.log/error` which goes to stderr. That should work for parity capture.

Update the probe:

```typescript
setupTelemetry({
  serviceName,
  environment: process.env['PROVIDE_TELEMETRY_ENVIRONMENT'] ?? '',
  version: process.env['PROVIDE_TELEMETRY_VERSION'] ?? '',
  logFormat: 'json',
  logLevel: 'info',
  logIncludeTimestamp: includeTimestamp,
  consoleOutput: true,
});

const log = getLogger('probe');
log.info({ event: 'log.output.parity' }, 'log.output.parity');
```

However, the parity runner parses JSON from stderr. When `consoleOutput: true` with `logFormat: 'json'`, the hook calls `console.log(o)` which outputs `[Object object]` not JSON. It needs `logFormat: 'json'` to output `JSON.stringify(o)` — check the hook behavior.

Looking at `logger.ts:197-205`:
```typescript
if (cfg.consoleOutput) {
  const method = LEVEL_MAP[o['level'] as number] ?? 'log';
  if (cfg.logFormat === 'pretty') {
    (console as any)[method](formatPretty(o, supportsColor()));
  } else {
    (console as any)[method](o);
  }
}
```

The `else` branch calls `console[method](o)` with an object. In Node, `console.info({...})` outputs something like `{ service: 'probe', ... }` in Node's inspect format, NOT JSON. The parity runner expects parseable JSON.

So the public API path doesn't produce parseable JSON on stderr. The old probe worked around this by building a custom stream. We have two options:
1. Keep the custom stream approach but use `getLogger()` after setup
2. Fix the hook to output `JSON.stringify` for json format

Option 2 is the right fix — when `logFormat` is `'json'`, console output should be JSON-stringified. This is also arguably a bug in the logger.

- [ ] **Step 2: Fix the write hook JSON output**

In `typescript/src/logger.ts`, around line 197, change the non-pretty branch:

```typescript
if (cfg.consoleOutput) {
  const method = LEVEL_MAP[o['level'] as number] ?? 'log';
  if (cfg.logFormat === 'pretty') {
    (console as any)[method](formatPretty(o, supportsColor()));
  } else {
    (console as any)[method](JSON.stringify(o));
  }
}
```

- [ ] **Step 3: Rewrite Go probe to use top-level package**

Replace `spec/probes/emit_log_go/main.go`:

```go
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit one canonical JSON log line to stderr for cross-language parity checking.
package main

import (
	"context"
	"os"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	// Use the public API — SetupTelemetry reads env vars.
	_, _ = telemetry.SetupTelemetry()
	log := telemetry.GetLogger(context.Background(), "probe")
	log.Info("log.output.parity", "event", "log.output.parity")
	_ = os.Stderr.Sync()
}
```

Check the Go module path and imports. The top-level package may need `go/` prefix depending on module structure.

- [ ] **Step 4: Run parity check**

```bash
uv run python spec/run_behavioral_parity.py --check-output
```

Expected: All languages produce matching output.

- [ ] **Step 5: Commit**

```bash
git add spec/probes/emit_log_typescript.ts spec/probes/emit_log_go/main.go typescript/src/logger.ts
git commit -m "fix(parity): rewrite probes to use public APIs, fix JSON console output"
```

---

### Task 8: Update docs to match actual per-language setup signatures

`README.md:93` claims "All implementations export equivalent APIs" and `docs/API.md:13` documents `setup_telemetry(config)`, but Go uses `SetupTelemetry(opts...)` and Rust uses zero-arg `setup_telemetry()`.

**Files:**
- Modify: `README.md:91-106`
- Modify: `docs/API.md:13-15`

- [ ] **Step 1: Update README API surface table**

In `README.md`, change line 93 from:

```markdown
All implementations export equivalent APIs:
```

to:

```markdown
All implementations export equivalent APIs (signatures vary per language idiom):
```

- [ ] **Step 2: Add per-language signature note to `docs/API.md`**

After line 15 in `docs/API.md`, add a note:

```markdown
> **Per-language signatures:** Python accepts an optional `TelemetryConfig` object.
> TypeScript accepts `Partial<TelemetryConfig>` overrides merged over env config.
> Go reads env vars and accepts functional `SetupOption` arguments.
> Rust reads env vars with no programmatic config argument.
> All four read `PROVIDE_*` / `OTEL_*` environment variables as the primary config source.
```

- [ ] **Step 3: Update PARITY_ROADMAP.md lazy-init note**

In `docs/PARITY_ROADMAP.md`, update the lazy-init envelope drift note at line 29-30 to mark it as resolved (if Task 5 Go fix lands first) or note it's being addressed:

```markdown
- ~~Rust logger behavior still diverges on level filtering, strict-schema
  enforcement, required-key enforcement, and lazy-init envelope fields.~~ (resolved: level filtering, strict-schema, and envelope fields now aligned)
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/API.md docs/PARITY_ROADMAP.md
git commit -m "docs: clarify per-language setup signatures and update parity roadmap"
```

---

## Execution Order

Tasks 1-8 are mostly independent, but some natural ordering:

1. **Task 1** (parity runner fix) — standalone, no deps
2. **Task 2** (TS setupTelemetry/root logger) — foundational for Tasks 3, 4, 7
3. **Task 3** (TS consoleOutput default) — depends on Task 2
4. **Task 4** (TS shutdown reset) — depends on Task 2
5. **Task 5** (Go lazy-init) — standalone
6. **Task 6** (Rust cold-field warning) — standalone
7. **Task 7** (parity probes) — depends on Tasks 1, 2, 3
8. **Task 8** (docs) — do last, after code changes land

Parallelizable groups:
- Group A (independent): Tasks 1, 5, 6
- Group B (TS chain): Tasks 2 → 3 → 4
- Group C (after A+B): Task 7
- Group D (last): Task 8
