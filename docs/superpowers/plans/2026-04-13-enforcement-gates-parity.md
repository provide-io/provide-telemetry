# Enforcement Gates Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire sampling, backpressure, and consent gates consistently into every signal hot path across TypeScript, Go, and Rust, and fix two TypeScript lifecycle defects (split-brain config state and shutdown not clearing provider registration).

**Architecture:** Each task is self-contained: write a failing test first, make it pass with the minimal code change, commit. No task depends on another's uncommitted changes. TypeScript and Go changes are additive (adding missing gate calls). Rust changes include both gate wiring and a module consolidation.

**Tech Stack:** TypeScript/vitest, Go stdlib testing, Rust cargo test.

---

## File Map

| File | Change |
|------|--------|
| `typescript/src/logger.ts` | Add `shouldSample` call to log write hook |
| `typescript/src/tracing.ts` | Add `shouldSample` + `tryAcquire`/`release` to `withTrace()` |
| `typescript/src/runtime.ts` | Add `_clearProviderState()` export; change `getRuntimeConfig()` fallback from `configFromEnv()` to `getConfig()` |
| `typescript/src/shutdown.ts` | Call `_clearProviderState()` after flushing/shutting down providers |
| `typescript/src/config.ts` | Fix `otelEnabled` JSDoc comment |
| `typescript/tests/logger.test.ts` | Add log-sampling gate test |
| `typescript/tests/tracing.test.ts` | Add consent/sampling/backpressure gate tests for traces |
| `typescript/tests/shutdown.test.ts` | Add provider-state-cleared-after-shutdown test |
| `typescript/tests/runtime.test.ts` | Add getRuntimeConfig-reflects-setupTelemetry test |
| `go/tracing.go` | Add `ShouldSample` + `TryAcquire`/`Release` to `Trace()` |
| `go/tracing_test.go` | Add sampling and backpressure gate tests |
| `rust/src/setup.rs` | Apply sampling, backpressure, and exporter policies from config after parse |
| `rust/src/tracer.rs` | Add `should_allow` consent gate to `trace()`; add `increment_emitted` call |
| `rust/src/tracing.rs` | Delegate `trace()` to `tracer::trace()` (remove duplicated logic) |
| `rust/src/logger.rs` | Add `increment_emitted` call in `log_event()` |
| `rust/tests/logger_test.rs` | Add consent-blocks-trace and health-counter tests |

---

## Task 1: TypeScript — Add sampling gate to log write hook

**Files:**
- Modify: `typescript/src/logger.ts`
- Modify: `typescript/tests/logger.test.ts`

- [ ] **Step 1: Write the failing test**

Open `typescript/tests/logger.test.ts`. Add at the end of the file, inside the appropriate describe block or at top level:

```typescript
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling';

describe('makeWriteHook — sampling gate', () => {
  beforeEach(() => {
    _resetSamplingForTests();
    _resetConfig();
    _resetRootLogger();
    setupTelemetry({ serviceName: 'test-svc', logLevel: 'debug', captureToWindow: true });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
  });

  afterEach(() => {
    _resetSamplingForTests();
  });

  it('drops log records when logs sampling rate is 0', () => {
    setSamplingPolicy('logs', { defaultRate: 0, overrides: {} });
    const hook = makeWriteHook();
    hook({ level: 30, message: 'should.be.dropped' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(0);
  });

  it('passes log records when logs sampling rate is 1', () => {
    setSamplingPolicy('logs', { defaultRate: 1, overrides: {} });
    const hook = makeWriteHook();
    hook({ level: 30, message: 'should.pass' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd typescript && npm test -- logger.test.ts 2>&1 | tail -20
```

Expected: test fails because sampling gate is absent — both cases pass records regardless of rate.

- [ ] **Step 3: Add the `shouldSample` import and gate to `logger.ts`**

In `typescript/src/logger.ts`, add `shouldSample` to the sampling import. The file already has no sampling import, so add a new import line after the `shouldAllow` import:

```typescript
import { shouldSample } from './sampling';
```

Then in `makeWriteHook()`, add the sampling gate immediately after the consent gate (before `tryAcquire`):

