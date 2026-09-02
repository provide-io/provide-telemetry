// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Unit tests for src/otel-logs.ts — emitLogRecord and attribute security gates.
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
import { _resetConfig, setupTelemetry } from '../src/config.js';
import {
  _resetOtelLogProviderForTests,
  emitLogRecord,
  setupOtelLogProvider,
} from '../src/otel-logs.js';

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

describe('emitLogRecord', () => {
  it('is a noop when no provider is registered', () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    expect(() =>
      emitLogRecord({ level: 'INFO', message: 'hello', time: Date.now() }),
    ).not.toThrow();
    expect(loggerStub.emit).not.toHaveBeenCalled();
  });

  it('calls logger.emit with correct body, severityNumber, and attributes', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);

    emitLogRecord({
      level: 'INFO',
      message: 'test message',
      time: 1000,
      event: 'test.event',
      env: 'prod',
    });

    expect(loggerStub.emit).toHaveBeenCalledOnce();
    const call = loggerStub.emit.mock.calls[0][0];
    expect(call.body).toBe('test message');
    expect(call.severityNumber).toBe(9); // INFO
    expect(call.severityText).toBe('INFO');
    expect(call.attributes).toMatchObject({ event: 'test.event', env: 'prod' });
    expect(call.attributes).not.toHaveProperty('message');
    expect(call.attributes).not.toHaveProperty('level');
    expect(call.attributes).not.toHaveProperty('time');
  });

  it('maps pino level 10 → TRACE (severityNumber=1)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'TRACE', message: 'trace', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(1);
    expect(loggerStub.emit.mock.calls[0][0].severityText).toBe('TRACE');
  });

  it('maps pino level 20 → DEBUG (severityNumber=5)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'DEBUG', message: 'debug', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(5);
  });

  it('maps pino level 40 → WARN (severityNumber=13)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'WARN', message: 'warn', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(13);
  });

  it('maps pino level 50 → ERROR (severityNumber=17)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'ERROR', message: 'err', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(17);
  });

  it('maps pino level 60 → FATAL (severityNumber=21)', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'CRITICAL', message: 'fatal', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(21);
  });

  it('defaults to INFO (severityNumber=9) for unknown levels', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 99, message: 'unknown', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(9);
    // The name says INFO, and INFO is two fields: the number and the text the
    // collector displays. Asserting only the number left the text fallback free
    // to become the empty string.
    expect(loggerStub.emit.mock.calls[0][0].severityText).toBe('INFO');
  });

  it('falls back to event field when message is absent', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'INFO', event: 'my.event', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].body).toBe('my.event');
  });

  it('uses time field as timestamp when present', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'INFO', message: 'ts', time: 1234567890 });
    expect(loggerStub.emit.mock.calls[0][0].timestamp).toBe(1234567890);
  });

  it('falls back to Date.now() when time field is not a number', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    const before = Date.now();
    emitLogRecord({ level: 'INFO', message: 'no-time' });
    const after = Date.now();
    const ts = loggerStub.emit.mock.calls[0][0].timestamp as number;
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(after);
  });

  it('defaults level to INFO (9) when level field is absent', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ message: 'no level', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].severityNumber).toBe(9);
  });

  it('body falls back to empty string when neither message nor event present', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'INFO', time: 1000 });
    expect(loggerStub.emit.mock.calls[0][0].body).toBe('');
  });

  it('excludes v field from attributes', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    emitLogRecord({ level: 'INFO', message: 'test', time: 1000, v: 1, service: 'svc' });
    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs).not.toHaveProperty('v');
    expect(attrs).toHaveProperty('service', 'svc');
  });
});

describe('emitLogRecord — securityMaxAttrValueLength', () => {
  it('truncates string attribute values exceeding maxAttrValueLength', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ securityMaxAttrValueLength: 10 });

    emitLogRecord({ level: 'INFO', message: 'test', time: 1000, longField: 'a'.repeat(20) });

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs['longField']).toBe('a'.repeat(10) + '...');
  });

  it('does NOT truncate string values at exactly the limit', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ securityMaxAttrValueLength: 10 });

    emitLogRecord({ level: 'INFO', message: 'test', time: 1000, exact: 'a'.repeat(10) });

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs['exact']).toBe('a'.repeat(10));
  });

  it('does not truncate non-string attribute values', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ securityMaxAttrValueLength: 5 });

    emitLogRecord({ level: 'INFO', message: 'test', time: 1000, num: 123456 });

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs['num']).toBe(123456);
  });
});

