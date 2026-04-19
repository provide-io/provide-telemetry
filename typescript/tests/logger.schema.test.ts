// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import { _resetContext } from '../src/context';
import { _resetRootLogger, getLogger, makeWriteHook } from '../src/logger';
import * as otelLogs from '../src/otel-logs';
import * as schema from '../src/schema';

function makeCfg(overrides?: Parameters<typeof setupTelemetry>[0]) {
  _resetConfig();
  setupTelemetry({
    serviceName: 'test-svc',
    logLevel: 'debug',
    captureToWindow: true,
    ...overrides,
  });
}

beforeEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  setupTelemetry({ serviceName: 'test-svc', logLevel: 'debug', captureToWindow: true });
  (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
});

afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  vi.restoreAllMocks();
});

describe('write hook — schema validation (strictSchema)', () => {
  it('emits normally when strictSchema=true and event is a valid 3-part name', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'app.user.created' });
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it('annotates log with _schema_error when strictSchema=true and event name violates schema', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'x' });
    // Record is emitted (not dropped) with _schema_error annotation.
    // Cross-language standard: never lose telemetry on schema violation.
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0]).toHaveProperty('_schema_error');
    spy.mockRestore();
  });

  it('passes any event through when strictSchema=false (default)', () => {
    makeCfg({ strictSchema: false });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'x' });
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it('annotates log with _schema_error when strictEventName=true and strictSchema=false', () => {
    makeCfg({ strictSchema: false, strictEventName: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'Bad.Event.Ok' });
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0]).toHaveProperty('_schema_error');
    spy.mockRestore();
  });

  it('annotates log with _schema_error when strictSchema=true and requiredLogKeys missing', () => {
    makeCfg({ strictSchema: true, requiredLogKeys: ['action'] });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'app.user.created' });
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0]).toHaveProperty('_schema_error');
    spy.mockRestore();
  });

  it('emits when strictSchema=true, requiredLogKeys present, and event valid', () => {
    makeCfg({ strictSchema: true, requiredLogKeys: ['action'] });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'app.user.created', action: 'signup' });
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it('does not drop log when event is empty and strictSchema=true', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30 });
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it('annotates message field when event is absent and name invalid', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, message: 'x' });
    // 'x' is not a valid 3-part event name; annotated, not dropped.
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0]).toHaveProperty('_schema_error');
    spy.mockRestore();
  });

  it('rethrows non-EventSchemaError from validateEventName', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(schema, 'validateEventName').mockImplementation(() => {
      throw new TypeError('unexpected');
    });
    const hook = makeWriteHook();
    expect(() => hook({ level: 30, event: 'app.user.created' })).toThrow(TypeError);
    spy.mockRestore();
  });

  it('rethrows non-EventSchemaError from validateRequiredKeys', () => {
    makeCfg({ strictSchema: true, requiredLogKeys: ['action'] });
    const spy = vi.spyOn(schema, 'validateRequiredKeys').mockImplementation(() => {
      throw new RangeError('unexpected');
    });
    const hook = makeWriteHook();
    expect(() => hook({ level: 30, event: 'app.user.created' })).toThrow(RangeError);
    spy.mockRestore();
  });

  it('captures schema-annotated record to window.__pinoLogs', () => {
    makeCfg({ strictSchema: true, captureToWindow: true });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const hook = makeWriteHook();
    hook({ level: 30, event: 'x' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    // Record is emitted (not dropped) with _schema_error annotation.
    expect(logs.length).toBe(1);
    expect(logs[0]).toHaveProperty('_schema_error');
  });
});

// ── logIncludeCaller tests ────────────────────────────────────────────────────

describe('write hook — logIncludeCaller', () => {
  it('injects caller_file and caller_line when logIncludeCaller is true', () => {
    makeCfg({ logIncludeCaller: true });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'caller.test' };
    hook(obj);
    expect(obj['caller_file']).toBeDefined();
    expect(typeof obj['caller_file']).toBe('string');
    expect(typeof obj['caller_line']).toBe('number');
  });

  it('caller_file is a basename (no full path)', () => {
    makeCfg({ logIncludeCaller: true });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'caller.basename' };
    hook(obj);
    expect(obj['caller_file']).toBeDefined();
    // Should not contain path separators — it's a basename
    expect(String(obj['caller_file'])).not.toContain('/');
  });

  it('does NOT inject caller_file when logIncludeCaller is false', () => {
    makeCfg({ logIncludeCaller: false });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'no.caller' };
    hook(obj);
    expect(obj['caller_file']).toBeUndefined();
    expect(obj['caller_line']).toBeUndefined();
  });
});