```typescript
    // Consent gate: drop records the current consent level forbids.
    const levelLabel = CONSENT_LEVEL_MAP[o['level'] as number] ?? 'info';
    if (!shouldAllow('logs', levelLabel)) return;

    // Sampling gate: probabilistically drop records based on configured rate.
    if (!shouldSample('logs')) return;

    // Backpressure gate: drop when the log queue is full.
    const ticket = tryAcquire('logs');
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd typescript && npm test -- logger.test.ts 2>&1 | tail -20
```

Expected: PASS — sampling rate 0 drops records, rate 1 passes them.

- [ ] **Step 5: Run full TypeScript suite to check for regressions**

```bash
cd typescript && npm test 2>&1 | tail -20
```

Expected: all tests pass (or same count as before).

- [ ] **Step 6: Commit**

```bash
git add typescript/src/logger.ts typescript/tests/logger.test.ts
git commit -m "fix(ts): add sampling gate to log write hook"
```

---

## Task 2: TypeScript — Add sampling and backpressure to trace hot path

**Files:**
- Modify: `typescript/src/tracing.ts`
- Modify: `typescript/tests/tracing.test.ts`

- [ ] **Step 1: Write the failing tests**

Open `typescript/tests/tracing.test.ts`. Add the following imports at the top (alongside existing imports):

```typescript
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling';
import { _resetBackpressureForTests, setQueuePolicy } from '../src/backpressure';
import { resetConsentForTests, setConsentLevel } from '../src/consent';
import { _resetConfig, setupTelemetry } from '../src/config';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';
```

Add a `beforeEach` / `afterEach` block and the following tests:

```typescript
beforeEach(() => {
  _resetConfig();
  _resetSamplingForTests();
  _resetBackpressureForTests();
  resetConsentForTests();
  _resetHealthForTests();
  setupTelemetry({ serviceName: 'test-svc' });
});

afterEach(() => {
  _resetSamplingForTests();
  _resetBackpressureForTests();
  resetConsentForTests();
});

describe('withTrace — enforcement gates', () => {
  it('does not count emission when consent is NONE', () => {
    setConsentLevel('none');
    let called = false;
    withTrace('test.span', () => { called = true; });
    expect(called).toBe(true); // fn still runs
    expect(getHealthSnapshot().emitted_traces).toBe(0);
  });

  it('does not count emission when sampling rate is 0', () => {
    setSamplingPolicy('traces', { defaultRate: 0, overrides: {} });
    let called = false;
    withTrace('test.span', () => { called = true; });
    expect(called).toBe(true); // fn still runs (pass-through)
    expect(getHealthSnapshot().emitted_traces).toBe(0);
  });

  it('counts emission when sampling rate is 1', () => {
    setSamplingPolicy('traces', { defaultRate: 1, overrides: {} });
    withTrace('test.span', () => {});
    expect(getHealthSnapshot().emitted_traces).toBe(1);
  });

  it('does not count emission when backpressure queue is full', () => {
    setQueuePolicy({ maxLogs: 0, maxTraces: 1, maxMetrics: 0 });
    // Acquire the only slot to fill the queue
    const { tryAcquire, release } = await import('../src/backpressure');
    const ticket = tryAcquire('traces');
    expect(ticket).toBeTruthy();
    let called = false;
    withTrace('test.span', () => { called = true; });
    expect(called).toBe(true); // fn still runs
    expect(getHealthSnapshot().emitted_traces).toBe(0);
    release(ticket!);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd typescript && npm test -- tracing.test.ts 2>&1 | tail -20
```

Expected: the sampling and backpressure tests fail (no gate present in withTrace).

- [ ] **Step 3: Add `shouldSample` and backpressure imports and gates to `tracing.ts`**

In `typescript/src/tracing.ts`, add to the existing imports:

```typescript
import { shouldSample } from './sampling';
import { tryAcquire, release } from './backpressure';
```

Rewrite `withTrace()` to add the two new gates. The consent check stays first; sampling and backpressure are added after, with the fn() pass-through on gate failure:

