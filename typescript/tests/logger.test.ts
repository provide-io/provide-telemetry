// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

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
});

describe('write hook — msg fallback to event', () => {
  it('sets msg to event value when msg is absent', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'my_event' };
    hook(obj);
    expect(obj['msg']).toBe('my_event');
  });

  it('sets msg to empty string when neither msg nor event present', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30 };
    hook(obj);
    expect(obj['msg']).toBe('');
  });

  it('preserves explicit non-empty msg', () => {
    makeCfg();
    const hook = makeWriteHook();
    const obj: Record<string, unknown> = { level: 30, event: 'e', msg: 'explicit message' };
    hook(obj);
    expect(obj['msg']).toBe('explicit message');
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
    const obj: Record<string, unknown> = { level: 40, event: 'login', password: 'hunter2' };
    hook(obj);
    expect(obj['password']).toBe('[REDACTED]');
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
  it('injects trace_id and span_id when active span has non-zero IDs', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValueOnce({
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
    await new Promise(resolve => setTimeout(resolve, 10));
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
  it('does not add trace_id when getActiveTraceIds returns empty', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({});
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
});
