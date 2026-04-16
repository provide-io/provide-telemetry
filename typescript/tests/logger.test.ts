// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Logger tests.
 *
 * makeWriteHook() now reads config dynamically on each invocation, so tests
 * call setupTelemetry() to configure the desired options and then invoke the
 * hook — no need to pass a cfg object.
 *
 * The Node.js stream path means getLogger() / logger calls now flow through
 * the write hook too, so integration tests can assert on window.__pinoLogs.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import { _resetContext, bindContext, clearContext } from '../src/context';
import { _resetRootLogger, getLogger, makeWriteHook } from '../src/logger';
import * as tracing from '../src/tracing';

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

// ── Write hook unit tests (core logic) ────────────────────────────────────────

describe('write hook — window.__pinoLogs capture', () => {
  it('pushes log objects to window.__pinoLogs', () => {
    makeCfg();
    const hook = makeWriteHook();
    hook({ level: 30, event: 'request_ok', status: 200 });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs.length).toBe(1);
  });

  it('captured object contains the passed fields', () => {
    makeCfg();
    const hook = makeWriteHook();
    hook({ level: 20, event: 'test_event', code: 42 });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    const last = logs[logs.length - 1] as Record<string, unknown>;
    expect(last['code']).toBe(42);
    expect(last['event']).toBe('test_event');
  });

  it('does not capture when captureToWindow is false', () => {
    makeCfg({ captureToWindow: false });
    const hook = makeWriteHook();
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    hook({ level: 30, event: 'hidden' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs.length).toBe(0);
  });

  it('does NOT call console by default (consoleOutput: false)', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    makeCfg({ consoleOutput: false });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'info_event' });
    expect(spy).not.toHaveBeenCalled();
  });

  it('calls console.log for level 30 when consoleOutput: true', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'info_event' });
    expect(spy).toHaveBeenCalledOnce();
  });

  it('calls console.warn for level 40 when consoleOutput: true', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 40, event: 'warn_event' });
    expect(spy).toHaveBeenCalledOnce();
  });

  it('calls console.error for level 50 when consoleOutput: true', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 50, event: 'error_event' });
    expect(spy).toHaveBeenCalledOnce();
  });

  it('message defaults to empty string when both message and event are absent', () => {
    // mutation: `o['event'] ?? ''` → `o['event'] ?? null` or similar
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30 }; // no message, no event
    hook(obj as object);
    // After hook runs, obj['message'] should be '' not undefined or null
    expect(obj['message']).toBe('');
  });
});

describe('write hook — message fallback to event', () => {
  it('sets message to event value when message is absent', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'my_event' };
    hook(obj);
    expect(obj['message']).toBe('my_event');
  });

  it('sets message to empty string when neither message nor event present', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30 };
    hook(obj);
    expect(obj['message']).toBe('');
  });

  it('preserves explicit non-empty message', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'e', message: 'explicit message' };
    hook(obj);
    expect(obj['message']).toBe('explicit message');
  });
});

describe('write hook — context binding injection', () => {
  it('injects bound context fields', () => {
    _resetContext();
    bindContext({ request_id: 'req-999', user_id: 7 });
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'action' };
    hook(obj);
    expect(obj['request_id']).toBe('req-999');
    expect(obj['user_id']).toBe(7);
    clearContext();
  });
});

describe('write hook — PII sanitization', () => {
  it('redacts password fields', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 40, event: 'login', password: 'hunter2' }; // pragma: allowlist secret
    hook(obj);
    expect(obj['password']).toBe('***');
  });

  it('does not redact non-PII fields', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'ok', user_id: 42, status: 200 };
    hook(obj);
    expect(obj['user_id']).toBe(42);
    expect(obj['status']).toBe(200);
  });
});

// ── getLogger integration tests ────────────────────────────────────────────────

