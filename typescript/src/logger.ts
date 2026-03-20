// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Structured logger — wraps pino with:
 *   - browser.write hook (correct hook for capture; avoids the console-caching bug)
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

// Stryker disable next-line ConditionalExpression,StringLiteral
const isBrowser = typeof window !== 'undefined';

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

export function makeWriteHook(cfg: ReturnType<typeof getConfig>) {
  // pino's WriteFn signature uses `object`; we cast internally for safe property access.
  return (obj: object): void => {
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
    if (isBrowser && cfg.captureToWindow) {
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
  // Stryker disable all
  _root = pino({
    base: { service: cfg.serviceName, env: cfg.environment, version: cfg.version },
    level: cfg.logLevel,
    browser: {
      write: makeWriteHook(cfg),
    },
  });
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
