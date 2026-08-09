// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Targeted mutation-killing tests for `src/otel-logs.ts`.
 *
 * otel-logs.test.ts pins the happy path (endpoint + headers reach the exporter,
 * the processor is wired with an options object). What was left unpinned is the
 * endpoint normalization either side of it, the signal name the exporter's
 * resilience policy is keyed by, and the rule that an attribute with no value
 * is dropped rather than exported as null.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@opentelemetry/sdk-logs', () => ({
  LoggerProvider: vi.fn(),
  BatchLogRecordProcessor: vi.fn(),
}));
vi.mock('@opentelemetry/exporter-logs-otlp-http', () => ({
  OTLPLogExporter: vi.fn(),
}));
vi.mock('@opentelemetry/api-logs', () => ({
  logs: {
    setGlobalLoggerProvider: vi.fn(),
    getLogger: vi.fn(),
  },
}));

import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { logs } from '@opentelemetry/api-logs';
import { _resetConfig } from '../src/config.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { _resetResilienceForTests, setExporterPolicy } from '../src/resilience.js';
import {
  _resetOtelLogProviderForTests,
  emitLogRecord,
  setupOtelLogProvider,
} from '../src/otel-logs.js';

const baseConfig = (overrides: Record<string, unknown>) =>
  ({ serviceName: 'logs-mutants', otelEnabled: true, ...overrides }) as never;

beforeEach(() => {
  _resetConfig();
  _resetOtelLogProviderForTests();
  _resetHealthForTests();
  _resetResilienceForTests();
  vi.clearAllMocks();
  vi.mocked(LoggerProvider).mockImplementation(function () {
    return { shutdown: async () => {}, forceFlush: async () => {} };
  } as never);
  vi.mocked(BatchLogRecordProcessor).mockImplementation(function () {
    return {};
  } as never);
  vi.mocked(OTLPLogExporter).mockImplementation(function () {
    return {};
  } as never);
  vi.mocked(logs.getLogger).mockReturnValue({ emit: vi.fn() } as never);
});

afterEach(() => {
  _resetOtelLogProviderForTests();
  _resetConfig();
  _resetHealthForTests();
  _resetResilienceForTests();
});

describe('setupOtelLogProvider — endpoint normalization', () => {
  it('trims whitespace around the endpoint before appending /v1/logs', async () => {
    await setupOtelLogProvider(baseConfig({ otlpEndpoint: '  http://collector:4318  ' }));
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'http://collector:4318/v1/logs' }),
    );
  });

  it('collapses a run of trailing slashes, not just the last one', async () => {
    await setupOtelLogProvider(baseConfig({ otlpEndpoint: 'http://collector:4318///' }));
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'http://collector:4318/v1/logs' }),
    );
  });
});

describe('setupOtelLogProvider — resilience wiring', () => {
  it('wraps the log exporter under the "logs" policy, not the default one', async () => {
    // The signal name selects both the retry policy and the counters the
    // failures land on. A wrong name falls back to the built-in default policy
    // — one attempt, no retries — so a collector blip that should have been
    // retried twice is dropped on the first try instead.
    setExporterPolicy('logs', { retries: 2, backoffMs: 0, timeoutMs: 0, failOpen: true });
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      return {
        export: (_items: unknown, cb: (r: { code: number; error: Error }) => void) => {
          cb({ code: 1, error: new Error('collector down') });
        },
        shutdown: async () => {},
      };
    } as never);
    await setupOtelLogProvider(baseConfig({ otlpEndpoint: 'http://collector:4318' }));
    const { exporter } = vi.mocked(BatchLogRecordProcessor).mock.calls[0][0] as {
      exporter: { export: (items: unknown, cb: (r: unknown) => void) => void };
    };
    await new Promise<void>((resolve) => {
      exporter.export([], () => {
        resolve();
      });
    });
    const health = getHealthSnapshot();
    expect(health.exportFailuresLogs).toBe(3); // one attempt plus two retries
    expect(health.retriesLogs).toBe(2);
  });
});

describe('emitLogRecord — attribute selection', () => {
  it('drops attributes whose value is undefined instead of exporting them empty', async () => {
    const emit = vi.fn();
    vi.mocked(logs.getLogger).mockReturnValue({ emit } as never);
    await setupOtelLogProvider(baseConfig({ otlpEndpoint: 'http://collector:4318' }));
    emitLogRecord({ level: 30, message: 'm', time: 1, present: 'yes', absent: undefined });
    const { attributes } = emit.mock.calls[0][0] as { attributes: Record<string, unknown> };
    expect(attributes).toHaveProperty('present', 'yes');
    // Hardening keeps `undefined` as-is, so an unfiltered key reaches the
    // exporter as an attribute with no value rather than not being sent.
    expect(Object.keys(attributes)).not.toContain('absent');
  });
});
