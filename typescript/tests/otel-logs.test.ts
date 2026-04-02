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
  it('throws when SDK peer dep is missing (caller handles graceful degradation)', async () => {
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      throw new Error('peer dep missing');
    } as never);
    await expect(
      setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never),
    ).rejects.toThrow('peer dep missing');
  });

  it('constructs OTLPLogExporter with default endpoint and /v1/logs path', async () => {
    setupTelemetry({ serviceName: 'test', otelEnabled: true, otlpEndpoint: undefined });
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://localhost:4318/v1/logs',
      headers: {},
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
    });
  });

  it('wires BatchLogRecordProcessor with the log exporter', async () => {
    const fakeExporter = { fake: 'log-exporter' };
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(vi.mocked(BatchLogRecordProcessor)).toHaveBeenCalledWith(fakeExporter);
  });

  it('constructs LoggerProvider with processors array containing the BatchLogRecordProcessor', async () => {
    const fakeProcessor = { fake: 'processor' };
    vi.mocked(BatchLogRecordProcessor).mockImplementation(function () {
      return fakeProcessor;
    } as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(vi.mocked(LoggerProvider)).toHaveBeenCalledWith(
      expect.objectContaining({ processors: [fakeProcessor] }),
    );
  });

  it('calls logs.setGlobalLoggerProvider with the provider', async () => {
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(vi.mocked(logs.setGlobalLoggerProvider)).toHaveBeenCalledOnce();
  });

  it('calls logs.getLogger to obtain the internal logger', async () => {
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(vi.mocked(logs.getLogger)).toHaveBeenCalledWith('@provide-io/telemetry');
  });

  it('returns a ShutdownableProvider with forceFlush and shutdown', async () => {
    const result = await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(result).toBeDefined();
    expect(typeof result.forceFlush).toBe('function');
    expect(typeof result.shutdown).toBe('function');
  });

  it('stores the provider accessible via _getOtelLogProvider', async () => {
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    expect(_getOtelLogProvider()).not.toBeNull();
  });
});

describe('emitLogRecord', () => {
  it('is a noop when no provider is registered', () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    expect(() => emitLogRecord({ level: 30, msg: 'hello', time: Date.now() })).not.toThrow();
    expect(loggerStub.emit).not.toHaveBeenCalled();
  });

  it('calls logger.emit with correct body, severityNumber, and attributes', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);

    emitLogRecord({ level: 30, msg: 'test message', time: 1000, event: 'test.event', env: 'prod' });

    expect(loggerStub.emit).toHaveBeenCalledOnce();
    const call = loggerStub.emit.mock.calls[0][0];
    expect(call.body).toBe('test message');
    expect(call.severityNumber).toBe(9); // INFO
    expect(call.severityText).toBe('INFO');
    expect(call.attributes).toMatchObject({ event: 'test.event', env: 'prod' });
    expect(call.attributes).not.toHaveProperty('msg');
    expect(call.attributes).not.toHaveProperty('level');
    expect(call.attributes).not.toHaveProperty('time');
  });

  it('maps pino level 10 → TRACE (severityNumber=1)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 10, msg: 'trace', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(1);
    expect(loggerStub.emit.mock.calls[0][0].severityText).toBe('TRACE');
  });

  it('maps pino level 20 → DEBUG (severityNumber=5)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 20, msg: 'debug', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(5);
  });

  it('maps pino level 40 → WARN (severityNumber=13)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 40, msg: 'warn', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(13);
  });

  it('maps pino level 50 → ERROR (severityNumber=17)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 50, msg: 'err', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(17);
  });

  it('maps pino level 60 → FATAL (severityNumber=21)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 60, msg: 'fatal', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(21);
  });

  it('defaults to INFO (severityNumber=9) for unknown levels', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 99, msg: 'unknown', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(9);
  });

  it('falls back to event field when msg is absent', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 30, event: 'my.event', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].body).toBe('my.event');
  });

  it('uses time field as timestamp when present', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 30, msg: 'ts', time: 1234567890 });
    expect(loggerStub.emit.mock.calls[0][0].timestamp).toBe(1234567890);
  });

  it('falls back to Date.now() when time field is not a number', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    const before = Date.now();
    emitLogRecord({ level: 30, msg: 'no-time' });
    const after = Date.now();
    const ts = loggerStub.emit.mock.calls[0][0].timestamp as number;
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(after);
  });

  it('defaults level to INFO (9) when level field is absent', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ msg: 'no level', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(9);
  });

  it('body falls back to empty string when neither msg nor event present', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 30, time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].body).toBe('');
  });

  it('excludes v field from attributes', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    emitLogRecord({ level: 30, msg: 'test', time: 1000, v: 1, service: 'svc' });
    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs).not.toHaveProperty('v');
    expect(attrs).toHaveProperty('service', 'svc');
  });
});

describe('_resetOtelLogProviderForTests', () => {
  it('nulls the provider so emitLogRecord becomes noop again', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({ serviceName: 'test', otelEnabled: true } as never);
    _resetOtelLogProviderForTests();
    emitLogRecord({ level: 30, msg: 'after reset', time: 1000 });
    expect(loggerStub.emit).not.toHaveBeenCalled();
    expect(_getOtelLogProvider()).toBeNull();
  });
});