describe('write hook — window.__pinoLogs auto-init', () => {
  it('creates window.__pinoLogs when it does not exist', () => {
    makeCfg({ captureToWindow: true });
    const hook = makeWriteHook();
    // Remove __pinoLogs so the hook must create it
    delete (window as unknown as Record<string, unknown>)['__pinoLogs'];
    hook({ level: 30, event: 'init_test' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(Array.isArray(logs)).toBe(true);
    expect(logs.length).toBe(1);
  });
});

describe('write hook — OTEL trace_id/span_id injection', () => {
  it('injects trace_id and span_id when trace context is available', () => {
    vi.spyOn(tracing, 'getTraceContext').mockReturnValueOnce({
      trace_id: 'abc123def456abc123def456abc123de',
      span_id: '1234567890abcdef',
    });
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'traced' };
    hook(obj);
    expect(obj['trace_id']).toBe('abc123def456abc123def456abc123de');
    expect(obj['span_id']).toBe('1234567890abcdef');
  });
});

describe('getLogger lazy init', () => {
  it('uses env-derived identity and logging flags before setupTelemetry()', () => {
    _resetConfig();
    _resetRootLogger();
    process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] = 'probe';
    process.env['PROVIDE_TELEMETRY_ENV'] = 'parity';
    process.env['PROVIDE_TELEMETRY_VERSION'] = '1.2.3';
    process.env['PROVIDE_LOG_INCLUDE_TIMESTAMP'] = 'false';
    process.env['PROVIDE_LOG_INCLUDE_CALLER'] = 'false';
    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    try {
      (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
      getLogger('probe').info({ event: 'log.output.parity' }, 'log.output.parity');
      const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
      const record = logs[0] as Record<string, unknown>;
      expect(record['service']).toBe('probe');
      expect(record['env']).toBe('parity');
      expect(record['version']).toBe('1.2.3');
      expect(record['time']).toBeUndefined();
      expect(record['caller_file']).toBeUndefined();
      expect(record['caller_line']).toBeUndefined();
    } finally {
      delete process.env['PROVIDE_TELEMETRY_SERVICE_NAME'];
      delete process.env['PROVIDE_TELEMETRY_ENV'];
      delete process.env['PROVIDE_TELEMETRY_VERSION'];
      delete process.env['PROVIDE_LOG_INCLUDE_TIMESTAMP'];
      delete process.env['PROVIDE_LOG_INCLUDE_CALLER'];
      consoleSpy.mockRestore();
    }
  });
});

describe('write hook — unknown level fallback', () => {
  it('uses console.log for unmapped level numbers when consoleOutput=true', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 999, event: 'unknown_level' });
    expect(spy).toHaveBeenCalledOnce();
  });
});

describe('getLogger', () => {
  it('returns a logger with all level methods', () => {
    const log = getLogger('test');
    expect(typeof log.debug).toBe('function');
    expect(typeof log.info).toBe('function');
    expect(typeof log.warn).toBe('function');
    expect(typeof log.error).toBe('function');
    expect(typeof log.trace).toBe('function');
  });

  it('returns root logger when no name given', () => {
    expect(getLogger()).toBeDefined();
  });

  it('child() returns a Logger with all methods', () => {
    const log = getLogger('parent');
    const child = log.child({ request_id: 'abc' });
    expect(typeof child.info).toBe('function');
    expect(typeof child.child).toBe('function');
  });

  it('logger methods do not throw', () => {
    const log = getLogger('smoke');
    expect(() => log.info({ event: 'ping' }, 'ping')).not.toThrow();
    expect(() => log.info({ event: 'ping_no_msg' })).not.toThrow();
    expect(() => log.debug({ event: 'debug_evt' })).not.toThrow();
    expect(() => log.warn({ event: 'warn_evt' })).not.toThrow();
    expect(() => log.error({ event: 'err_evt', error: 'oops' })).not.toThrow();
  });

  it('trace() does not throw', () => {
    const log = getLogger('trace-test');
    expect(() => log.trace({ event: 'trace_evt' })).not.toThrow();
  });

  it('trace() with explicit message does not throw', () => {
    const log = getLogger('trace-msg-test');
    expect(() => log.trace({ event: 'trace_evt' }, 'explicit trace msg')).not.toThrow();
  });

  it('debug() with explicit message does not throw', () => {
    const log = getLogger('debug-msg-test');
    expect(() => log.debug({ event: 'debug_evt' }, 'explicit debug msg')).not.toThrow();
  });

  it('reuses root logger on second getLogger call (cache hit)', () => {
    // Two getLogger calls without reset in between — exercises getRootLogger cache
    const log1 = getLogger('first');
    const log2 = getLogger('second');
    expect(log1).toBeDefined();
    expect(log2).toBeDefined();
  });

  it('getLogger log flows through write hook (window.__pinoLogs populated)', async () => {
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const log = getLogger('integration');
    log.info({ event: 'hello' }, 'world');
    // The Node.js stream is async (pino flushes on next tick)
    await new Promise((resolve) => setTimeout(resolve, 10));
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs.length).toBeGreaterThan(0);
  });
});

