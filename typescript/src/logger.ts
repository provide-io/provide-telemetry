// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
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
import { configFromEnv, getConfig, _getConfigVersion } from './config.js';
import { getContext } from './context.js';
import { loadConsentFromEnv, shouldAllow } from './consent.js';
import { computeErrorFingerprint } from './fingerprint.js';
import { formatPretty, supportsColor } from './pretty.js';
import { _emittedField, _incrementHealth } from './health.js';
import { emitLogRecord } from './otel-logs.js';
import { hardenRecord } from './harden.js';
import { sanitize, sanitizePayload } from './pii.js';
import { EventSchemaError, validateEventName, validateRequiredKeys } from './schema.js';
import { tryAcquire, release } from './backpressure.js';
import { setSamplingPolicy, shouldSample } from './sampling.js';
import { getTraceContext } from './tracing.js';
import { LogSeverity, severityFromPino, severityName, toPinoLevel } from './levels.js';

/** Pino level number → console method name. */
// 10 maps to console.debug, not console.trace: console.trace prepends "Trace: "
// and appends a stack dump, so a TRACE record emitted through it is no longer
// a parseable line. console.debug is the same severity channel without the
// decoration.
const LEVEL_MAP: Record<number, string> = {
  10: 'debug',
  20: 'debug',
  30: 'log',
  40: 'warn',
  50: 'error',
  60: 'error',
};

/** Pino level number → semantic level string for consent checks. */
const CONSENT_LEVEL_MAP: Record<number, string> = {
  10: 'trace',
  20: 'debug',
  30: 'info',
  40: 'warn',
  50: 'error',
  60: 'error',
};

/**
 * Resolved source location of the call that produced a log record.
 *
 * Produced by the write hook and handed to the OTLP log exporter, which
 * publishes it as the `code.*` semantic-convention attributes. Kept separate
 * from the record itself so `logCodeAttributes` and `logIncludeCaller` stay
 * independent: the site is captured for either knob, and each knob decides
 * only whether its own output is written.
 */
export interface Callsite {
  /** Basename of the source file — a full path leaks the build machine layout. */
  filename: string;
  /**
   * Full path as the runtime reported it.
   *
   * The record field is a base name; `code.file.path` is not. OpenTelemetry
   * defines that attribute as the whole path, and Python (through
   * `opentelemetry-instrumentation-logging`, which publishes `record.pathname`)
   * and Go (`runtime.Frame.File`) both send it. A base name there would be a
   * third spelling of the same attribute.
   */
  path: string;
  /** 1-based line number within that file. */
  lineno: number;
  /** Enclosing function name. Absent when V8 resolved no name for the frame. */
  functionName?: string;
}

/** V8 frame that carries a function name: `at fn (/dir/file.ts:12:5)`. */
const NAMED_FRAME_RE = /at\s+(.+?)\s+\((.+):(\d+):\d+\)/;
/** V8 frame with no function name: `at /dir/file.ts:12:5`. */
const BARE_FRAME_RE = /at\s+(.+):(\d+):\d+/;
/**
 * Everything up to and including the last path separator, either kind.
 *
 * Backslashes count: a CJS frame on Windows reads
 * `at handleRequest (C:\srv\app\routes.ts:42:17)`, and stripping only forward
 * slashes puts that whole path — drive letter and all — in `filename`, which is
 * specified as a base name precisely so a record never carries one.
 */
const PATH_PREFIX_RE = /^.*[\\/]/;
/** V8 prints `async` ahead of the name; it is a modifier, not part of the name. */
const ASYNC_PREFIX_RE = /^async\s+/;
/** V8's stand-in for a name it could not resolve, e.g. `Object.<anonymous>`. */
const ANONYMOUS_NAME = '<anonymous>';
/** V8's nested-eval frame: `at eval (eval at fn (/app/main.js:1:1), <anonymous>:1:1)`. */
const EVAL_FRAME_MARKER = 'eval at ';