```typescript
export function withTrace<T>(name: string, fn: () => T): T {
  if (!shouldAllow('traces')) return fn();
  if (!shouldSample('traces', name)) return fn();
  const ticket = tryAcquire('traces');
  if (!ticket) return fn();

  const tracer = trace.getTracer(TRACER_NAME);

  try {
    const activeCtx = getActiveOtelContext();
    if (activeCtx) {
      return otelContext.with(activeCtx as ReturnType<typeof otelContext.active>, () =>
        tracer.startActiveSpan(name, (span: Span) => {
          // Stryker disable next-line ConditionalExpression: noop detection is not observable without SDK — branch outcome equivalent under mutation
          /* v8 ignore start: noop-span false branch + real-span return are unreachable without a registered OTel provider */
          if (_isNoopSpan(span)) return _withSyntheticIds(() => _spanHandler(fn, span));
          return _spanHandler(fn, span);
          /* v8 ignore stop */
        }),
      );
    }
  } catch {
    // Graceful degradation — fall through to default behaviour.
  } finally {
    release(ticket);
  }

  return tracer.startActiveSpan(name, (span: Span) => {
    try {
      // Stryker disable next-line ConditionalExpression: noop detection is not observable without SDK — branch outcome equivalent under mutation
      if (_isNoopSpan(span)) return _withSyntheticIds(() => _spanHandler(fn, span));
      return _spanHandler(fn, span);
    } finally {
      release(ticket);
    }
  });
}
```