describe('emitLogRecord — securityMaxAttrCount', () => {
  it('drops excess attributes beyond maxAttrCount', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ securityMaxAttrCount: 3 });

    const record: Record<string, unknown> = { level: 'INFO', message: 'test', time: 1000 };
    for (let i = 0; i < 10; i++) record[`key${i}`] = `val${i}`;
    emitLogRecord(record);

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(Object.keys(attrs).length).toBe(3);
  });

  it('keeps all attributes when count is within limit', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ securityMaxAttrCount: 100 });

    emitLogRecord({ level: 'INFO', message: 'test', time: 1000, a: 1, b: 2, c: 3 });

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs).toHaveProperty('a', 1);
    expect(attrs).toHaveProperty('b', 2);
    expect(attrs).toHaveProperty('c', 3);
  });
});

describe('emitLogRecord — logCodeAttributes', () => {
  it('publishes the callsite under the code.* semantic conventions', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ logCodeAttributes: true });

    emitLogRecord(
      { level: 'INFO', message: 'test', time: 1000, name: 'my.module' },
      { filename: 'app.ts', path: '/srv/app/app.ts', lineno: 42, functionName: 'handleRequest' },
    );

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    // The full path, not the base name the record field carries: OpenTelemetry
    // defines code.file.path as the whole path, and Python and Go both send it.
    expect(attrs['code.file.path']).toBe('/srv/app/app.ts');
    expect(attrs['code.line.number']).toBe(42);
    expect(attrs['code.function.name']).toBe('handleRequest');
    // code.namespace is not a canonical attribute and is no longer derived.
    expect(attrs).not.toHaveProperty('code.namespace');
  });

  it('omits code.function.name when the callsite resolved no function name', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ logCodeAttributes: true });

    emitLogRecord(
      { level: 'INFO', message: 'test', time: 1000 },
      { filename: 'app.ts', path: '/srv/app/app.ts', lineno: 42 },
    );

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs['code.file.path']).toBe('/srv/app/app.ts');
    expect(attrs['code.line.number']).toBe(42);
    expect(attrs).not.toHaveProperty('code.function.name');
  });

  it('does NOT add code attributes when logCodeAttributes is false', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ logCodeAttributes: false });

    emitLogRecord(
      { level: 'INFO', message: 'test', time: 1000 },
      { filename: 'app.ts', lineno: 42, functionName: 'handleRequest' },
    );

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs).not.toHaveProperty('code.file.path');
    expect(attrs).not.toHaveProperty('code.line.number');
    expect(attrs).not.toHaveProperty('code.function.name');
  });

  it('adds no code attributes when no callsite was captured', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ logCodeAttributes: true });

    emitLogRecord({ level: 'INFO', message: 'test', time: 1000 });

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs).not.toHaveProperty('code.file.path');
    expect(attrs).not.toHaveProperty('code.line.number');
    expect(attrs).not.toHaveProperty('code.function.name');
  });

  it('does not derive code attributes from record fields', async () => {
    const loggerStub = makeLoggerStub();
    vi.mocked(logs.getLogger).mockReturnValue(loggerStub as never);
    await setupOtelLogProvider({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    setupTelemetry({ logCodeAttributes: true });

    // filename/lineno on the record belong to logIncludeCaller; they are
    // carried through as-is and never promoted to code.* attributes.
    emitLogRecord({ level: 'INFO', message: 'test', time: 1000, filename: 'app.ts', lineno: 42 });

    const attrs = loggerStub.emit.mock.calls[0][0].attributes;
    expect(attrs['filename']).toBe('app.ts');
    expect(attrs['lineno']).toBe(42);
    expect(attrs).not.toHaveProperty('code.file.path');
    expect(attrs).not.toHaveProperty('code.line.number');
  });
});