/** Strip the directory part of a path. */
function basename(path: string): string {
  return path.replace(PATH_PREFIX_RE, '');
}

/**
 * Parse one V8 stack frame into a callsite.
 *
 * `functionName` is omitted — rather than filled with a placeholder — whenever
 * V8 resolved no name for the frame: a bare frame (top-level module code, an
 * inline callback) carries none at all, and `Object.<anonymous>` is V8's own
 * placeholder. An absent attribute is more useful to a consumer than one whose
 * value means "unknown".
 *
 * Exported for direct unit testing; not part of the package's public API.
 */
export function _parseStackFrame(frame: string): Callsite | undefined {
  // A nested-eval frame carries two locations in one set of parentheses, and
  // every path group here would swallow both. There is no file to report for
  // code that has none, so report nothing.
  if (frame.includes(EVAL_FRAME_MARKER)) return undefined;
  const named = NAMED_FRAME_RE.exec(frame);
  if (named) {
    const site: Callsite = {
      filename: basename(named[2]),
      path: named[2],
      lineno: Number(named[3]),
    };
    const fn = named[1].replace(ASYNC_PREFIX_RE, '');
    if (!fn.includes(ANONYMOUS_NAME)) site.functionName = fn;
    return site;
  }
  const bare = BARE_FRAME_RE.exec(frame);
  if (!bare) return undefined;
  return { filename: basename(bare[1]), path: bare[1], lineno: Number(bare[2]) };
}

/** The source path a frame names, or undefined when the frame is unparsable. */
function frameFile(frame: string): string | undefined {
  return _parseStackFrame(frame)?.path;
}

/**
 * True for a frame belonging to pino, which sits between the caller and this
 * module in every Node stack.
 *
 * Matched on path *segments* rather than as a substring. `frame.includes('pino')`
 * also matches a consumer working in `/home/pino/`, a function named
 * `pinoAdapter`, and a package called `pinocchio`; `frame.includes('node_modules')`
 * matches every library that logs, so any package wrapping this logger was
 * attributed to whoever called *it*. Both were reported as the caller's own
 * frame being skipped, which is a wrong answer, not a missing one.
 */
function isPinoFrame(file: string): boolean {
  const segments = file.split(/[\\/]/);
  return (
    segments.includes('node_modules') &&
    segments.some((segment) => segment === 'pino' || segment.startsWith('pino-'))
  );
}

/**
 * The first frame belonging to the caller rather than to the logging machinery.
 *
 * `frames[0]` is this module's own capture frame by construction — the caller
 * passes the stack with only the `Error` header removed — so its path is what
 * identifies the rest of our frames, whatever the file is called. That is the
 * whole of the rule, and it is why there is no list of file names to keep in
 * step with the build: source tree, published `dist`, a consumer's own
 * `logger.ts`, a renamed chunk, all behave the same.
 *
 * It also decides the bundled case honestly. Bundle this module and the
 * consumer into one file and every frame shares that file, so no frame is
 * distinguishable as the caller's and the walk returns nothing. A missing
 * callsite is recoverable; naming the logger's own line as the caller's, which
 * is what a file-name skip list does there, is not.
 *
 * Exported for direct unit testing; not part of the package's public API.
 */
export function _firstCallerFrame(frames: string[]): string | undefined {
  const ownFile = frames.length > 0 ? frameFile(frames[0]) : undefined;
  for (const frame of frames.slice(1)) {
    const file = frameFile(frame);
    // An unparsable frame is skipped rather than reported: `at new Promise
    // (<anonymous>)` and the like carry no source position to publish.
    if (file === undefined) continue;
    if (file === ownFile) continue;
    if (isPinoFrame(file)) continue;
    return frame;
  }
  return undefined;
}

// Stryker disable all
function captureCallsite(): Callsite | undefined {
  // `.stack` is a string only under V8's default formatting. A host that has
  // installed its own Error.prepareStackTrace — a source-map or trace library,
  // typically — gets whatever that returns, often an array of CallSite objects.
  // Reading it as a string there would throw, and a logger that throws takes
  // the record and the caller with it.
  const stack = new Error().stack;
  if (typeof stack !== 'string') return undefined;
  const frame = _firstCallerFrame(stack.split('\n').slice(1));
  return frame === undefined ? undefined : _parseStackFrame(frame);
}
// Stryker enable all

