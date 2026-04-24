// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { context, metrics, trace } from '@opentelemetry/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { bindContext, getContext } from '../src/context';
import { _incrementHealth, getHealthSnapshot } from '../src/health';
import { setTraceContext, getTraceContext } from '../src/tracing';
import { resetTelemetryState, resetTraceContext, telemetryTestPlugin } from '../src/testing';

afterEach(() => {
  trace.disable();
  metrics.disable();
  context.disable();
});

describe('resetTelemetryState', () => {
  it('clears context bindings', () => {
    bindContext({ userId: 'u1' });
    expect(getContext()['userId']).toBe('u1');
    resetTelemetryState();
    expect(getContext()['userId']).toBeUndefined();
  });

  it('resets health counters', () => {
    _incrementHealth('exportFailuresLogs', 5);
    resetTelemetryState();
    expect(getHealthSnapshot().exportFailuresLogs).toBe(0);
  });

  it('does not throw when called multiple times', () => {
    expect(() => {
      resetTelemetryState();
      resetTelemetryState();
    }).not.toThrow();
  });

  it('clears installed OTEL trace, metrics, and context globals', () => {
    const contextManager = {
      active: vi.fn(),
      with: vi.fn((_ctx, fn, thisArg, ...args) => fn.apply(thisArg, args)),
      bind: vi.fn((_ctx, target) => target),
      enable: vi.fn(),
      disable: vi.fn(),
    };

    expect(context.setGlobalContextManager(contextManager as never)).toBe(true);
    expect(trace.setGlobalTracerProvider({ getTracer: vi.fn() } as never)).toBe(true);
    expect(metrics.setGlobalMeterProvider({ getMeter: vi.fn() } as never)).toBe(true);

    resetTelemetryState();

    expect(contextManager.disable).toHaveBeenCalledOnce();
    expect(trace.setGlobalTracerProvider({ getTracer: vi.fn() } as never)).toBe(true);
    expect(metrics.setGlobalMeterProvider({ getMeter: vi.fn() } as never)).toBe(true);
  });
});

describe('resetTraceContext', () => {
  it('clears manually set trace context', () => {
    setTraceContext('abc123', 'def456');
    expect(getTraceContext().trace_id).toBe('abc123');
    resetTraceContext();
    expect(getTraceContext().trace_id).toBeUndefined();
  });

  it('does not throw when nothing is set', () => {
    expect(() => resetTraceContext()).not.toThrow();
  });
});

describe('telemetryTestPlugin', () => {
  it('beforeEach resets state', () => {
    bindContext({ x: 1 });
    telemetryTestPlugin.beforeEach();
    expect(getContext()['x']).toBeUndefined();
  });

  it('afterEach resets state', () => {
    bindContext({ y: 2 });
    telemetryTestPlugin.afterEach();
    expect(getContext()['y']).toBeUndefined();
  });
});