> **Note:** The `release(ticket)` must fire exactly once. The `try/catch/finally` around the `getActiveOtelContext()` branch releases on that path; the `startActiveSpan` branch has its own `finally`. If `getActiveOtelContext()` doesn't throw, it returns (releasing in its finally) and the second `startActiveSpan` is never reached.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd typescript && npm test -- tracing.test.ts 2>&1 | tail -20
```

Expected: all tracing tests pass.

- [ ] **Step 5: Run full suite**

```bash
cd typescript && npm test 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add typescript/src/tracing.ts typescript/tests/tracing.test.ts
git commit -m "fix(ts): add sampling and backpressure gates to withTrace()"
```

---

## Task 3: TypeScript — Fix getRuntimeConfig split-brain

**Files:**
- Modify: `typescript/src/runtime.ts`
- Modify: `typescript/tests/runtime.test.ts`

**Problem:** `setupTelemetry({ serviceName: 'x' })` writes `_config` in `config.ts`. `getRuntimeConfig()` reads `_activeConfig ?? configFromEnv()` — after a plain `setupTelemetry()` call, `_activeConfig` is null so it re-parses env and misses the override. Fix: fall back to `getConfig()` (the live `_config`) instead of re-parsing env.

- [ ] **Step 1: Write the failing test**

Open `typescript/tests/runtime.test.ts`. Add to the `describe('getRuntimeConfig')` block:

```typescript
  it('reflects values set via setupTelemetry() without needing updateRuntimeConfig()', () => {
    _resetRuntimeForTests();
    _resetConfig();
    setupTelemetry({ serviceName: 'injected-service', logLevel: 'debug' });
    const cfg = getRuntimeConfig();
    expect(cfg.serviceName).toBe('injected-service');
    expect(cfg.logLevel).toBe('debug');
  });
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd typescript && npm test -- runtime.test.ts 2>&1 | grep -A5 "injected-service\|FAIL"
```

Expected: FAIL — `getRuntimeConfig()` returns `'provide-service'` (the env default), not `'injected-service'`.

- [ ] **Step 3: Fix `getRuntimeConfig()` in `runtime.ts`**

In `typescript/src/runtime.ts`, add `getConfig` to the import from `./config`:

```typescript
import {
  type RuntimeOverrides,
  type TelemetryConfig,
  configFromEnv,
  getConfig,
  setupTelemetry,
} from './config';
```

Change the fallback in `getRuntimeConfig()` from `configFromEnv()` to `getConfig()`:

```typescript
export function getRuntimeConfig(): Readonly<TelemetryConfig> {
  const cfg = _activeConfig ?? getConfig();
  return deepFreeze({ ...cfg });
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd typescript && npm test -- runtime.test.ts 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
cd typescript && npm test 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add typescript/src/runtime.ts typescript/tests/runtime.test.ts
git commit -m "fix(ts): getRuntimeConfig falls back to live config instead of re-parsing env"
```

---

## Task 4: TypeScript — Fix shutdown not clearing provider state

**Files:**
- Modify: `typescript/src/runtime.ts`
- Modify: `typescript/src/shutdown.ts`
- Modify: `typescript/tests/shutdown.test.ts`

**Problem:** After `shutdownTelemetry()`, `_areProvidersRegistered()` stays `true` and `reconfigureTelemetry({ otelEnabled: true })` is still rejected. Fix: export a function to clear the flag and registered list, call it from shutdown.

- [ ] **Step 1: Write the failing test**

Open `typescript/tests/shutdown.test.ts`. Add after the existing tests:

```typescript
import {
  _areProvidersRegistered,
  _markProvidersRegistered,
  _resetRuntimeForTests,
  _storeRegisteredProviders,
} from '../src/runtime';
import { reconfigureTelemetry } from '../src/runtime';
import { _resetConfig } from '../src/config';

describe('shutdownTelemetry — clears provider registration state', () => {
  beforeEach(() => {
    _resetRuntimeForTests();
    _resetConfig();
  });
  afterEach(() => {
    _resetRuntimeForTests();
  });

  it('clears _providersRegistered after shutdown', async () => {
    _markProvidersRegistered();
    expect(_areProvidersRegistered()).toBe(true);
    await shutdownTelemetry();
    expect(_areProvidersRegistered()).toBe(false);
  });

  it('clears registered provider list after shutdown', async () => {
    _storeRegisteredProviders([{ shutdown: vi.fn() }]);
    await shutdownTelemetry();
    expect(_getRegisteredProviders()).toHaveLength(0);
  });

  it('allows provider-changing reconfigureTelemetry after shutdown', async () => {
    _markProvidersRegistered();
    await shutdownTelemetry();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd typescript && npm test -- shutdown.test.ts 2>&1 | tail -20
```

Expected: FAIL — `_areProvidersRegistered()` is still `true` after shutdown.

- [ ] **Step 3: Add `_clearProviderState()` to `runtime.ts`**

In `typescript/src/runtime.ts`, add the new export:

```typescript
/** Clear provider registration state. Called by shutdownTelemetry after flush/shutdown. */
export function _clearProviderState(): void {
  _providersRegistered = false;
  _registeredProviders = [];
}
```

- [ ] **Step 4: Call `_clearProviderState()` from `shutdown.ts`**

In `typescript/src/shutdown.ts`, update the import and add the call:

```typescript
import { _clearProviderState, _getRegisteredProviders } from './runtime';

export async function shutdownTelemetry(): Promise<void> {
  const providers = _getRegisteredProviders();
  await Promise.allSettled(providers.map((p) => p.forceFlush?.() ?? Promise.resolve()));
  await Promise.allSettled(providers.map((p) => p.shutdown?.() ?? Promise.resolve()));
  _clearProviderState();
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd typescript && npm test -- shutdown.test.ts 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
cd typescript && npm test 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add typescript/src/runtime.ts typescript/src/shutdown.ts typescript/tests/shutdown.test.ts
git commit -m "fix(ts): shutdownTelemetry clears provider registration state"
```

---

## Task 5: TypeScript — Fix otelEnabled comment

**Files:**
- Modify: `typescript/src/config.ts`

- [ ] **Step 1: Fix the misleading JSDoc**

In `typescript/src/config.ts`, find the `otelEnabled` field and update its comment:

Old:
```typescript
  /** Enable OTEL SDK registration on setupTelemetry(). */
  otelEnabled: boolean;
```

New:
```typescript
  /** When true, registerOtelProviders() will install OTEL SDK providers. setupTelemetry() stores this flag but does not register providers itself. */
  otelEnabled: boolean;
```

- [ ] **Step 2: Verify no test breaks**

```bash
cd typescript && npm test 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add typescript/src/config.ts
git commit -m "docs(ts): clarify otelEnabled — registration requires explicit registerOtelProviders() call"
```

---

## Task 6: Go — Add sampling and backpressure to Trace()

**Files:**
- Modify: `go/tracing.go`
- Modify: `go/tracing_test.go`

The current `Trace()` function only checks `ShouldAllow`. It needs `ShouldSample` (probabilistic drop) and `TryAcquire`/`Release` (backpressure).

- [ ] **Step 1: Write the failing tests**

Open `go/tracing_test.go`. Add:

```go
// ── Trace() enforcement gate tests ───────────────────────────────────────────

func TestTrace_ConsentNone_FnStillRuns(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentNone)

	ran := false
	err := Trace(context.Background(), "test.span", func(_ context.Context) error {
		ran = true
		return nil
	})
	if !ran {
		t.Error("expected fn to run even when consent is NONE")
	}
	if err != nil {
		t.Errorf("unexpected error: %v", err)
	}
}

func TestTrace_SamplingZero_FnStillRuns(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)
	_, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 0})
	if err != nil {
		t.Fatal(err)
	}

	ran := false
	_ = Trace(context.Background(), "test.span", func(_ context.Context) error {
		ran = true
		return nil
	})
	if !ran {
		t.Error("expected fn to run even when sampling rate is 0")
	}
}

func TestTrace_SamplingOne_RecordsEmission(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)
	_resetBackpressureForTests()
	t.Cleanup(_resetBackpressureForTests)

	_, _ = SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 1.0})
	SetConsentLevel(ConsentFull)

	_ = Trace(context.Background(), "test.span", func(_ context.Context) error { return nil })

	snap := GetHealthSnapshot()
	if snap.EmittedTraces == 0 {
		t.Error("expected EmittedTraces > 0 after Trace() with sampling=1")
	}
}

