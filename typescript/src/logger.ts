// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Structured logger — wraps pino with:
 *   - browser.write hook in actual browsers; custom stream in Node.js/Vitest
 *   - window.__pinoLogs capture for Playwright/devtools inspection
 *   - Automatic context binding (from bindContext())
 *   - Automatic OTEL trace_id/span_id injection
 *   - PII sanitization
 *   - msg fallback: if msg is empty, defaults to obj.event
 *
 * Mirrors Python undef.telemetry get_logger().
 */

import pino from 'pino';
import { getConfig } from './config';
import { getContext } from './context';
import { sanitize } from './sanitize';
import { getActiveTraceIds } from './tracing';

/** Pino level number → console method name. */
const LEVEL_MAP: Record<number, string> = {
  10: 'trace',
  20: 'debug',
  30: 'log',
  40: 'warn',
  50: 'error',
  60: 'error',
};

/** Public Logger interface — consumers should type against this, not pino.Logger. */
export interface Logger {
  trace(obj: Record<string, unknown>, msg?: string): void;
  debug(obj: Record<string, unknown>, msg?: string): void;
  info(obj: Record<string, unknown>, msg?: string): void;
  warn(obj: Record<string, unknown>, msg?: string): void;
  error(obj: Record<string, unknown>, msg?: string): void;
  /** Create a child logger with additional bound fields. */
  child(bindings: Record<string, unknown>): Logger;
}

// Pino root instance — lazily created so config is read after setupTelemetry().
let _root: pino.Logger | null = null;

/**
 * Build the write hook that enriches, sanitizes, captures, and optionally
 * emits each log record.  Config is read dynamically on every invocation so
 * that resetTelemetryState() + setupTelemetry() changes take effect without
 * needing to rebuild the hook closure.
 */
export function makeWriteHook() {
  // pino's WriteFn signature uses `object`; we cast internally for safe property access.
  return (obj: object): void => {
    // Read config dynamically — avoids stale-capture bug after _resetConfig().
    const cfg = getConfig();
    const o = obj as Record<string, unknown>;

    // Inject OTEL trace/span IDs if an active span exists.
    const ids = getActiveTraceIds();
    if (ids.trace_id) o['trace_id'] = ids.trace_id;
    if (ids.span_id) o['span_id'] = ids.span_id;

    // Merge module-level context bindings.
    Object.assign(o, getContext());

    // Ensure msg is always non-empty — pino sets msg='' when no string arg is passed.
    if (!o['msg']) o['msg'] = o['event'] ?? '';

    // PII sanitization.
    sanitize(o, cfg.sanitizeFields);

    // Capture to window.__pinoLogs for Playwright and devtools inspection.
    // Check is done inline (not at module load) so it works when loaded in Node.js
    // test environments that later gain a jsdom window.
    if (typeof window !== 'undefined' && cfg.captureToWindow) {
      if (!('__pinoLogs' in window)) {
        (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
      }
      (window as unknown as Record<string, unknown[]>)['__pinoLogs'].push(o);
    }

    // Emit to console only when explicitly enabled (opt-in).
    if (cfg.consoleOutput) {
      const method = LEVEL_MAP[o['level'] as number] ?? 'log';
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (console as any)[method](o);
    }
  };
}

function getRootLogger(): pino.Logger {
  // Stryker disable next-line ConditionalExpression
  if (_root) return _root;
  const cfg = getConfig();
  const hook = makeWriteHook();

  // pino only invokes browser.write when process.version is absent (real browser).
  // In Node.js / Vitest, we use a custom destination stream that forwards every
  // serialised log line back through the write hook.
  // Stryker disable all
  const isNodeEnv = typeof process !== 'undefined' && typeof process.version === 'string';

  /* c8 ignore else */
  if (isNodeEnv) {
    const stream = {
      write(msg: string) {
        try {
          hook(JSON.parse(msg.trimEnd()) as object);
        } catch {
          // Ignore malformed lines (e.g. pino flush sentinels).
        }
      },
    };
    _root = pino(
      {
        base: { service: cfg.serviceName, env: cfg.environment, version: cfg.version },
        level: cfg.logLevel,
      },
      stream as unknown as pino.DestinationStream,
    );
  } else {
    /* c8 ignore next 8 */
    _root = pino({
      base: { service: cfg.serviceName, env: cfg.environment, version: cfg.version },
      level: cfg.logLevel,
      browser: {
        write: hook,
      },
    });
  }
  // Stryker enable all
  return _root;
}

function adaptPino(pinoLogger: pino.Logger): Logger {
  // Stryker disable all
  return {
    trace: (obj, msg) => pinoLogger.trace(obj, msg ?? ''),
    debug: (obj, msg) => pinoLogger.debug(obj, msg ?? ''),
    info: (obj, msg) => pinoLogger.info(obj, msg ?? ''),
    warn: (obj, msg) => pinoLogger.warn(obj, msg ?? ''),
    error: (obj, msg) => pinoLogger.error(obj, msg ?? ''),
    child: (bindings) => adaptPino(pinoLogger.child(bindings)),
  };
  // Stryker enable all
}

/**
 * Return a logger for the given name.
 * Name appears as the `name` field in every log record.
 * Mirrors Python: get_logger(name)
 */
export function getLogger(name?: string): Logger {
  const root = getRootLogger();
  // Stryker disable next-line ObjectLiteral
  const pinoLogger = name ? root.child({ name }) : root;
  return adaptPino(pinoLogger);
}

/** Reset the root logger (forces re-creation with current config on next call). */
// Stryker disable next-line BlockStatement
export function _resetRootLogger(): void {
  _root = null;
}

/** Module-level lazy singleton logger. Mirrors Python: logger = get_logger('default'). */
// Stryker disable all
export const logger: Logger = {
  trace: (obj, msg) => getLogger('default').trace(obj, msg),
  debug: (obj, msg) => getLogger('default').debug(obj, msg),
  info: (obj, msg) => getLogger('default').info(obj, msg),
  warn: (obj, msg) => getLogger('default').warn(obj, msg),
  error: (obj, msg) => getLogger('default').error(obj, msg),
  child: (bindings) => getLogger('default').child(bindings),
};
// Stryker enable all
