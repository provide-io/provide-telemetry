// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * getRuntimeStatus must report the provider state the emit paths actually see.
 *
 * Before setupTelemetry() the emit paths read getConfig(), which is still the
 * built-in defaults — the environment has not been loaded yet. Gating the
 * provider probes on the env-resolved config instead made status claim a signal
 * was dead while withTrace went on exporting through a host application's
 * provider, and put TypeScript out of step with Python and Go, which both
 * default a signal on until a loaded config switches it off.
 *
 * The rule is spec'd as behavioral_parity provider_adoption_reporting in
 * spec/telemetry-api.yaml. It lives here rather than in runtime.test.ts's
 * getRuntimeStatus block only because that file is near the 500-line cap.
 */

import { metrics, trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetRuntimeForTests, getRuntimeStatus } from '../src/runtime.js';
import { liveMeterProvider, liveTracerProvider } from './fixtures/live-providers.js';

function installHostProviders(): void {
  trace.setGlobalTracerProvider(liveTracerProvider() as never);
  metrics.setGlobalMeterProvider(liveMeterProvider() as never);
}

beforeEach(() => {
  trace.disable();
  metrics.disable();
  _resetRuntimeForTests();
  _resetConfig();
  process.env['PROVIDE_TRACE_ENABLED'] = 'false';
  process.env['PROVIDE_METRICS_ENABLED'] = 'false';
});

afterEach(() => {
  trace.disable();
  metrics.disable();
  _resetRuntimeForTests();
  _resetConfig();
  delete process.env['PROVIDE_TRACE_ENABLED'];
  delete process.env['PROVIDE_METRICS_ENABLED'];
});

describe('getRuntimeStatus provider gating against a disabling environment', () => {
  it('reports a host provider before setup, because the env is not loaded yet', () => {
    installHostProviders();

    const status = getRuntimeStatus();

    expect(status.setupDone).toBe(false);
    expect(status.providers.traces).toBe(true);
    expect(status.providers.metrics).toBe(true);
    expect(status.fallback.traces).toBe(false);
    expect(status.fallback.metrics).toBe(false);
    // signals still reports configured intent, which is what the env says.
    expect(status.signals.traces).toBe(false);
    expect(status.signals.metrics).toBe(false);
  });

  it('stops reporting the provider once setup loads that same config', () => {
    installHostProviders();

    setupTelemetry();
    const status = getRuntimeStatus();

    expect(status.setupDone).toBe(true);
    expect(status.providers.traces).toBe(false);
    expect(status.providers.metrics).toBe(false);
    expect(status.fallback.traces).toBe(true);
    expect(status.fallback.metrics).toBe(true);
  });
});
