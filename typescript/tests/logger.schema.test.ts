// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { _resetContext } from '../src/context.js';
import type { Callsite } from '../src/logger.js';
import {
  _firstCallerFrame,
  _parseStackFrame,
  _resetRootLogger,
  getLogger,
  makeWriteHook,
} from '../src/logger.js';
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

  it('emits the record with no callsite when a host owns Error.prepareStackTrace', () => {
    // Source-map and tracing libraries install their own formatter, and then
    // `.stack` is whatever it returns — an array of CallSite objects, usually.
    // Reading that as a string throws, and in a browser pino has no catch
    // around the hook, so the throw reaches the application's log call.
    makeCfg({ logIncludeCaller: true, logCodeAttributes: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    const original = Error.prepareStackTrace;
    Error.prepareStackTrace = (_err, frames) => frames;
    try {
      const obj: Record<string, unknown> = { level: 30, event: 'prepared.stack' };
      expect(() => hook(obj)).not.toThrow();
      expect(obj['filename']).toBeUndefined();
      expect(obj['lineno']).toBeUndefined();
      expect(callsiteOf(spy)).toBeUndefined();
    } finally {
      Error.prepareStackTrace = original;
      spy.mockRestore();
    }
  });

  it('emits the record with no callsite when the stack holds no caller frame', () => {
    // Error.stackTraceLimit = 0 yields a header and nothing else, which is the
    // same shape a bundled build produces: no frame is the caller's.
    makeCfg({ logIncludeCaller: true, logCodeAttributes: true });
    const spy = vi.spyOn(otelLogs, 'emitLogRecord').mockImplementation(() => {});
    const hook = makeWriteHook();
    const original = Error.stackTraceLimit;
    Error.stackTraceLimit = 0;
    try {
      const obj: Record<string, unknown> = { level: 30, event: 'no.frames' };
      hook(obj);
      expect(obj['filename']).toBeUndefined();
      expect(callsiteOf(spy)).toBeUndefined();
    } finally {
      Error.stackTraceLimit = original;
      spy.mockRestore();
    }
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
      path: '/srv/app/routes.ts',
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
    expect(site).toEqual({ filename: 'main.js', path: '/srv/app/main.js', lineno: 1 });
    expect(site?.functionName).toBeUndefined();
  });

  it('omits the function name for a bare frame', () => {
    expect(_parseStackFrame('    at /srv/app/boot.ts:3:11')).toEqual({
      filename: 'boot.ts',
      path: '/srv/app/boot.ts',
      lineno: 3,
    });
  });

  it('returns undefined for a frame with no source location', () => {
    expect(_parseStackFrame('    at new Promise (<anonymous>)')).toBeUndefined();
  });

  it('strips a Windows path, which a CJS frame reports with backslashes', () => {
    // `filename` is specified as a base name. Stripping only forward slashes
    // publishes `C:\srv\app\routes.ts` whole — the build machine's layout, on
    // every record, on the platform where CJS output is still common.
    expect(_parseStackFrame('    at handleRequest (C:\\srv\\app\\routes.ts:42:17)')).toEqual({
      filename: 'routes.ts',
      path: 'C:\\srv\\app\\routes.ts',
      lineno: 42,
      functionName: 'handleRequest',
    });
  });

  it('returns undefined for a nested-eval frame', () => {
    // Two locations inside one set of parentheses. Every path group here would
    // swallow both and publish `main.js:1:1), <anonymous>` as a filename.
    expect(
      _parseStackFrame('    at eval (eval at <anonymous> (/app/main.js:1:1), <anonymous>:1:1)'),
    ).toBeUndefined();
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

describe('_firstCallerFrame', () => {
  const caller = '    at handleRequest (/srv/app/routes.ts:42:17)';
  const capture = '    at captureCallsite (/pkg/src/logger.ts:150:9)';

  it('skips this module in the source tree', () => {
    expect(_firstCallerFrame([capture, caller])).toBe(caller);
  });

  it('skips this module in the published build', () => {
    // The frame consumers actually get: they import dist/logger.js, never the
    // .ts source. Frame 0 is this module's own by construction, whatever the
    // file is called, so the build the consumer runs needs no separate rule.
    expect(_firstCallerFrame(['    at captureCallsite (/pkg/dist/logger.js:150:9)', caller])).toBe(
      caller,
    );
  });

  it('skips every later frame from the same file as the capture frame', () => {
    expect(_firstCallerFrame([capture, '    at hook (/pkg/src/logger.ts:410:5)', caller])).toBe(
      caller,
    );
  });

  it('skips pino frames, including a pnpm store path', () => {
    expect(
      _firstCallerFrame([
        capture,
        '    at Pino.write (/pkg/node_modules/pino/lib/proto.js:210:9)',
        '    at Object.info (/pkg/node_modules/.pnpm/pino@9.5.0/node_modules/pino/index.js:11:2)',
        '    at push (/pkg/node_modules/pino-abstract-transport/index.js:3:1)',
        caller,
      ]),
    ).toBe(caller);
  });

  it('reports a dependency that logs, rather than whoever called it', () => {
    // Skipping every node_modules frame made any library using this logger
    // invisible: its records named the application file that called *it*.
    const dependency = '    at query (/srv/app/node_modules/@acme/db/query.ts:4:3)';
    expect(_firstCallerFrame([capture, dependency, caller])).toBe(dependency);
  });

  it('reports a caller working under a directory named pino', () => {
    const inPinoDir = '    at handle (/home/pino/app/handler.ts:4:3)';
    expect(_firstCallerFrame([capture, inPinoDir])).toBe(inPinoDir);
  });

  it('reports a caller whose own file is named logger.ts', () => {
    // A consumer wrapping this SDK in their own logger.ts is the common case,
    // and a file-name skip list attributes their records to their caller.
    const consumerLogger = '    at log (/srv/app/src/logger.ts:12:3)';
    expect(_firstCallerFrame([capture, consumerLogger])).toBe(consumerLogger);
  });

  it('skips a frame with no source position rather than reporting it', () => {
    expect(_firstCallerFrame([capture, '    at new Promise (<anonymous>)', caller])).toBe(caller);
  });

  it('returns undefined when every frame shares the capture frame file', () => {
    // A bundle. There is no way to tell the caller from the logger inside one
    // file, and naming the logger's own line is a wrong answer, not a missing
    // one.
    expect(
      _firstCallerFrame([
        '    at captureCallsite (/srv/app/out.cjs:7125:20)',
        '    at hook (/srv/app/out.cjs:7180:5)',
        '    at handleRequest (/srv/app/out.cjs:7391:9)',
      ]),
    ).toBeUndefined();
  });

  it('returns undefined when the capture frame is the only one', () => {
    expect(_firstCallerFrame([capture])).toBeUndefined();
  });

  it('returns undefined for an empty stack', () => {
    expect(_firstCallerFrame([])).toBeUndefined();
  });
});

// ── colour follows the stream the record is actually written to ──────────────

describe('write hook — colour is decided per destination stream', () => {
  /**
   * The wiring, not the helper. supportsColor now takes a stream, and this is
   * what proves the level's real destination is what it is asked about:
   * console.debug/log go to stdout and carry trace, debug and info, while only
   * warn and error reach stderr.
   */
  function withStreams(stdoutTTY: boolean, stderrTTY: boolean, body: () => void): void {
    const origProcess = globalThis.process;
    const origForceColor = process.env['FORCE_COLOR'];
    const origNoColor = process.env['NO_COLOR'];
    try {
      delete process.env['FORCE_COLOR'];
      delete process.env['NO_COLOR'];
      vi.stubGlobal('process', {
        ...origProcess,
        env: { ...origProcess.env },
        stdout: { ...origProcess.stdout, isTTY: stdoutTTY },
        stderr: { ...origProcess.stderr, isTTY: stderrTTY },
      });
      body();
    } finally {
      if (origForceColor === undefined) delete process.env['FORCE_COLOR'];
      else process.env['FORCE_COLOR'] = origForceColor;
      if (origNoColor === undefined) delete process.env['NO_COLOR'];
      else process.env['NO_COLOR'] = origNoColor;
      vi.unstubAllGlobals();
    }
  }

  it('colours an info record from stdout, and an error record from stderr', () => {
    makeCfg({ logFormat: 'pretty', consoleOutput: true });
    const hook = makeWriteHook();
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});

    withStreams(true, false, () => {
      hook({ level: 30, event: 'stream.info.ok' });
      hook({ level: 50, event: 'stream.error.ok' });
    });

    expect(String(log.mock.calls[0]?.[0])).toContain('\x1b[');
    expect(String(err.mock.calls[0]?.[0])).not.toContain('\x1b[');

    log.mockRestore();
    err.mockRestore();
  });

  it('and the other way round when only stderr is a terminal', () => {
    makeCfg({ logFormat: 'pretty', consoleOutput: true });
    const hook = makeWriteHook();
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});

    withStreams(false, true, () => {
      hook({ level: 30, event: 'stream.info.ok' });
      hook({ level: 50, event: 'stream.error.ok' });
    });

    expect(String(log.mock.calls[0]?.[0])).not.toContain('\x1b[');
    expect(String(err.mock.calls[0]?.[0])).toContain('\x1b[');

    log.mockRestore();
    err.mockRestore();
  });
});