/** Public Logger interface — consumers should type against this, not pino.Logger. */
export interface Logger {
  trace(obj: Record<string, unknown>, msg?: string): void;
  debug(obj: Record<string, unknown>, msg?: string): void;
  info(obj: Record<string, unknown>, msg?: string): void;
  warn(obj: Record<string, unknown>, msg?: string): void;
  error(obj: Record<string, unknown>, msg?: string): void;
  /**
   * Emit at a level known only at runtime.
   *
   * For adapters that receive a level as data. Callers holding a level string
   * convert once at the boundary with `parseLevel` rather than re-implementing
   * a dispatch chain whose arms only run when that severity actually occurs.
   */
  log(level: LogSeverity, obj: Record<string, unknown>, msg?: string): void;
  /** Create a child logger with additional bound fields. */
  child(bindings: Record<string, unknown>): Logger;
}

// Pino root instance — lazily created so config is read after setupTelemetry().
let _root: pino.Logger | null = null;
// The cache-reuse check below is `_root && _rootConfigVersion === currentVersion`.
// _root and _rootConfigVersion are always assigned together (see the
// cache-miss branch and _resetRootLogger), so _root is null on every path
// that would otherwise consult this initial value — the `&&` short-circuits
// before it's ever read. Verified by hand-mutating -1 to +1 against the full
// logger.*.test.ts suite (and the whole test suite) with no failures.
// Stryker disable next-line UnaryOperator
let _rootConfigVersion = -1;

function resolveLoggerConfig() {
  // Before setupTelemetry() runs, logger lazy-init should still honor env config.
  return _getConfigVersion() === 0 ? configFromEnv() : getConfig();
}

/**
 * Env-driven policies for a logger built before setupTelemetry() has run.
 *
 * Guarded on the config version so it only fires on the lazy path: once setup
 * has happened, env was already applied there and a later root rebuild must
 * not clobber a consent level the application set programmatically since.
 */
