// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * The canonical severity ladder and the single place a level string becomes a
 * level.
 *
 * Before this module TypeScript had no converter at all: the raw
 * PROVIDE_LOG_LEVEL value was lowercased and handed straight to pino, whose
 * vocabulary is trace|debug|info|warn|error|fatal. WARNING and CRITICAL —
 * both listed as applicable to TypeScript in spec/telemetry-api.yaml — threw
 * "default level:warning must be included in custom levels" at logger
 * construction. Per-module levels had the same fault.
 *
 * See the log_levels section of spec/behavioral_fixtures.yaml for the
 * cross-language contract.
 */

/**
 * Severity, ordered. The numeric value is the rank, so severities compare
 * directly with `<` and `>`.
 *
 * WARNING and FATAL are deliberately absent: they are spellings resolved by
 * {@link tryParseLevel}, not members. Admitting an alias as a member is how
 * Warn and Warning both ended up on the public C# Logger surface.
 */
export enum LogSeverity {
  Trace = 0,
  Debug = 1,
  Info = 2,
  Warn = 3,
  Error = 4,
  Critical = 5,
}

/** Canonical spellings first, then the two aliases. */
const TABLE: Readonly<Record<string, LogSeverity>> = {
  TRACE: LogSeverity.Trace,
  DEBUG: LogSeverity.Debug,
  INFO: LogSeverity.Info,
  WARN: LogSeverity.Warn,
  ERROR: LogSeverity.Error,
  CRITICAL: LogSeverity.Critical,
  WARNING: LogSeverity.Warn,
  FATAL: LogSeverity.Critical,
};

/** Canonical uppercase spelling, indexed by rank. */
const CANONICAL_NAMES: readonly string[] = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'];

/** pino's own vocabulary, indexed by rank. CRITICAL lands on pino's fatal. */
const PINO_NAMES: readonly string[] = ['trace', 'debug', 'info', 'warn', 'error', 'fatal'];

/** The canonical uppercase spelling, as it appears on the record. */
export function severityName(severity: LogSeverity): string {
  return CANONICAL_NAMES[severity] as string;
}

/** The pino level name for a severity. */
export function pinoLevelName(severity: LogSeverity): string {
  return PINO_NAMES[severity] as string;
}

/**
 * Resolve a level string, or null when it is not recognised.
 * Trims surrounding whitespace; comparison is case-insensitive.
 */
export function tryParseLevel(text: string | null | undefined): LogSeverity | null {
  if (text === null || text === undefined) return null;
  const found = TABLE[text.trim().toUpperCase()];
  return found === undefined ? null : found;
}

/**
 * Resolve a level string, substituting `fallback` when it is not recognised.
 * The fallback is a parameter rather than a hidden constant so the
 * substitution is visible at the call site.
 */
export function parseLevel(
  text: string | null | undefined,
  fallback: LogSeverity = LogSeverity.Info,
): LogSeverity {
  const parsed = tryParseLevel(text);
  return parsed === null ? fallback : parsed;
}

/** Numeric rank, for threshold comparisons. */
export function levelOrder(text: string | null | undefined): number {
  return parseLevel(text);
}

/**
 * Normalise any accepted spelling to the pino level name it configures.
 * This is the boundary that stops a canonical spelling reaching pino.
 */
export function toPinoLevel(text: string | null | undefined): string {
  return pinoLevelName(parseLevel(text));
}

/** pino's numeric ladder mapped onto the canonical one. */
const PINO_TO_SEVERITY: Readonly<Record<number, LogSeverity>> = {
  10: LogSeverity.Trace,
  20: LogSeverity.Debug,
  30: LogSeverity.Info,
  40: LogSeverity.Warn,
  50: LogSeverity.Error,
  60: LogSeverity.Critical,
};

/**
 * Resolve a pino numeric level to a severity.
 *
 * pino's numbers are the internal representation; the canonical name is what
 * reaches the record. A number outside pino's ladder resolves to INFO, the
 * same fallback the string parser uses.
 */
export function severityFromPino(level: number): LogSeverity {
  return PINO_TO_SEVERITY[level] ?? LogSeverity.Info;
}
