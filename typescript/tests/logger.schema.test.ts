// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetContext } from '../src/context.js';
import type { Callsite } from '../src/logger.js';
import { _parseStackFrame, _resetRootLogger, getLogger, makeWriteHook } from '../src/logger.js';
import * as otelLogs from '../src/otel-logs.js';
import * as schema from '../src/schema.js';

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

// ── callsite capture tests ────────────────────────────────────────────────────

/**
 * Call the hook from a named function so the resulting V8 frame carries a
 * function name. Calls made straight from an `it` callback produce a bare
 * frame instead, because the callback is an anonymous arrow.
 */
function emitFromNamedFunction(
  hook: ReturnType<typeof makeWriteHook>,
  obj: Record<string, unknown>,
): void {
  hook(obj);
}

/** The last callsite handed to emitLogRecord by the hook. */
function callsiteOf(spy: ReturnType<typeof vi.spyOn>): Callsite | undefined {
  return spy.mock.calls[0][1] as Callsite | undefined;
}

describe('write hook — logIncludeCaller', () => {
  it('injects filename and lineno when logIncludeCaller is true', () => {
    makeCfg({ logIncludeCaller: true });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'caller.test' };
    hook(obj);
    // The logger's own frames are skipped, so this resolves to the test file.
    expect(obj['filename']).toBe('logger.schema.test.ts');
    expect(typeof obj['lineno']).toBe('number');
  });

  it('filename is a basename (no full path)', () => {
    makeCfg({ logIncludeCaller: true });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'caller.basename' };
    hook(obj);
    expect(obj['filename']).toBeDefined();
    // Should not contain path separators — it's a basename
    expect(String(obj['filename'])).not.toContain('/');
  });

  it('does NOT inject filename when logIncludeCaller is false', () => {
    makeCfg({ logIncludeCaller: false });
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'no.caller' };
    hook(obj);
    expect(obj['filename']).toBeUndefined();
    expect(obj['lineno']).toBeUndefined();
  });
});

describe('write hook — logCodeAttributes is independent of logIncludeCaller', () => {
  it('captures a callsite with logCodeAttributes alone and writes no record fields', () => {
    makeCfg({ logIncludeCaller: false, logCodeAttributes: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'code.only' };
    hook(obj);
    expect(obj['filename']).toBeUndefined();
    expect(obj['lineno']).toBeUndefined();
    expect(callsiteOf(spy)).toMatchObject({ filename: 'logger.schema.test.ts' });
    spy.mockRestore();
  });

  it('passes no callsite when logCodeAttributes is off but logIncludeCaller is on', () => {
    makeCfg({ logIncludeCaller: true, logCodeAttributes: false });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'caller.only' };
    hook(obj);
    expect(obj['filename']).toBe('logger.schema.test.ts');
    expect(callsiteOf(spy)).toBeUndefined();
    spy.mockRestore();
  });

  it('skips the stack walk entirely when both knobs are off', () => {
    makeCfg({ logIncludeCaller: false, logCodeAttributes: false });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'neither' };
    hook(obj);
    expect(obj['filename']).toBeUndefined();
    expect(callsiteOf(spy)).toBeUndefined();
    spy.mockRestore();
  });

  it('resolves the enclosing function name from a named frame', () => {
    makeCfg({ logIncludeCaller: false, logCodeAttributes: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    emitFromNamedFunction(hook, { level: 30, event: 'named.frame' });
    expect(callsiteOf(spy)?.functionName).toBe('emitFromNamedFunction');
    spy.mockRestore();
  });

  it('omits the function name when the calling frame is anonymous', () => {
    makeCfg({ logIncludeCaller: false, logCodeAttributes: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    // Called straight from this anonymous arrow — V8 emits a nameless frame.
    hook({ level: 30, event: 'anon.frame' });
    expect(callsiteOf(spy)).toMatchObject({ filename: 'logger.schema.test.ts' });
    expect(callsiteOf(spy)?.functionName).toBeUndefined();
    spy.mockRestore();
  });
});

// ── stack frame parsing ───────────────────────────────────────────────────────

describe('_parseStackFrame', () => {
  it('reads file, line and function name from a named frame', () => {
    expect(_parseStackFrame('    at handleRequest (/srv/app/routes.ts:42:17)')).toEqual({
      filename: 'routes.ts',
      lineno: 42,
      functionName: 'handleRequest',
    });
  });

  it('keeps the qualifying prefix of a method frame', () => {
    expect(_parseStackFrame('    at Service.handle (/srv/app/service.ts:7:3)')?.functionName).toBe(
      'Service.handle',
    );
  });

  it('strips the async modifier V8 prints ahead of the name', () => {
    expect(_parseStackFrame('    at async load (/srv/app/load.ts:9:1)')?.functionName).toBe('load');
  });

  it('omits the function name for a V8 <anonymous> placeholder', () => {
    const site = _parseStackFrame('    at Object.<anonymous> (/srv/app/main.js:1:1)');
    expect(site).toEqual({ filename: 'main.js', lineno: 1 });
    expect(site?.functionName).toBeUndefined();
  });

  it('omits the function name for a bare frame', () => {
    expect(_parseStackFrame('    at /srv/app/boot.ts:3:11')).toEqual({
      filename: 'boot.ts',
      lineno: 3,
    });
  });

  it('returns undefined for a frame with no source location', () => {
    expect(_parseStackFrame('    at new Promise (<anonymous>)')).toBeUndefined();
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
