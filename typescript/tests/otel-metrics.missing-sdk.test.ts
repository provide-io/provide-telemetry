// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** setupOtelMeterProvider() when an optional OTel package will not load. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULTS, type TelemetryConfig } from '../src/config.js';

const missing = new Set<string>();

vi.mock('../src/otel-dynimport.js', () => ({
  dynImportOtel: (pkg: string) =>
    missing.has(pkg) ? Promise.reject(new Error(`Cannot find package '${pkg}'`)) : import(pkg),
}));

const { setupOtelMeterProvider } = await import('../src/otel-metrics.js');
const { getPullStatus, NOT_SELECTED, OTEL_MISSING, SETUP_FAILED, _resetPullForTests } =
  await import('../src/prom-pull.js');

const { unreadableTls } = await import('../src/otlp-tls.js');

const ENDPOINT = 'http://127.0.0.1:9/v1/metrics';

function cfg(overrides: Partial<TelemetryConfig>): TelemetryConfig {
  return { ...DEFAULTS, ...overrides };
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  missing.clear();
  _resetPullForTests();
  vi.restoreAllMocks();
});

describe('a missing SDK package', () => {
  it.each(['@opentelemetry/sdk-metrics', '@opentelemetry/resources'])(
    '%s missing with the pull reader wanted is otel_missing',
    async (pkg) => {
      missing.add(pkg);
      const provider = await setupOtelMeterProvider(
        cfg({ metricsExporters: ['prometheus'] }),
        undefined,
        {},
      );
      expect(provider).toBeUndefined();
      expect(getPullStatus()).toBe(OTEL_MISSING);
      expect(console.warn).toHaveBeenCalledWith(
        '[provide/telemetry] OTEL metrics setup failed (missing peer deps?):',
        expect.any(Error),
      );
    },
  );

  it('the SDK missing for OTLP alone leaves the pull reader not selected', async () => {
    missing.add('@opentelemetry/sdk-metrics');
    await setupOtelMeterProvider(cfg({}), ENDPOINT, {});
    expect(getPullStatus()).toBe(NOT_SELECTED);
  });

  it('the OTLP exporter missing is a setup failure, even with the pull reader wanted', async () => {
    missing.add('@opentelemetry/exporter-metrics-otlp-http');
    const provider = await setupOtelMeterProvider(
      cfg({ metricsExporters: ['otlp', 'prometheus'] }),
      ENDPOINT,
      {},
    );
    expect(provider).toBeUndefined();
    expect(getPullStatus()).toBe(SETUP_FAILED);
    expect(console.warn).toHaveBeenCalledTimes(1);
  });

  it('the TLS check imports no Node built-in when nothing is configured', async () => {
    missing.add('node:fs');
    await expect(unreadableTls('metrics', () => undefined)).resolves.toBeUndefined();
  });
});
