// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { metrics, trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig } from '../src/config.js';
import { _resetRuntimeForTests, RuntimeState, TelemetryRuntime } from '../src/runtime.js';

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
    expect(result.config?.samplingLogsRate).toBe(0.5);
    expect(result.state).toBe(RuntimeState.READY);
    expect(result.status).toBe(RuntimeState.READY);
    expect(result.previous).toBeDefined();
  });

  it('reconfigures via shared function path', () => {
    const runtime = new TelemetryRuntime();
    runtime.reconfigure({ tracingEnabled: false });
    expect(runtime.getRuntimeConfig().tracingEnabled).toBe(false);
  });

  it('flushes and reports per-signal status', async () => {
    const result = await new TelemetryRuntime().flush(100);
    expect(result.logs.flushed).toBe(true);
    expect(result.traces.flushed).toBe(true);
    expect(result.metrics.flushed).toBe(true);
    expect(result.logs.timedOut).toBe(false);
    expect(result.logs.notInstalled).toBe(false);
    expect(result.logs.notOwned).toBe(false);
    expect(result.logs.failed).toBe(false);
  });

  it('encodes stop state from timeout vs no-timeout shutdown calls', async () => {
    const runtime = new TelemetryRuntime();
    await runtime.shutdown(100);
    expect(await runtime.shutdown()).toBeUndefined();
  });
});