func TestTrace_BackpressureFull_FnStillRuns(t *testing.T) {
	_resetBackpressureForTests()
	t.Cleanup(_resetBackpressureForTests)
	SetQueuePolicy(QueuePolicy{TracesMaxSize: 1})
	// Occupy the only slot
	ok := TryAcquire(signalTraces)
	if !ok {
		t.Fatal("could not acquire initial trace slot")
	}
	defer Release(signalTraces)

	ran := false
	_ = Trace(context.Background(), "test.span", func(_ context.Context) error {
		ran = true
		return nil
	})
	if !ran {
		t.Error("expected fn to run even under full backpressure")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd go && go test -run "TestTrace_Sampling\|TestTrace_Backpressure\|TestTrace_Consent" -v 2>&1 | tail -30
```

Expected: sampling and backpressure tests fail (or panic) because neither gate exists in `Trace()`.

- [ ] **Step 3: Add gates to `Trace()` in `go/tracing.go`**

Replace the current `Trace()` function:

```go
// Trace wraps fn in a span using DefaultTracer.
// fn receives the context enriched with trace/span IDs.
// If fn returns an error, the error is recorded on the span before it ends.
// Consent, sampling, and backpressure are applied before starting the span;
// fn is still invoked (without a span) when any gate rejects.
func Trace(ctx context.Context, name string, fn func(context.Context) error) error {
	if !ShouldAllow(signalTraces, "") {
		return fn(ctx)
	}
	if sampled, _ := ShouldSample(signalTraces, name); !sampled {
		return fn(ctx)
	}
	if !TryAcquire(signalTraces) {
		return fn(ctx)
	}
	defer Release(signalTraces)

	spanCtx, span := DefaultTracer.Start(ctx, name)
	defer span.End()
	err := fn(spanCtx)
	if err != nil {
		span.RecordError(err)
	}
	return err
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd go && go test -run "TestTrace_" -v 2>&1 | tail -30
```

Expected: all `TestTrace_*` tests pass.

- [ ] **Step 5: Run full Go suite**

```bash
cd go && go test ./... -count=1 2>&1 | tail -10
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add go/tracing.go go/tracing_test.go
git commit -m "fix(go): add sampling and backpressure gates to Trace()"
```

---

## Task 7: Rust — Apply config to policy stores in setup_telemetry()

**Files:**
- Modify: `rust/src/setup.rs`
- Modify: `rust/tests/integration_test.rs` (or add `rust/tests/setup_test.rs`)

**Problem:** `setup_telemetry()` stores config in `ACTIVE_CONFIG` but never calls `set_sampling_policy()`, `set_queue_policy()`, or `set_exporter_policy()`. The policy engines use their defaults (rate 1.0, unlimited queue) regardless of config values.

- [ ] **Step 1: Write the failing test**

Add to `rust/tests/integration_test.rs` (or create `rust/tests/setup_test.rs`):

```rust
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use std::sync::{Mutex, OnceLock};

use provide_telemetry::{
    get_sampling_policy, setup_telemetry, shutdown_telemetry, Signal, TelemetryConfig,
    SamplingConfig,
};

static SETUP_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn setup_lock() -> &'static Mutex<()> {
    SETUP_LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn setup_test_sampling_policy_applied_from_config() {
    let _guard = setup_lock().lock().expect("setup lock");
    let _ = shutdown_telemetry(); // ensure clean state

    // Build config with logs_rate = 0.25
    let mut config = TelemetryConfig::default();
    config.sampling = SamplingConfig {
        logs_rate: 0.25,
        traces_rate: 0.5,
        metrics_rate: 0.75,
    };

    // Override env-derived config by calling setup with a pre-built config.
    // (setup_telemetry reads from env; we test by inspecting policy after setup)
    // Set env vars to drive the rates, then call setup_telemetry().
    std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0.25");
    std::env::set_var("PROVIDE_SAMPLING_TRACES_RATE", "0.5");
    let _ = setup_telemetry();

    let logs_policy = get_sampling_policy(Signal::Logs).expect("logs policy");
    assert!(
        (logs_policy.default_rate - 0.25).abs() < 1e-9,
        "expected logs rate 0.25, got {}",
        logs_policy.default_rate
    );

    let traces_policy = get_sampling_policy(Signal::Traces).expect("traces policy");
    assert!(
        (traces_policy.default_rate - 0.5).abs() < 1e-9,
        "expected traces rate 0.5, got {}",
        traces_policy.default_rate
    );

    let _ = shutdown_telemetry();
    std::env::remove_var("PROVIDE_SAMPLING_LOGS_RATE");
    std::env::remove_var("PROVIDE_SAMPLING_TRACES_RATE");
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd rust && cargo test setup_test_sampling_policy_applied -- --nocapture 2>&1 | tail -20
```

Expected: FAIL — the policy rate is 1.0 (default) instead of the configured 0.25.

- [ ] **Step 3: Add policy application to `setup.rs`**

In `rust/src/setup.rs`, add imports:

```rust
use crate::backpressure::{set_queue_policy, QueuePolicy};
use crate::resilience::{set_exporter_policy, ExporterPolicy};
use crate::sampling::{set_sampling_policy, SamplingPolicy, Signal};
```

Add a helper function and call it in `setup_telemetry()`:

```rust
fn apply_policies(config: &TelemetryConfig) {
    let _ = set_sampling_policy(
        Signal::Logs,
        SamplingPolicy { default_rate: config.sampling.logs_rate, overrides: std::collections::BTreeMap::new() },
    );
    let _ = set_sampling_policy(
        Signal::Traces,
        SamplingPolicy { default_rate: config.sampling.traces_rate, overrides: std::collections::BTreeMap::new() },
    );
    let _ = set_sampling_policy(
        Signal::Metrics,
        SamplingPolicy { default_rate: config.sampling.metrics_rate, overrides: std::collections::BTreeMap::new() },
    );
    set_queue_policy(QueuePolicy {
        logs_maxsize: config.backpressure.logs_maxsize,
        traces_maxsize: config.backpressure.traces_maxsize,
        metrics_maxsize: config.backpressure.metrics_maxsize,
    });
    let _ = set_exporter_policy(
        Signal::Logs,
        ExporterPolicy {
            retries: config.exporter.logs_retries as u32,
            backoff_seconds: config.exporter.logs_backoff_seconds,
            timeout_seconds: config.exporter.logs_timeout_seconds,
            fail_open: config.exporter.logs_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    let _ = set_exporter_policy(
        Signal::Traces,
        ExporterPolicy {
            retries: config.exporter.traces_retries as u32,
            backoff_seconds: config.exporter.traces_backoff_seconds,
            timeout_seconds: config.exporter.traces_timeout_seconds,
            fail_open: config.exporter.traces_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
    let _ = set_exporter_policy(
        Signal::Metrics,
        ExporterPolicy {
            retries: config.exporter.metrics_retries as u32,
            backoff_seconds: config.exporter.metrics_backoff_seconds,
            timeout_seconds: config.exporter.metrics_timeout_seconds,
            fail_open: config.exporter.metrics_fail_open,
            allow_blocking_in_event_loop: false,
        },
    );
}
```

Then call it inside `setup_telemetry()` before `set_active_config`:

```rust
pub fn setup_telemetry() -> Result<TelemetryConfig, TelemetryError> {
    let mut state = setup_state().lock().expect("setup state lock poisoned");
    if state.done {
        return get_runtime_config()
            .ok_or_else(|| TelemetryError::new("telemetry setup state is inconsistent"));
    }

    let config = TelemetryConfig::from_env().map_err(|err| TelemetryError::new(err.message))?;
    setup_otel(&config)?;
    apply_policies(&config);          // <-- NEW
    set_active_config(Some(config.clone()));
    state.done = true;
    Ok(config)
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd rust && cargo test setup_test_sampling_policy_applied -- --nocapture 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 5: Run full Rust suite**

```bash
cd rust && cargo test 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add rust/src/setup.rs rust/tests/integration_test.rs
git commit -m "fix(rust): apply sampling, backpressure, and exporter policies in setup_telemetry()"
```

---

## Task 8: Rust — Add consent gate to tracer::trace() and consolidate modules

**Files:**
- Modify: `rust/src/tracer.rs`
- Modify: `rust/src/tracing.rs`
- Modify: `rust/tests/logger_test.rs`

**Problem:** `tracer::trace()` (the publicly re-exported function) starts spans without checking `should_allow`. `tracing::trace()` has the consent check but is a duplicate surface. Fix: add the consent check to `tracer::trace()`, then make `tracing::trace()` delegate to it to remove the duplication.

- [ ] **Step 1: Write the failing test**

Open `rust/tests/logger_test.rs`. Add (using the existing lock pattern):

```rust
#[cfg(feature = "governance")]
#[test]
fn tracer_test_consent_none_blocks_span_but_runs_fn() {
    use provide_telemetry::{reset_consent_for_tests, set_consent_level, ConsentLevel};
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    reset_consent_for_tests();

    set_consent_level(ConsentLevel::None);

    let mut ran = false;
    let result = provide_telemetry::trace("test.span", || {
        ran = true;
        42_i32
    });

    assert!(ran, "fn should run even when consent is None");
    assert_eq!(result, 42);

    // Verify no trace context was set (no span was started)
    let ctx = provide_telemetry::get_trace_context();
    // When consent blocks, no trace_id should be injected from this call
    // (context may have a prior value; we check nothing was pushed by this call)
    // Reset to confirm
    reset_consent_for_tests();
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd rust && cargo test tracer_test_consent_none_blocks_span -- --nocapture 2>&1 | tail -20
```

Expected: test still passes (fn runs) but the span IS started — we can't verify consent blocking yet because the gate is absent. The test may pass trivially. Adjust: check that a span was NOT created by inspecting the tracer counter before and after.

Update the test to verify consent blocked the span start:

```rust
#[cfg(feature = "governance")]
#[test]
fn tracer_test_consent_none_skips_span_creation() {
    use provide_telemetry::{reset_consent_for_tests, set_consent_level, ConsentLevel, get_health_snapshot};
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    reset_consent_for_tests();

    set_consent_level(ConsentLevel::None);
    let before = get_health_snapshot().emitted_traces;

    let _ = provide_telemetry::trace("test.span", || 42_i32);

    let after = get_health_snapshot().emitted_traces;
    assert_eq!(before, after, "emitted_traces should not increase when consent is None");

    reset_consent_for_tests();
}
```

- [ ] **Step 3: Add consent gate and health increment to `tracer.rs::trace()`**

In `rust/src/tracer.rs`, add the imports:

```rust
use crate::health::increment_emitted;
use crate::sampling::Signal;
```

For the consent import, add conditionally (the governance feature is default-enabled but guard for safety):

```rust
#[cfg(feature = "governance")]
use crate::consent::should_allow;
```

Update the `trace()` function:

```rust
pub fn trace<T, F>(name: &str, callback: F) -> T
where
    F: FnOnce() -> T,
{
    #[cfg(feature = "governance")]
    if !should_allow("traces", None) {
        return callback();
    }
    let _span = tracer.start_span(name);
    increment_emitted(Signal::Traces, 1);
    callback()
}
```

- [ ] **Step 4: Simplify `tracing.rs::trace()` to delegate**

In `rust/src/tracing.rs`, replace the duplicated `trace()` implementation:

```rust
pub fn trace<T, F>(name: &str, callback: F) -> T
where
    F: FnOnce() -> T,
{
    crate::tracer::trace(name, callback)
}
```

Remove the now-unused imports from `tracing.rs` (`should_allow` and the context imports it needed for its own implementation). Keep `get_tracer`, `set_trace_context`, `get_trace_context`, and the `Tracer` struct re-exports as they were.

- [ ] **Step 5: Run test to verify it passes**

```bash
cd rust && cargo test tracer_test_consent_none_skips_span -- --nocapture 2>&1 | tail -20
```

Expected: PASS — `emitted_traces` stays the same when consent is None.

- [ ] **Step 6: Run full suite**

```bash
cd rust && cargo test 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add rust/src/tracer.rs rust/src/tracing.rs rust/tests/logger_test.rs
git commit -m "fix(rust): add consent gate to tracer::trace(); consolidate tracing::trace() delegation"
```

---

## Task 9: Rust — Add health counter increments to logger and tracer

**Files:**
- Modify: `rust/src/logger.rs`
- Modify: `rust/tests/logger_test.rs`

**Problem:** `log_event()` never calls `increment_emitted(Signal::Logs, 1)`, so `emitted_logs` in `HealthSnapshot` is always 0. (`tracer::trace()` was fixed in Task 8 to include `increment_emitted(Signal::Traces, 1)`.)

- [ ] **Step 1: Write the failing test**

Open `rust/tests/logger_test.rs`. Add:

```rust
#[test]
fn logger_test_emitted_logs_increments_on_log() {
    let _guard = logger_lock().lock().expect("logger lock poisoned");
    use provide_telemetry::get_health_snapshot;

    let before = get_health_snapshot().emitted_logs;
    let logger = provide_telemetry::get_logger(Some("tests.health"));
    logger.info("logger.health.test");
    let after = get_health_snapshot().emitted_logs;
    assert!(after > before, "emitted_logs should increase after a log call (before={before}, after={after})");
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd rust && cargo test logger_test_emitted_logs_increments -- --nocapture 2>&1 | tail -15
```

Expected: FAIL — `after == before` because `log_event` doesn't call `increment_emitted`.

- [ ] **Step 3: Add `increment_emitted` to `log_event()` in `logger.rs`**

The file already imports `Signal` from `crate::sampling`. Add `increment_emitted` to the health import. In `log_event()`, add the call after the event is pushed to the buffer:

```rust
use crate::health::increment_emitted;
```

In `log_event()`, after the buffer push (before `release(ticket)`):

```rust
fn log_event(level: &str, target: &str, message: &str) {
    if !should_allow("logs", Some(level)) {
        return;
    }
    let Some(ticket) = try_acquire(Signal::Logs) else {
        return;
    };
    let event = new_event(target, level, message);
    emit_if_json(&event);
    emit_if_console(&event);
    let mut buf = events().lock().expect("logger event lock poisoned");
    if buf.len() < MAX_FALLBACK_EVENTS {
        buf.push(event);
    }
    drop(buf);
    increment_emitted(Signal::Logs, 1);    // <-- NEW
    release(ticket);
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd rust && cargo test logger_test_emitted_logs_increments -- --nocapture 2>&1 | tail -15
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
cd rust && cargo test 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add rust/src/logger.rs rust/tests/logger_test.rs
git commit -m "fix(rust): increment emitted_logs health counter in log_event()"
```

---

## Self-Review

### Spec coverage

| Issue | Task |
|-------|------|
| TS logs bypass sampling | Task 1 ✓ |
| TS traces bypass sampling + backpressure | Task 2 ✓ |
| TS split-brain getRuntimeConfig | Task 3 ✓ |
| TS shutdown doesn't clear provider state | Task 4 ✓ |
| TS otelEnabled comment misleads | Task 5 ✓ |
| Go traces bypass sampling + backpressure | Task 6 ✓ |
| Rust setup doesn't apply config to policy stores | Task 7 ✓ |
| Rust public trace() lacks consent gate | Task 8 ✓ |
| Rust duplicate tracing modules | Task 8 ✓ |
| Rust emitted_logs/emitted_traces never increment | Task 8 (traces) + Task 9 (logs) ✓ |

### Items intentionally deferred

- **Rust otel feature stub**: The `otel` feature is gated and intentionally not wired. This is an implementation gap, not a runtime defect. Left for a dedicated task when real OTLP provider construction is tackled.
- **Go `_resetBackpressureForTests`**: If this function doesn't exist in the Go package, Task 6's test needs to use `SetQueuePolicy(QueuePolicy{})` to reset instead.

### Placeholder scan

No steps say "TBD", "similar to above", or "add appropriate handling". All code blocks are complete.

### Type consistency

- `shouldSample(signal, key?)` — TypeScript, matches existing usage in metrics.ts ✓
- `tryAcquire(signal)` / `release(ticket)` — TypeScript, matches logger.ts pattern ✓
- `ShouldSample(signalTraces, name)` / `TryAcquire(signalTraces)` / `Release(signalTraces)` — Go, matches logger.go pattern ✓
- `set_sampling_policy(Signal, SamplingPolicy)` — Rust, matches sampling.rs signature ✓
- `increment_emitted(Signal, u64)` — Rust, matches metrics.rs usage ✓