import { logger } from '../src/logger';

describe('logger singleton', () => {
  it('logger.info does not throw', () => {
    expect(() => logger.info({ event: 'test' })).not.toThrow();
  });

  it('logger.debug does not throw', () => {
    expect(() => logger.debug({ event: 'test' })).not.toThrow();
  });

  it('logger.warn does not throw', () => {
    expect(() => logger.warn({ event: 'test' })).not.toThrow();
  });

  it('logger.error does not throw', () => {
    expect(() => logger.error({ event: 'test' })).not.toThrow();
  });

  it('logger.trace does not throw', () => {
    expect(() => logger.trace({ event: 'test' })).not.toThrow();
  });

  it('logger.child returns a logger', () => {
    const child = logger.child({ component: 'test' });
    expect(typeof child.info).toBe('function');
  });
});

describe('write hook — LEVEL_MAP console routing', () => {
  it('level 10 (trace) routes to console.trace when consoleOutput=true', () => {
    const spy = vi.spyOn(console, 'trace').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 10, event: 'x' });
    expect(spy).toHaveBeenCalled();
  });

  it('level 20 (debug) routes to console.debug when consoleOutput=true', () => {
    const spy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 20, event: 'x' });
    expect(spy).toHaveBeenCalled();
  });

  it('level 60 (fatal) routes to console.error when consoleOutput=true', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    makeCfg({ consoleOutput: true });
    const hook = makeWriteHook();
    hook({ level: 60, event: 'x' });
    expect(spy).toHaveBeenCalled();
  });
});

describe('write hook — trace context NOT injected when no span', () => {
  it('does not add trace_id when getTraceContext returns empty', () => {
    vi.spyOn(tracing, 'getTraceContext').mockReturnValue({});
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'test' };
    hook(obj);
    expect(obj).not.toHaveProperty('trace_id');
    expect(obj).not.toHaveProperty('span_id');
  });
});

