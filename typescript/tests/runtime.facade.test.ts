// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { metrics, trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import {
  _resetRuntimeForTests,
  _setLogsProviderInstalled,
  _storeRegisteredProviders,
  RuntimeState,
  TelemetryRuntime,
} from '../src/runtime.js';
import { liveMeterProvider, liveTracerProvider } from './fixtures/live-providers.js';

beforeEach(() => {
  trace.disable();
  metrics.disable();
  _resetRuntimeForTests();
  _resetConfig();
});

afterEach(() => {
  trace.disable();
  metrics.disable();
  _resetRuntimeForTests();
  _resetConfig();
});

describe('TelemetryRuntime facade', () => {
  it('starts, delegates tracer/meter/logger access, and returns runtime status/config', async () => {
    const runtime = new TelemetryRuntime();
    const cfg = await runtime.start({
      serviceName: 'runtime-facade',
      tracingEnabled: false,
      metricsEnabled: false,
    } as unknown as Parameters<TelemetryRuntime['start']>[0]);
    expect(cfg.serviceName).toBe('runtime-facade');
    expect(runtime.getRuntimeConfig().serviceName).toBe('runtime-facade');
    expect(runtime.getRuntimeStatus().setupDone).toBe(true);

    const logger = runtime.getLogger('runtime.module');
    expect(typeof logger).toBe('object');
    expect(typeof logger.info).toBe('function');
    expect(typeof runtime.getTracer('runtime.tracer').startSpan).toBe('function');
    expect(typeof runtime.getMeter('runtime.meter').createCounter).toBe('function');
  });

  it('reconfigure delegates through the facade and returns active state', () => {
    setupTelemetry({ serviceName: 'facade-update' });
    const runtime = new TelemetryRuntime();
    const result = runtime.updateConfig({ samplingLogsRate: 0.5 });
    expect(result.applied).toBe(true);
    expect(result.current?.samplingLogsRate).toBe(0.5);
    expect(result.state).toBe(RuntimeState.READY);
    expect(result.previous).toBeDefined();
  });

  it('reconfigures via shared function path', () => {
    // reconfigure requires a live config; the facade shares that precondition
    // with the free function.
    setupTelemetry({ serviceName: 'facade-reconfigure' });
    const runtime = new TelemetryRuntime();
    runtime.reconfigure({ tracingEnabled: false });
    expect(runtime.getRuntimeConfig().tracingEnabled).toBe(false);
  });

  it('reports notInstalled per signal when no provider is registered', async () => {
    // flushTelemetry() returns [].every() === true with an empty provider list;
    // the facade must not turn that vacuous truth into "flushed".
    const result = await new TelemetryRuntime().flush(100);
    for (const signal of [result.logs, result.traces, result.metrics]) {
      expect(signal.notInstalled).toBe(true);
      expect(signal.flushed).toBe(false);
      expect(signal.timedOut).toBe(false);
      expect(signal.notOwned).toBe(false);
      expect(signal.failed).toBe(false);
    }
  });

  it('reports flushed for a signal whose provider is live and ours', async () => {
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    _storeRegisteredProviders([{ forceFlush: () => Promise.resolve() }], ['traces']);
    const result = await new TelemetryRuntime().flush(100);
    expect(result.traces.flushed).toBe(true);
    expect(result.traces.notInstalled).toBe(false);
    expect(result.traces.notOwned).toBe(false);
    // A clean drain must not carry a failure flag: `failed` and `timedOut`
    // compare the outcome against their own literal, and forcing either
    // comparison true would brand every successful flush a failure.
    expect(result.traces.failed).toBe(false);
    expect(result.traces.timedOut).toBe(false);
  });

  it('reports failed for a provider whose forceFlush throws synchronously', async () => {
    // A sync throw is the same broken exporter as a rejection, and it must
    // surface as the *failed* outcome specifically — not merely a falsy one.
    // flushTelemetry() collapses every non-flushed outcome to false, so only
    // this per-signal assertion distinguishes 'failed' from a mangled
    // outcome string.
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    _storeRegisteredProviders(
      [
        {
          forceFlush: () => {
            throw new Error('sync boom');
          },
        },
      ],
      ['traces'],
    );

    const result = await new TelemetryRuntime().flush(100);

    expect(result.traces.failed).toBe(true);
    expect(result.traces.timedOut).toBe(false);
    expect(result.traces.flushed).toBe(false);
    vi.restoreAllMocks();
  });

  it.each([
    ['logs', 'traces'],
    ['metrics', 'traces'],
  ] as const)('keys the %s result by its own signal, not another', async (signal, other) => {
    // Each signal must read its own entry out of the per-signal drain. Keying
    // one by the wrong name (or by an empty name) silently turns a drained
    // signal into notOwned, which is the "we did not touch this" answer.
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    metrics.setGlobalMeterProvider(liveMeterProvider() as never);
    _setLogsProviderInstalled(true);
    _storeRegisteredProviders(
      [{ forceFlush: () => Promise.resolve() }, { forceFlush: () => new Promise<void>(() => {}) }],
      [signal, other],
    );

    const result = await new TelemetryRuntime().flush(20);

    expect(result[signal].flushed).toBe(true);
    expect(result[signal].notOwned).toBe(false);
    expect(result[signal].timedOut).toBe(false);
  });

  it('reports notOwned for a provider the host installed on the OTel globals', async () => {
    // traces status is probed against the globals, so a host application's own
    // SDK counts as installed — but we registered nothing, so there is nothing
    // of ours to drain. Calling it flushed would say the spans are out while
    // they sit in the host's BatchSpanProcessor.
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    const result = await new TelemetryRuntime().flush(100);
    expect(result.traces.notOwned).toBe(true);
    expect(result.traces.flushed).toBe(false);
    expect(result.traces.timedOut).toBe(false);
  });

  it('settles in STOPPED after shutdown, with or without a timeout', async () => {
    // updateConfig refuses to run after shutdown (see the test below), so the
    // state is observed by re-running module-level setup — which satisfies the
    // not-set-up guard without touching the instance's own lifecycle state.
    const withTimeout = new TelemetryRuntime();
    await withTimeout.shutdown(100);
    setupTelemetry({ serviceName: 'post-shutdown' });
    expect(withTimeout.updateConfig({}).state).toBe(RuntimeState.STOPPED);

    const withoutTimeout = new TelemetryRuntime();
    expect(await withoutTimeout.shutdown()).toBeUndefined();
    setupTelemetry({ serviceName: 'post-shutdown' });
    expect(withoutTimeout.updateConfig({}).state).toBe(RuntimeState.STOPPED);
  });

  it('refuses updateConfig after shutdown instead of resurrecting setup', async () => {
    // On this branch's parent, updateConfig after shutdownTelemetry silently
    // republished the config and flipped setupDone back to true with zero
    // providers registered — a health endpoint would report telemetry live
    // while every record no-ops. Go and Rust refuse with this error instead.
    const runtime = new TelemetryRuntime();
    await runtime.start({ serviceName: 'resurrect' } as unknown as Parameters<
      TelemetryRuntime['start']
    >[0]);
    await runtime.shutdown(100);

    expect(() => runtime.updateConfig({ samplingLogsRate: 0.5 })).toThrow(
      'telemetry not set up: call setupTelemetry first',
    );
    expect(runtime.getRuntimeStatus().setupDone).toBe(false);
  });

  it('reports failed for an installed provider whose exporter rejected in time', async () => {
    // A rejection that beat the deadline is an exporter failure, not a timeout:
    // the drain did not run out of budget, it was refused. Conflating the two
    // (or throwing) loses the healthy signals' outcomes — Go maps this to
    // Failed and TypeScript must agree.
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    _storeRegisteredProviders(
      [{ forceFlush: () => Promise.reject(new Error('down')) }],
      ['traces'],
    );

    const result = await new TelemetryRuntime().flush(100);

    expect(result.traces.failed).toBe(true);
    expect(result.traces.timedOut).toBe(false);
    expect(result.traces.flushed).toBe(false);
    expect(result.traces.notOwned).toBe(false);
    vi.restoreAllMocks();
  });

  it('reports timedOut only for an installed provider that missed the deadline', async () => {
    // traces: installed=true, but the registered provider hangs past the
    // deadline -> flushTelemetry() resolves false -> traces.timedOut = true.
    // logs/metrics: installed=false, same failed flushTelemetry() -> their
    // timedOut must stay false (an uninstalled signal can't "time out").
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    _storeRegisteredProviders([{ forceFlush: () => new Promise<void>(() => {}) }], ['traces']);
    const result = await new TelemetryRuntime().flush(20);

    expect(result.traces.timedOut).toBe(true);
    expect(result.traces.flushed).toBe(false);
    expect(result.logs.timedOut).toBe(false);
    expect(result.logs.notInstalled).toBe(true);
    expect(result.metrics.timedOut).toBe(false);
    expect(result.metrics.notInstalled).toBe(true);
  });

  it('forwards the requested name to getTracer', () => {
    const runtime = new TelemetryRuntime();
    // Distinct names must not collapse into one instrumentation scope.
    expect(runtime.getTracer('payments.worker')).not.toBe(runtime.getTracer('billing.worker'));
  });
});
