// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Transcribes the log_levels section of spec/behavioral_fixtures.yaml.
// The canonical ladder, the alias table and the unrecognised-token fallback are
// cross-language contracts, not TypeScript choices.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  LogSeverity,
  severityName,
  parseLevel,
  tryParseLevel,
  levelOrder,
  pinoLevelName,
  severityFromPino,
} from '../src/levels.js';

describe('parity: log_levels', () => {
  it.each([
    [LogSeverity.Trace, 0, 'TRACE'],
    [LogSeverity.Debug, 1, 'DEBUG'],
    [LogSeverity.Info, 2, 'INFO'],
    [LogSeverity.Warn, 3, 'WARN'],
    [LogSeverity.Error, 4, 'ERROR'],
    [LogSeverity.Critical, 5, 'CRITICAL'],
  ])('%s has order %s and name %s', (severity, order, name) => {
    expect(severity as number).toBe(order);
    expect(severityName(severity as LogSeverity)).toBe(name);
  });
});

describe('log_levels — parse vectors', () => {
  it.each([
    ['ERROR', LogSeverity.Error, true],
    ['error', LogSeverity.Error, true],
    ['CrItIcAl', LogSeverity.Critical, true],
    ['  warn  ', LogSeverity.Warn, true],
    ['warning', LogSeverity.Warn, true],
    ['WARNING', LogSeverity.Warn, true],
    ['FATAL', LogSeverity.Critical, true],
    ['CRITICAL', LogSeverity.Critical, true],
    ['TRACE', LogSeverity.Trace, true],
    ['DEBUG', LogSeverity.Debug, true],
    ['INFO', LogSeverity.Info, true],
    ['warnn', LogSeverity.Info, false],
    ['warns', LogSeverity.Info, false],
    ['', LogSeverity.Info, false],
    ['   ', LogSeverity.Info, false],
    [null, LogSeverity.Info, false],
    [undefined, LogSeverity.Info, false],
  ])('parses %s', (input, expected, recognised) => {
    expect(tryParseLevel(input as string | null | undefined)).toBe(recognised ? expected : null);
    expect(parseLevel(input as string | null | undefined)).toBe(expected);
    expect(levelOrder(input as string | null | undefined)).toBe(expected as number);
  });

  it('uses the caller fallback only for unrecognised input', () => {
    expect(parseLevel('warnn', LogSeverity.Error)).toBe(LogSeverity.Error);
    expect(parseLevel('debug', LogSeverity.Error)).toBe(LogSeverity.Debug);
  });
});

describe('log_levels — ordering', () => {
  it('CRITICAL outranks ERROR', () => {
    expect(parseLevel('CRITICAL')).toBeGreaterThan(parseLevel('ERROR'));
  });
  it('WARNING equals WARN', () => {
    expect(parseLevel('WARNING')).toBe(parseLevel('WARN'));
  });
  it('FATAL equals CRITICAL', () => {
    expect(parseLevel('FATAL')).toBe(parseLevel('CRITICAL'));
  });
  it('TRACE is the floor', () => {
    expect(parseLevel('TRACE')).toBeLessThan(parseLevel('DEBUG'));
  });
});

describe('log_levels — pino vocabulary', () => {
  // pino's ladder tops out at fatal, which is where CRITICAL lands. Without
  // this mapping the raw canonical spelling reaches pino and it throws
  // "default level:warning must be included in custom levels".
  it.each([
    [LogSeverity.Trace, 'trace'],
    [LogSeverity.Debug, 'debug'],
    [LogSeverity.Info, 'info'],
    [LogSeverity.Warn, 'warn'],
    [LogSeverity.Error, 'error'],
    [LogSeverity.Critical, 'fatal'],
  ])('%s maps to pino %s', (severity, name) => {
    expect(pinoLevelName(severity as LogSeverity)).toBe(name);
  });
});