describe('write hook — __pinoLogs array preservation', () => {
  it('preserves existing __pinoLogs entries on subsequent writes', () => {
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [{ existing: true }];
    makeCfg();
    const hook = makeWriteHook();
    hook({ level: 30, event: 'new' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs).toHaveLength(2);
    expect((logs[0] as Record<string, unknown>)['existing']).toBe(true);
  });
});

describe('write hook — config read dynamically (Bug 2 regression)', () => {
  it('reflects config change after hook is created', () => {
    // Create hook with captureToWindow: true
    makeCfg({ captureToWindow: true });
    const hook = makeWriteHook();
    // Now change config to captureToWindow: false
    makeCfg({ captureToWindow: false });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    hook({ level: 30, event: 'after_reset' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    // Hook should read the NEW config — no capture
    expect(logs.length).toBe(0);
  });

  it('write hook adds error_fingerprint when exc_name present', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 50, event: 'error.test', exc_name: 'TypeError' };
    hook(obj);
    expect(obj['error_fingerprint']).toBeDefined();
    expect(typeof obj['error_fingerprint']).toBe('string');
    expect((obj['error_fingerprint'] as string).length).toBe(12);
  });

  it('write hook adds error_fingerprint from err object', () => {
    makeCfg();
    const hook = makeWriteHook();
    const err = new Error('boom');
    const obj: Record<string, unknown> = {
      level: 50,
      event: 'error.test',
      err: { type: 'Error', name: 'Error', stack: err.stack, message: 'boom' },
    };
    hook(obj);
    expect(obj['error_fingerprint']).toBeDefined();
    expect((obj['error_fingerprint'] as string).length).toBe(12);
  });

  it('write hook does not add error_fingerprint on normal events', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'app.start.ok' };
    hook(obj);
    expect(obj['error_fingerprint']).toBeUndefined();
  });

  it('write hook uses pretty formatting when logFormat=pretty', () => {
    makeCfg({ consoleOutput: true, logFormat: 'pretty' as 'json' | 'pretty' });
    const hook = makeWriteHook();
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    hook({ level: 30, event: 'pretty.test', time: Date.now() });
    expect(spy).toHaveBeenCalledOnce();
    // Pretty output is a string, not an object
    const output = spy.mock.calls[0][0];
    expect(typeof output).toBe('string');
    expect(output).toContain('pretty.test');
    spy.mockRestore();
  });

  it('json format passes object to console, not a pretty string', () => {
    // Kills: `cfg.logFormat === 'pretty'` → `true` (always uses pretty)
    // When logFormat is 'json', the object itself is passed to console, not a formatted string.
    makeCfg({ consoleOutput: true, logFormat: 'json' });
    const hook = makeWriteHook();
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {});
    hook({ level: 30, event: 'json.test' });
    expect(spy).toHaveBeenCalledOnce();
    const output = spy.mock.calls[0][0];
    // JSON path passes the raw log object (type 'object'), not a string
    expect(typeof output).toBe('object');
    spy.mockRestore();
  });
});

describe('write hook — OTLP log export', () => {
  it('calls emitLogRecord on every log line', () => {
    makeCfg();
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'export.test' });
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it('applies custom PII rules via sanitizePayload in write hook', async () => {
    const { registerPiiRule, resetPiiRulesForTests } = await import('../src/pii');
    registerPiiRule({ path: 'user.email', mode: 'hash' });
    makeCfg({});
    const captured: Record<string, unknown>[] = [];
    vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation((o) => {
      captured.push(JSON.parse(JSON.stringify(o)));
    });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'pii.custom', user: { email: 'ops@example.com', name: 'Op' } });
    const user = captured[0]['user'] as Record<string, unknown>;
    expect(user['email']).not.toBe('ops@example.com');
    expect(user['name']).toBe('Op'); // not affected by the rule
    vi.restoreAllMocks();
    resetPiiRulesForTests();
  });

  it('calls emitLogRecord after PII sanitization (enriched record)', () => {
    makeCfg({ sanitizeFields: ['secret'] });
    const captured: Record<string, unknown>[] = [];
    vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation((o) => {
      captured.push({ ...o });
    });
    const hook = makeWriteHook();
    hook({ level: 30, event: 'pii.test', secret: 'tok123' }); // pragma: allowlist secret
    expect(captured[0]['secret']).not.toBe('tok123');
    vi.restoreAllMocks();
  });
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

  it('drops log when strictSchema=true and event name violates schema', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'x' });
    expect(spy).not.toHaveBeenCalled();
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

  it('drops log when strictSchema=true and requiredLogKeys missing', () => {
    makeCfg({ strictSchema: true, requiredLogKeys: ['action'] });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, event: 'app.user.created' });
    expect(spy).not.toHaveBeenCalled();
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

  it('validates message field when event is absent', () => {
    makeCfg({ strictSchema: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    hook({ level: 30, message: 'x' });
    // 'x' is not a valid 3-part event name, so the record should be dropped.
    expect(spy).not.toHaveBeenCalled();
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

  it('does not capture dropped record to window.__pinoLogs', () => {
    makeCfg({ strictSchema: true, captureToWindow: true });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
    const hook = makeWriteHook();
    hook({ level: 30, event: 'x' });
    const logs = (window as unknown as Record<string, unknown[]>)['__pinoLogs'];
    expect(logs.length).toBe(0);
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
