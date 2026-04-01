// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Pretty ANSI log renderer for CLI / terminal output.
 *
 * Mirrors Python undef.telemetry.logger.pretty.PrettyRenderer.
 * Same color scheme, same layout: timestamp [level] event key=value pairs.
 */

const RESET = '\x1b[0m';
const DIM = '\x1b[2m';

const LEVEL_COLORS: Record<string, string> = {
  fatal: '\x1b[31;1m', // bold red
  error: '\x1b[31m', // red
  warn: '\x1b[33m', // yellow
  info: '\x1b[32m', // green
  debug: '\x1b[34m', // blue
  trace: '\x1b[36m', // cyan
};

// pino level number → name
const LEVEL_NAMES: Record<number, string> = {
  10: 'trace',
  20: 'debug',
  30: 'info',
  40: 'warn',
  50: 'error',
  60: 'fatal',
};

const LEVEL_PAD = 6; // "fatal" = 5, pad to 6

// Keys to exclude from the key=value tail (already rendered or internal)
const SKIP_KEYS = new Set(['level', 'time', 'msg', 'event', 'v', 'pid', 'hostname']);

/**
 * Detect whether stdout supports color.
 * Returns false in browsers, CI without FORCE_COLOR, or piped output.
 */
export function supportsColor(): boolean {
  /* c8 ignore next -- browser-only path, untestable in Node */
  // Stryker disable next-line ConditionalExpression,StringLiteral,BooleanLiteral -- browser-only guard
  if (typeof process === 'undefined') return false;
  if (process.env['FORCE_COLOR'] === '1' || process.env['FORCE_COLOR'] === 'true') return true;
  if (process.env['NO_COLOR'] !== undefined) return false;
  // Stryker disable next-line OptionalChaining -- process.stdout is always defined in Node/test env
  if (typeof process.stdout?.isTTY === 'boolean') return process.stdout.isTTY;
  return false;
}

/**
 * Format a pino log object as a pretty ANSI string.
 *
 * Layout: `timestamp [level   ] event  key=value key=value`
 */
export function formatPretty(obj: Record<string, unknown>, colors: boolean): string {
  const parts: string[] = [];

  // 1. Timestamp
  const time = obj['time'];
  if (time !== undefined) {
    const ts = typeof time === 'number' ? new Date(time).toISOString() : String(time);
    parts.push(colors ? DIM + ts + RESET : ts);
  }

  // 2. Level
  const levelNum = obj['level'] as number;
  const levelName = LEVEL_NAMES[levelNum] ?? 'log';
  const padded = levelName.padEnd(LEVEL_PAD);
  if (colors) {
    const c = LEVEL_COLORS[levelName] ?? '';
    parts.push('[' + c + padded + RESET + ']');
  } else {
    parts.push('[' + padded + ']');
  }

  // 3. Event / message
  const event = obj['event'] ?? obj['msg'] ?? '';
  parts.push(String(event));

  // 4. Remaining key=value pairs (sorted, skip internal keys)
  const keys = Object.keys(obj)
    .filter((k) => !SKIP_KEYS.has(k))
    .sort();
  for (const k of keys) {
    const v = JSON.stringify(obj[k]);
    parts.push(colors ? DIM + k + RESET + '=' + v : k + '=' + v);
  }

  return parts.join(' ');
}