describe('log_levels — spec values TypeScript previously rejected', () => {
  const KEYS = ['PROVIDE_LOG_LEVEL', 'PROVIDE_LOG_MODULE_LEVELS'];
  const saved: Record<string, string | undefined> = {};
  beforeEach(() => {
    for (const k of KEYS) saved[k] = process.env[k];
  });
  afterEach(() => {
    for (const k of KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });

  // spec/telemetry-api.yaml lists WARNING and CRITICAL as applicable to
  // TypeScript. Both threw inside pino at logger construction, because the raw
  // environment string was lowercased and handed straight over.
  it.each(['WARNING', 'CRITICAL', 'FATAL', 'WARN', 'warning'])(
    'PROVIDE_LOG_LEVEL=%s constructs a logger',
    async (level) => {
      process.env['PROVIDE_LOG_LEVEL'] = level;
      const m = await import('../src/logger.js');
      m._resetRootLogger();
      expect(() => m.getLogger('probe').error({}, 'constructed')).not.toThrow();
    },
  );

  it('PROVIDE_LOG_MODULE_LEVELS with a canonical spelling constructs a logger', async () => {
    process.env['PROVIDE_LOG_MODULE_LEVELS'] = 'probe=WARNING';
    const m = await import('../src/logger.js');
    m._resetRootLogger();
    expect(() => m.getLogger('probe').error({}, 'constructed')).not.toThrow();
  });
});

describe('log_levels — Logger.log', () => {
  beforeEach(async () => {
    const cfg = await import('../src/config.js');
    const lg = await import('../src/logger.js');
    cfg._resetConfig();
    lg._resetRootLogger();
    cfg.setupTelemetry({ serviceName: 'test-svc', logLevel: 'trace', captureToWindow: true });
    (window as unknown as Record<string, unknown>)['__pinoLogs'] = [];
  });

  function records(): Record<string, unknown>[] {
    return (window as unknown as Record<string, unknown[]>)['__pinoLogs'] as Record<
      string,
      unknown
    >[];
  }

  // The record carries the canonical name, identical to the other four ports.
  // pino's number is an internal detail that no longer reaches a consumer.
  it.each([
    [LogSeverity.Trace, 'TRACE'],
    [LogSeverity.Debug, 'DEBUG'],
    [LogSeverity.Info, 'INFO'],
    [LogSeverity.Warn, 'WARN'],
    [LogSeverity.Error, 'ERROR'],
    [LogSeverity.Critical, 'CRITICAL'],
  ])('log(%s) publishes level %s', async (severity, pinoLevel) => {
    const { getLogger } = await import('../src/logger.js');
    getLogger('probe').log(severity as LogSeverity, { event: 'lvl.probe' }, 'lvl.probe');
    expect(records().map((r) => r['level'])).toEqual([pinoLevel]);
  });

  it('omitting the message falls back to the empty string, like every sibling', async () => {
    const { getLogger } = await import('../src/logger.js');
    getLogger('probe').log(LogSeverity.Warn, { event: 'lvl.probe' });
    const rec = records()[0] as Record<string, unknown>;
    expect(rec['level']).toBe('WARN');
    // The write hook backfills an empty message from the event key.
    expect(rec['message']).toBe('lvl.probe');
  });

  it('the module-level logger exposes the same door', async () => {
    const { logger } = await import('../src/logger.js');
    logger.log(LogSeverity.Error, { event: 'lvl.probe' }, 'lvl.probe');
    expect(records().map((r) => r['level'])).toEqual(['ERROR']);
  });

  it('a child logger keeps the door and its bindings', async () => {
    const { getLogger } = await import('../src/logger.js');
    getLogger('probe')
      .child({ request_id: 'abc' })
      .log(LogSeverity.Warn, { event: 'lvl.probe' }, 'lvl.probe');
    const rec = records()[0] as Record<string, unknown>;
    expect(rec['level']).toBe('WARN');
    expect(rec['request_id']).toBe('abc');
  });

  it('collapses the downstream adapter dispatch chain', async () => {
    // The motivating case: a component reports (level, message) so it need not
    // depend on a logger, and every adapter re-implemented an if/else chain
    // whose arms only ran when that severity actually occurred.
    const { getLogger } = await import('../src/logger.js');
    const log = getLogger('adapter');
    const onLog = (level: string, message: string) =>
      log.log(parseLevel(level), { event: message }, message);

    onLog('debug', 'a');
    onLog('warn', 'b');
    onLog('warning', 'c');
    onLog('error', 'd');
    onLog('fatal', 'e');
    onLog('nonsense', 'f');

    // warning/warn coincide, fatal reaches pino's fatal, and an unrecognised
    // level takes the chain's old else-branch: info.
    expect(records().map((r) => r['level'])).toEqual([
      'DEBUG',
      'WARN',
      'WARN',
      'ERROR',
      'CRITICAL',
      'INFO',
    ]);
  });
});

describe('log_levels — pino numeric bridge', () => {
  it.each([
    [10, LogSeverity.Trace],
    [20, LogSeverity.Debug],
    [30, LogSeverity.Info],
    [40, LogSeverity.Warn],
    [50, LogSeverity.Error],
    [60, LogSeverity.Critical],
  ])('pino %s resolves to %s', (pinoLevel, expected) => {
    expect(severityFromPino(pinoLevel as number)).toBe(expected);
  });

  it('a number outside pino ladder resolves to INFO, like an unknown string', () => {
    expect(severityFromPino(99)).toBe(LogSeverity.Info);
    expect(severityFromPino(0)).toBe(LogSeverity.Info);
  });
});
