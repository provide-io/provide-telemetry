# TypeScript ALS Startup Guard — Design

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc

## Problem

`typescript/src/propagation.ts` falls back to a module-global `_fallbackStore` when
`AsyncLocalStorage` (ALS) is unavailable. In browsers this is safe — there is no
request concurrency. In Node.js, ALS is always available, so the fallback is never
reached in a correct configuration. However, if a bundler incorrectly strips
`node:async_hooks`, the fallback silently activates and concurrent requests share
propagation context — a request-isolation bug that is invisible until correlated log
events appear under the wrong request ID.

The current mitigation (`_warnFallbackOnce()` + exported `isFallbackMode()`) is
honest but easy to miss. The fix surfaces the problem at the one point every
Node.js application calls: `setupTelemetry()`.

## Decision

Throw a `ConfigurationError` from `setupTelemetry()` when both conditions hold:

1. `isFallbackMode()` returns `true` — ALS failed to load.
2. The runtime looks like Node.js — `process.versions.node` is a non-empty string.

Browser environments (no `process.versions.node`) keep the silent fallback
unchanged. The `isFallbackMode()` export and `_warnFallbackOnce` warning remain; the
check in `setupTelemetry()` is an additional hard gate, not a replacement.

## Files Changed

| File | Change |
|------|--------|
| `typescript/src/config.ts` | Add ALS guard block inside `setupTelemetry()`, after existing policy validation |
| `typescript/tests/config.test.ts` (or a new `als-guard.test.ts`) | Three new test cases (see Testing section) |

No changes to `propagation.ts`, `context.ts`, or any other module.

## Implementation

### Guard block in `setupTelemetry()` (`typescript/src/config.ts:296`)

Insert after the existing `applyConfigPolicies` / warn block:

```typescript
import { isFallbackMode } from './propagation';

// Inside setupTelemetry():
if (isFallbackMode()) {
  const isNodeLike =
    typeof process !== 'undefined' &&
    typeof process.versions === 'object' &&
    typeof process.versions.node === 'string';
  if (isNodeLike) {
    throw new ConfigurationError(
      'AsyncLocalStorage unavailable in a Node.js environment — ' +
      'concurrent requests would share propagation context. ' +
      'Check that node:async_hooks is not excluded from your bundler config.',
    );
  }
}
```

`ConfigurationError` is already used in `config.ts`. `isFallbackMode` is already
exported from `propagation.ts`; add it to the import list there.

### Node.js detection

`typeof process !== 'undefined' && typeof process.versions === 'object' && typeof process.versions.node === 'string'`

This is the canonical Node.js / Deno (which also exposes `process.versions.node`)
discriminator. Cloudflare Workers do not expose `process.versions.node`, so they
fall into the browser path and keep the silent fallback.

## Testing

Three cases, all using existing test helpers (`_disablePropagationALSForTest`,
`_restorePropagationALSForTest`, `resetTelemetryState`):

### Case 1 — Normal Node.js (baseline, already covered implicitly)

ALS is available → `setupTelemetry()` does not throw. Verified by every existing
test that calls `setupTelemetry()`. No new test required, but a dedicated assertion
makes the contract explicit.

### Case 2 — Node.js + ALS unavailable → hard fail

```typescript
it('throws ConfigurationError when ALS is unavailable in a Node.js environment', () => {
  const saved = _disablePropagationALSForTest();
  try {
    expect(() => setupTelemetry()).toThrow(ConfigurationError);
    expect(() => setupTelemetry()).toThrow(/AsyncLocalStorage unavailable/);
  } finally {
    _restorePropagationALSForTest(saved);
    resetTelemetryState();
  }
});
```

This test runs in the Node.js test runner where `process.versions.node` is always
set, so no process-object patching is needed.

### Case 3 — Browser simulation → silent fallback, no throw

```typescript
it('does not throw when ALS is unavailable in a non-Node environment', () => {
  const saved = _disablePropagationALSForTest();
  const realVersions = process.versions;
  // Simulate browser: remove process.versions.node
  Object.defineProperty(process, 'versions', { value: {}, configurable: true });
  try {
    expect(() => setupTelemetry()).not.toThrow();
    expect(isFallbackMode()).toBe(true);
  } finally {
    Object.defineProperty(process, 'versions', { value: realVersions, configurable: true });
    _restorePropagationALSForTest(saved);
    resetTelemetryState();
  }
});
```

## Error Handling

- The thrown `ConfigurationError` is the same type as all other configuration
  failures in the TS SDK — callers that already catch `ConfigurationError` from
  `setupTelemetry()` handle this automatically.
- No retry or recovery path is needed: the fix is a bundler configuration change,
  not a runtime-transient problem.

## What Does Not Change

- `propagation.ts` — no changes. `_fallbackStore`, `isFallbackMode()`,
  `_warnFallbackOnce()`, and all existing test helpers are untouched.
- `context.ts` and `tracing.ts` — their module-level fallbacks are out of scope.
  `context.ts` already has `runWithContext()` as the safe concurrent API.
- Browser behavior — silent fallback + one-time console warning remain unchanged.
- `isFallbackMode()` public export — remains available for application-level checks.

## Scope

Single file change + three test cases. No public API additions. No changes to
`propagation.ts`. Mutation kill and 100% branch coverage required per project
standards.