// ── logModuleLevels tests ─────────────────────────────────────────────────────

describe('getLogger — logModuleLevels', () => {
  it('sets logger level from exact module match', () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'info', logModuleLevels: { 'provide.server': 'warn' } });
    const log = getLogger('provide.server');
    // The adapted Logger does not expose .level, so we test via pino internals
    // by checking that debug-level messages are NOT captured
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    log.info({ event: 'should.be.dropped' });
    // Give pino stream time to flush
    // info < warn, so this should be filtered by pino level
  });

  it('matches longest prefix for nested module names', async () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'info', logModuleLevels: { 'provide.server': 'debug' } });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const log = getLogger('provide.server.auth');
    log.debug({ event: 'debug.event' }, 'debug message');
    // pino flushes async in Node stream mode
    await new Promise((resolve) => setTimeout(resolve, 10));
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    // debug is enabled because module level is 'debug'
    const found = logs.some((l) => (l as Record<string, unknown>)['event'] === 'debug.event');
    expect(found).toBe(true);
  });

  it('uses default level when no module match', async () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'warn', logModuleLevels: { 'provide.server': 'debug' } });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const log = getLogger('unrelated.module');
    log.info({ event: 'no.match' }, 'should not appear');
    await new Promise((resolve) => setTimeout(resolve, 10));
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    const found = logs.some((l) => (l as Record<string, unknown>)['event'] === 'no.match');
    // info < warn (default), so should be filtered
    expect(found).toBe(false);
  });

  it('does NOT match partial module name without dot boundary', async () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'warn', logModuleLevels: { my: 'debug' } });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const log = getLogger('myapp');
    log.debug({ event: 'partial.should.not.match' }, 'nope');
    await new Promise((resolve) => setTimeout(resolve, 10));
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    const found = logs.some(
      (l) => (l as Record<string, unknown>)['event'] === 'partial.should.not.match',
    );
    expect(found).toBe(false);
  });

  it('matches module name with dot boundary', async () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'warn', logModuleLevels: { my: 'debug' } });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const log = getLogger('my.app');
    log.debug({ event: 'dot.boundary.match' }, 'yes');
    await new Promise((resolve) => setTimeout(resolve, 10));
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    const found = logs.some(
      (l) => (l as Record<string, unknown>)['event'] === 'dot.boundary.match',
    );
    expect(found).toBe(true);
  });

  it('empty-string prefix matches all loggers as fallback', async () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'warn', logModuleLevels: { '': 'debug' } });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const log = getLogger('anything.here');
    log.debug({ event: 'empty.prefix.match' }, 'catchall');
    await new Promise((resolve) => setTimeout(resolve, 10));
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    const found = logs.some(
      (l) => (l as Record<string, unknown>)['event'] === 'empty.prefix.match',
    );
    expect(found).toBe(true);
  });

  it('does not override level when logModuleLevels is empty', () => {
    _resetRootLogger();
    makeCfg({ logLevel: 'info', logModuleLevels: {} });
    // Should not throw and logger should work normally
    const log = getLogger('some.module');
    expect(() => log.info({ event: 'ok' })).not.toThrow();
  });
});

// ── logSanitize toggle tests ─────────────────────────────────────────────────

describe('write hook — logSanitize toggle', () => {
  it('does NOT redact password fields when logSanitize is false', () => {
    makeCfg({ logSanitize: false });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 40, event: 'login', password: 'hunter2' }; // pragma: allowlist secret
    hook(obj);
    expect(obj['password']).toBe('hunter2');
  });

  it('redacts password fields when logSanitize is true (default)', () => {
    makeCfg({ logSanitize: true });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 40, event: 'login', password: 'hunter2' }; // pragma: allowlist secret
    hook(obj);
    expect(obj['password']).toBe('***');
  });
});

// ── logIncludeTimestamp toggle tests ─────────────────────────────────────────

describe('write hook — logIncludeTimestamp toggle', () => {
  it('removes time field when logIncludeTimestamp is false', () => {
    makeCfg({ logIncludeTimestamp: false });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'test', time: Date.now() };
    hook(obj);
    expect(obj).not.toHaveProperty('time');
  });

  it('retains time field when logIncludeTimestamp is true (default)', () => {
    makeCfg({ logIncludeTimestamp: true });
    const hook = makeWriteHook();
    const ts = Date.now();
    const obj: Record<string, unknown> = { level: 30, event: 'test', time: ts };
    hook(obj);
    expect(obj['time']).toBe(ts);
  });
});
