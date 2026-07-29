// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * withTrace defers sampling to a live tracer provider.
 *
 * The provider is probed on the OTel global, so a provider a host application
 * installed itself counts — otherwise the facade rate would multiply with the
 * SDK's own sampler (facadeRate x sdkRate) and silently drop spans the SDK had
 * already decided to keep.
 */

import { trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { _resetSamplingForTests } from '../src/sampling.js';
import { _resetTraceContext, withTrace } from '../src/tracing.js';

/** A minimal stand-in for a host application's SDK tracer provider. */
function fakeSdk(): { started: string[]; provider: object } {
  const started: string[] = [];
  const span = {
    spanContext: () => ({ traceId: 'a'.repeat(32), spanId: 'b'.repeat(16), traceFlags: 1 }),
    isRecording: () => true,
    setAttribute: () => span,
    setStatus: () => span,
    recordException: () => {},
    end: () => {},
  };
  const tracer = {
    startSpan: () => span,
    startActiveSpan: <T>(name: string, fn: (s: typeof span) => T): T => {
      started.push(name);
      return fn(span);
    },
  };
  return {
    started,
    provider: {
      getTracer: () => tracer,
      forceFlush: async (): Promise<void> => {},
      shutdown: async (): Promise<void> => {},
    },
  };
}

beforeEach(() => {
  trace.disable();
  _resetConfig();
  _resetSamplingForTests();
  _resetHealthForTests();
  _resetTraceContext();
});
afterEach(() => {
  trace.disable();
  _resetConfig();
  _resetSamplingForTests();
  _resetHealthForTests();
  _resetTraceContext();
});

describe('withTrace sampling vs. the live tracer provider', () => {
  it('starts the span at facade rate 0 when a provider owns the global', () => {
    const { started, provider } = fakeSdk();
    setupTelemetry({ tracingEnabled: true, samplingTracesRate: 0 });
    trace.setGlobalTracerProvider(provider as never);

    expect(withTrace('host.sdk.span', () => 'ok')).toBe('ok');

    expect(started).toEqual(['host.sdk.span']);
    expect(getHealthSnapshot().tracesEmitted).toBe(1);
    expect(getHealthSnapshot().tracesDropped).toBe(0);
  });

  it('applies facade sampling when no provider owns the global', () => {
    setupTelemetry({ tracingEnabled: true, samplingTracesRate: 0 });

    expect(withTrace('facade.only.span', () => 'ok')).toBe('ok');

    expect(getHealthSnapshot().tracesEmitted).toBe(0);
    expect(getHealthSnapshot().tracesDropped).toBe(1);
  });

  it('starts the span with no provider once the facade rate allows it', () => {
    setupTelemetry({ tracingEnabled: true, samplingTracesRate: 1 });

    expect(withTrace('facade.sampled.span', () => 'ok')).toBe('ok');

    expect(getHealthSnapshot().tracesEmitted).toBe(1);
    expect(getHealthSnapshot().tracesDropped).toBe(0);
  });

  it('drops the span again after the provider is torn down', () => {
    const { started, provider } = fakeSdk();
    setupTelemetry({ tracingEnabled: true, samplingTracesRate: 0 });
    trace.setGlobalTracerProvider(provider as never);
    withTrace('before.teardown', () => 'ok');

    trace.disable();
    expect(withTrace('after.teardown', () => 'ok')).toBe('ok');

    expect(started).toEqual(['before.teardown']);
    expect(getHealthSnapshot().tracesDropped).toBe(1);
  });
});
