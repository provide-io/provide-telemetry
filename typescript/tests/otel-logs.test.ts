// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Unit tests for src/otel-logs.ts.
 *
 * All OTEL peer deps are mocked so tests run without a live endpoint.
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
import { _resetConfig, setupTelemetry } from '../src/config';
import {
  _getOtelLogProvider,
  _resetOtelLogProviderForTests,
  emitLogRecord,
  setupOtelLogProvider,
} from '../src/otel-logs';

const makeProviderStub = () => ({
  shutdown: vi.fn().mockResolvedValue(undefined),
  forceFlush: vi.fn().mockResolvedValue(undefined),
});

const makeLoggerStub = () => ({ emit: vi.fn() });

beforeEach(() => {
  _resetConfig();
  _resetOtelLogProviderForTests();
  vi.clearAllMocks();
  vi.mocked(LoggerProvider).mockImplementation(function () {
    return makeProviderStub();
  } as never);
  vi.mocked(BatchLogRecordProcessor).mockImplementation(function () {
    return {};
  } as never);
  vi.mocked(OTLPLogExporter).mockImplementation(function () {
    return {};
  } as never);
  const loggerStub = makeLoggerStub();
  vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
});

afterEach(() => {
  _resetOtelLogProviderForTests();
  _resetConfig();
});

describe('setupOtelLogProvider', () => {
  it('throws when called without any OTLP log endpoint configured', async () => {
    await expect(
      setupOtelLogProvider({
        serviceName: 'test',
        otelEnabled: true,
        // otlpEndpoint intentionally omitted
      } as never),
    ).rejects.toThrow('setupOtelLogProvider called without an OTLP log endpoint configured');
  });

  it('throws when SDK peer dep is missing (caller handles graceful degradation)', async () => {
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      throw new Error('peer dep missing');
    } as never);
    await expect(
      setupOtelLogProvider({
        serviceName: 'test',
        otelEnabled: true,
        otlpEndpoint: 'http://localhost:4318',
      } as never),
    ).rejects.toThrow('peer dep missing');
  });

  it('constructs OTLPLogExporter with default endpoint and /v1/logs path', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://localhost:4318/v1/logs',
      headers: {},
      timeoutMillis: 10000,
    });
  });

  it('constructs OTLPLogExporter with configured endpoint and headers', async () => {
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://otel:4318',
      otlpHeaders: { Authorization: 'Bearer tok' },
    } as never);
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://otel:4318/v1/logs',
      headers: { Authorization: 'Bearer tok' },
      timeoutMillis: 10000,
    });
  });

  it('wires BatchLogRecordProcessor with the log exporter', async () => {
    const fakeExporter = { fake: 'log-exporter' };
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    // Exporter is wrapped in a resilient-export proxy, so assert on the
    // preserved underlying field rather than identity.
    expect(vi.mocked(BatchLogRecordProcessor)).toHaveBeenCalledWith(
      expect.objectContaining({ fake: 'log-exporter' }),
    );
  });

  it('constructs LoggerProvider with processors array containing the BatchLogRecordProcessor', async () => {
    const fakeProcessor = { fake: 'processor' };
    vi.mocked(BatchLogRecordProcessor).mockImplementation(function () {
      return fakeProcessor;
    } as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(vi.mocked(LoggerProvider)).toHaveBeenCalledWith(
      expect.objectContaining({ processors: [fakeProcessor] }),
    );
  });

  it('calls logs.setGlobalLoggerProvider with the provider', async () => {
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(vi.mocked(logs.setGlobalLoggerProvider)).toHaveBeenCalledOnce();
  });

  it('calls logs.getLogger to obtain the internal logger', async () => {
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(vi.mocked(logs.getLogger)).toHaveBeenCalledWith('@provide-io/telemetry');
  });

  it('returns a ShutdownableProvider with forceFlush and shutdown', async () => {
    const result = await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(result).toBeDefined();
    expect(typeof result.forceFlush).toBe('function');
    expect(typeof result.shutdown).toBe('function');
  });

  it('stores the provider accessible via _getOtelLogProvider', async () => {
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(_getOtelLogProvider()).not.toBeNull();
  });
});

describe('_resetOtelLogProviderForTests', () => {
  it('nulls the provider so emitLogRecord becomes noop again', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    _resetOtelLogProviderForTests();
    emitLogRecord({ level: 30, message: 'after reset', time: 1000 });
    expect(loggerStub.emit).not.toHaveBeenCalled();
    expect(_getOtelLogProvider()).toBeNull();
  });
});
