// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Structured logger — wraps pino with:
 *   - browser.write hook in actual browsers; custom stream in Node.js/Vitest
 *   - window.__pinoLogs capture for Playwright/devtools inspection
 *   - Automatic context binding (from bindContext())
 *   - Automatic OTEL trace_id/span_id injection
 *   - PII sanitization
 *   - message fallback: if message is empty, defaults to obj.event
 *
 * Mirrors Python provide.telemetry get_logger().
 */

import pino from 'pino';
import { configFromEnv, getConfig, _getConfigVersion } from './config';
import { getContext } from './context';
import { computeErrorFingerprint } from './fingerprint';
import { sanitize } from './sanitize';
import { EventSchemaError, validateEventName, validateRequiredKeys } from './schema';
import { tryAcquire, release } from './backpressure';
import { shouldSample } from './sampling';
import { getTraceContext } from './tracing';

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
let _rootConfigVersion = -1;

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

    // Consent gate: drop records the current consent level forbids.
    const levelLabel = CONSENT_LEVEL_MAP[o['level'] as number] ?? 'info';
    if (!shouldAllow('logs', levelLabel)) return;

    // Sampling gate: probabilistically drop records based on configured rate.
    // Pass the canonical event key so per-event override rates take effect.
    const samplingKey = String(o['event'] ?? o['message'] ?? '');
    if (!shouldSample('logs', samplingKey)) return;

    // Backpressure gate: drop when the log queue is full.
    const ticket = tryAcquire('logs');
    if (!ticket) return;

    // Error fingerprinting — stable hash from error name + stack.
    const errObj = o['err'] as Record<string, unknown> | undefined;
    const excName = (o['exc_name'] ?? o['exception'] ?? errObj?.['type'] ?? errObj?.['name']) as
      | string
      | undefined;
    if (excName) {
      const stack = (errObj?.['stack'] ?? o['stack']) as string | undefined;
      o['error_fingerprint'] = computeErrorFingerprint(String(excName), stack);
    }

    // PII sanitization.
    sanitize(o, cfg.sanitizeFields);

    // Capture to window.__pinoLogs for Playwright and devtools inspection.
    // Check is done inline (not at module load) so it works when loaded in Node.js
    // test environments that later gain a jsdom window.
    if (typeof window !== 'undefined' && cfg.captureToWindow) {
      if (!('__pinoLogs' in window)) {
        (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
      }
      // Stryker enable all

      // Error fingerprinting — stable hash from error name + stack.
      const errObj = o['err'] as Record<string, unknown> | undefined;
      const excName = (o['exc_name'] ?? o['exception'] ?? errObj?.['type'] ?? errObj?.['name']) as
        | string
        | undefined;
      if (excName) {
        const stack = (errObj?.['stack'] ?? o['stack']) as string | undefined;
        o['error_fingerprint'] = computeErrorFingerprint(String(excName), stack);
      }

      // PII sanitization: blocked keys + secret detection + custom PII rules.
      if (cfg.logSanitize) {
        sanitize(o, cfg.sanitizeFields);
        sanitizePayload(o, [], { maxDepth: cfg.piiMaxDepth });
      }

      // Strip timestamp when configured off.
      if (!cfg.logIncludeTimestamp) {
        delete o['time'];
      }

      // Schema validation — annotate instead of dropping.
      // Preserves telemetry while flagging violations via _schema_error.
      // Cross-language standard (Python/Rust/Go match).
      if (cfg.requiredLogKeys.length > 0) {
        try {
          validateRequiredKeys(o, cfg.requiredLogKeys);
        } catch (e) {
          if (e instanceof EventSchemaError) {
            o['_schema_error'] = (e as EventSchemaError).message;
          } else {
            throw e;
          }
        }
      }
      /* v8 ignore next -- V8 cannot fully attribute all ?? branches in a single expression */
      if (cfg.strictSchema || cfg.strictEventName) {
        const event = String(o['event'] ?? o['message'] ?? '');
        if (event) {
          try {
            validateEventName(event);
          } catch (e) {
            if (e instanceof EventSchemaError) {
              o['_schema_error'] = (e as EventSchemaError).message;
            } else {
              throw e;
            }
          }
        }
      }

      // Count every record that survives all filters as emitted.
      _incrementHealth(_emittedField('logs'));

      // Export to OTLP when a log provider is registered (noop otherwise).
      emitLogRecord(o);

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
        if (cfg.logFormat === 'pretty' || cfg.logFormat === 'console') {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (console as any)[method](formatPretty(o, supportsColor()));
        } else {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (console as any)[method](JSON.stringify(o));
        }
      }
    } finally {
      release(ticket);
    }
  };
}

function getRootLogger(): pino.Logger {
  const currentVersion = _getConfigVersion();
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
 * Find the longest-prefix match in logModuleLevels for the given logger name.
 * Returns the matched level string, or undefined if no match.
 * Mirrors Python _LevelFilter longest-prefix matching.
 */
function findModuleLevel(name: string, moduleLevels: Record<string, string>): string | undefined {
  let bestMatch: string | undefined;
  let bestLen = -1;
  for (const prefix of Object.keys(moduleLevels)) {
    if (
      (prefix === '' || name === prefix || name.startsWith(prefix + '.')) &&
      prefix.length > bestLen
    ) {
      bestMatch = prefix;
      bestLen = prefix.length;
    }
  }
  return bestMatch !== undefined ? moduleLevels[bestMatch] : undefined;
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
  // Apply per-module level overrides (longest-prefix match).
  if (name) {
    const cfg = getConfig();
    const moduleLevels = cfg.logModuleLevels;
    if (Object.keys(moduleLevels).length > 0) {
      const level = findModuleLevel(name, moduleLevels);
      if (level) {
        pinoLogger.level = level.toLowerCase();
      }
    }
  }
  return adaptPino(pinoLogger);
}

/** Reset the root logger (forces re-creation with current config on next call). */
// Stryker disable next-line BlockStatement
export function _resetRootLogger(): void {
  _root = null;
  _rootConfigVersion = -1;
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
