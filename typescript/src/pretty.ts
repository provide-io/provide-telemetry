// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Pretty ANSI log renderer for CLI / terminal output.
 *
 * Mirrors Python provide.telemetry.logger.pretty.PrettyRenderer.
 * Same color scheme, same layout: timestamp [level] event key=value pairs.
 */

const RESET = '\x1b[0m';
const DIM = '\x1b[2m';
const BOLD = '\x1b[1m';

const LEVEL_COLORS: Record<string, string> = {
  fatal: '\x1b[31;1m', // bold red
  error: '\x1b[31m', // red
  warn: '\x1b[33m', // yellow
  info: '\x1b[32m', // green
  debug: '\x1b[34m', // blue
  trace: '\x1b[36m', // cyan
};

const NAMED_COLORS: Record<string, string> = {
  dim: DIM,
  bold: BOLD,
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
  white: '\x1b[37m',
  none: '',
  '': '',
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
const SKIP_KEYS = new Set(['level', 'time', 'message', 'msg', 'event', 'v', 'pid', 'hostname']);

export interface PrettyFormatOptions {
  keyColor?: string;
  valueColor?: string;
  fields?: string[];
}

function resolveNamedColor(name: string | undefined, fallback: string): string {
  const normalized = (name ?? fallback).trim().toLowerCase();
  return NAMED_COLORS[normalized] ?? '';
}

function wrap(value: string, color: string, colors: boolean): string {
  return colors && color ? color + value + RESET : value;
}

/**
 * Detect whether stderr supports color.
 * Returns false in browsers, CI without FORCE_COLOR, or piped output.
 */
export function supportsColor(): boolean {
  // Stryker disable next-line ConditionalExpression,StringLiteral,BooleanLiteral -- browser-only guard
  /* v8 ignore next -- browser-only path, untestable in Node */
  if (typeof process === 'undefined') return false;
  if (process.env['FORCE_COLOR'] === '1' || process.env['FORCE_COLOR'] === 'true') return true;
  if (process.env['NO_COLOR'] !== undefined) return false;
  // Stryker disable next-line OptionalChaining -- process.stderr is always defined in Node/test env
  if (typeof process.stderr?.isTTY === 'boolean') return process.stderr.isTTY;
  return false;
}

/**
 * Format a pino log object as a pretty ANSI string.
 *
 * Layout: `timestamp [level   ] event  key=value key=value`
 */
export function formatPretty(
  obj: Record<string, unknown>,
  colors: boolean,
  options: PrettyFormatOptions = {},
): string {
  const parts: string[] = [];
  const keyColor = resolveNamedColor(options.keyColor, 'dim');
  const valueColor = resolveNamedColor(options.valueColor, '');
  const fields = new Set(options.fields ?? []);

  // 1. Timestamp
  const time = obj['time'];
  if (time !== undefined) {
    const ts = typeof time === 'number' ? new Date(time).toISOString() : String(time);
    parts.push(wrap(ts, DIM, colors));
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
  const event = obj['event'] ?? obj['message'] ?? obj['msg'] ?? '';
  parts.push(String(event));

  // 4. Remaining key=value pairs (sorted, skip internal keys)
  const keys = Object.keys(obj)
    .filter((k) => !SKIP_KEYS.has(k))
    .filter((k) => fields.size === 0 || fields.has(k))
    .sort();
  for (const k of keys) {
    const v = JSON.stringify(obj[k]) ?? String(obj[k]);
    parts.push(wrap(k, keyColor, colors) + '=' + wrap(v, valueColor, colors));
  }

  return parts.join(' ');
}