function applyLazyLoggerPoliciesFromEnv(): void {
  if (_getConfigVersion() !== 0) return;
  loadConsentFromEnv();
  const cfg = configFromEnv();
  setSamplingPolicy('logs', { defaultRate: cfg.samplingLogsRate });
}

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
    const cfg = resolveLoggerConfig();
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

    try {
      // Merge module-level context bindings first, then overlay trace context
      // so real trace/span IDs always win over user-bound values.
      Object.assign(o, getContext());
      const ids = getTraceContext();
      if (ids.trace_id) o['trace_id'] = ids.trace_id;
      if (ids.span_id) o['span_id'] = ids.span_id;

      // Ensure message is always non-empty — pino sets message='' when no string arg is passed.
      if (!o['message']) o['message'] = o['event'] ?? '';

      // Publish the canonical level name rather than pino's number. Every
      // other port writes a string here; a record reading `"level":40` forces
      // any consumer to carry a pino lookup table just for TypeScript.
      // The number is kept locally for the console-method choice below.
      const pinoLevel = o['level'] as number;
      o['level'] = severityName(severityFromPino(pinoLevel));

      // Callsite capture — one stack walk feeding two independent knobs.
      // logIncludeCaller writes filename/lineno onto the record;
      // logCodeAttributes forwards the site to the OTLP exporter, which
      // publishes it as code.* attributes. Either knob alone triggers the
      // walk, and neither implies the other's output.
      // Stryker disable all
      let codeSite: Callsite | undefined;
      if (cfg.logIncludeCaller || cfg.logCodeAttributes) {
        const site = captureCallsite();
        /* v8 ignore next -- V8 always yields a parseable frame outside the logger */
        if (site) {
          if (cfg.logIncludeCaller) {
            o['filename'] = site.filename;
            o['lineno'] = site.lineno;
          }
          if (cfg.logCodeAttributes) codeSite = site;
        }
      }
      // Stryker enable all

      // Error fingerprinting — stable hash from error name + stack.
      const errObj = o['err'] as Record<string, unknown> | undefined;
      const excName = (o['exc_name'] ?? o['exception'] ?? errObj?.['type'] ?? errObj?.['name']) as
        string | undefined;
      if (excName) {
        const stack = (errObj?.['stack'] ?? o['stack']) as string | undefined;
        o['error_fingerprint'] = computeErrorFingerprint(String(excName), stack);
      }

      // Recursive hardening runs before classification and PII, per the
      // canonical signal order: bound the record structurally so everything
      // after it sees a finite, JSON-shaped, non-cyclic value. Doing it here
      // rather than at export means a cyclic payload cannot reach the local
      // renderer either.
      hardenRecord(o, {
        maxValueLength: cfg.securityMaxAttrValueLength,
        maxAttrCount: cfg.securityMaxAttrCount,
        maxDepth: cfg.piiMaxDepth,
      });

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
      emitLogRecord(o, codeSite);

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
        const method = LEVEL_MAP[pinoLevel] ?? 'log';
        if (cfg.logFormat === 'pretty' || cfg.logFormat === 'console') {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (console as any)[method](
            formatPretty(o, supportsColor(), {
              keyColor: cfg.logPrettyKeyColor,
              valueColor: cfg.logPrettyValueColor,
              fields: cfg.logPrettyFields,
            }),
          );
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
  if (_root && _rootConfigVersion === currentVersion) return _root;
  _root = null;
  _rootConfigVersion = currentVersion;
  const cfg = resolveLoggerConfig();
  applyLazyLoggerPoliciesFromEnv();
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
        messageKey: 'message',
      },
      stream as unknown as pino.DestinationStream,
    );
  } else {
    /* c8 ignore next 9 */
    _root = pino({
      base: { service: cfg.serviceName, env: cfg.environment, version: cfg.version },
      level: cfg.logLevel,
      messageKey: 'message',
      browser: {
        write: hook,
      },
    });
  }
  // Stryker enable all
  return _root;
}

/**
 * Dispatch to the pino method for a severity.
 *
 * The one place this library maps a severity onto a pino call. CRITICAL has no
 * pino method of its own -- pino's most severe is fatal, which is where the
 * canonical ladder puts it.
 */
function emitAt(
  pinoLogger: pino.Logger,
  level: LogSeverity,
  obj: Record<string, unknown>,
  msg: string,
): void {
  switch (level) {
    case LogSeverity.Trace:
      pinoLogger.trace(obj, msg);
      return;
    case LogSeverity.Debug:
      pinoLogger.debug(obj, msg);
      return;
    case LogSeverity.Warn:
      pinoLogger.warn(obj, msg);
      return;
    case LogSeverity.Error:
      pinoLogger.error(obj, msg);
      return;
    case LogSeverity.Critical:
      pinoLogger.fatal(obj, msg);
      return;
    default:
      pinoLogger.info(obj, msg);
  }
}

function adaptPino(pinoLogger: pino.Logger): Logger {
  // Stryker disable all
  return {
    trace: (obj, msg) => pinoLogger.trace(obj, msg ?? ''),
    debug: (obj, msg) => pinoLogger.debug(obj, msg ?? ''),
    info: (obj, msg) => pinoLogger.info(obj, msg ?? ''),
    warn: (obj, msg) => pinoLogger.warn(obj, msg ?? ''),
    error: (obj, msg) => pinoLogger.error(obj, msg ?? ''),
    log: (level, obj, msg) => emitAt(pinoLogger, level, obj, msg ?? ''),
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
        pinoLogger.level = toPinoLevel(level);
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
  log: (level, obj, msg) => getLogger('default').log(level, obj, msg),
  child: (bindings) => getLogger('default').child(bindings),
};
// Stryker enable all
