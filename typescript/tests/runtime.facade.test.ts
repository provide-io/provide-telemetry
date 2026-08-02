// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { metrics, trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig } from '../src/config.js';
import {
  _resetRuntimeForTests,
  _storeRegisteredProviders,
  RuntimeState,
  TelemetryRuntime,
} from '../src/runtime.js';
import { liveTracerProvider } from './fixtures/live-providers.js';

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
    const runtime = new TelemetryRuntime();
    const result = runtime.updateConfig({ samplingLogsRate: 0.5 });
    expect(result.applied).toBe(true);
    expect(result.current?.samplingLogsRate).toBe(0.5);
    expect(result.state).toBe(RuntimeState.READY);
    expect(result.previous).toBeDefined();
  });

  it('reconfigures via shared function path', () => {
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
    const withTimeout = new TelemetryRuntime();
    await withTimeout.shutdown(100);
    expect(withTimeout.getRuntimeStatus).toBeDefined();
    expect(withTimeout.updateConfig({}).state).toBe(RuntimeState.STOPPED);

    const withoutTimeout = new TelemetryRuntime();
    expect(await withoutTimeout.shutdown()).toBeUndefined();
    expect(withoutTimeout.updateConfig({}).state).toBe(RuntimeState.STOPPED);
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
