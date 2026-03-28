// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Attribute cardinality guardrails with TTL pruning.
 * Mirrors Python provide.telemetry.cardinality.
 */

export interface CardinalityLimit {
  maxValues: number;
  ttlSeconds: number;
}

export const OVERFLOW_VALUE = '__overflow__';

const _limits = new Map<string, CardinalityLimit>();
/** key → (value → expiresAt timestamp ms) */
const _seen = new Map<string, Map<string, number>>();
const _lastPrune = new Map<string, number>();
const PRUNE_INTERVAL_MS = 5000;

export function registerCardinalityLimit(key: string, limit: CardinalityLimit): void {
  _limits.set(key, {
    maxValues: Math.max(1, limit.maxValues),
    ttlSeconds: Math.max(1, limit.ttlSeconds),
  });
  // Stryker disable next-line ConditionalExpression: equivalent mutant — guardAttributes line 64 has a ?? fallback that compensates if _seen entry is absent
  if (!_seen.has(key)) _seen.set(key, new Map());
}

export function getCardinalityLimits(): Map<string, CardinalityLimit> {
  return new Map(_limits);
}

export function clearCardinalityLimits(): void {
  _limits.clear();
  _seen.clear();
  _lastPrune.clear();
}

function _pruneExpired(key: string, now: number): void {
  const limit = _limits.get(key);
  const seen = _seen.get(key);
  /* v8 ignore next 2 */
  if (!limit || !seen) return;
  const threshold = now - limit.ttlSeconds * 1000;
  for (const [value, seenAt] of seen) {
    if (seenAt < threshold) seen.delete(value);
  }
}

export function guardAttributes(attrs: Record<string, string>): Record<string, string> {
  const now = Date.now();
  const result = { ...attrs };
  for (const [key, value] of Object.entries(result)) {
    const limit = _limits.get(key);
    if (!limit) continue;
    const lastPrune = _lastPrune.get(key) ?? 0;
    // Stryker disable next-line ConditionalExpression,ArithmeticOperator: early prune is a no-op (only deletes expired values); now+lastPrune equivalent because fresh values are always within TTL
    if (now - lastPrune >= PRUNE_INTERVAL_MS) {
      _pruneExpired(key, now);
      _lastPrune.set(key, now);
    }
    /* v8 ignore next */
    const seen = _seen.get(key) ?? new Map<string, number>();
    if (seen.has(value)) {
      seen.set(value, now);
      continue;
    }
    if (seen.size >= limit.maxValues) {
      result[key] = OVERFLOW_VALUE;
      continue;
    }
    seen.set(value, now);
    _seen.set(key, seen);
  }
  return result;
}

export function _resetCardinalityForTests(): void {
  clearCardinalityLimits();
}
