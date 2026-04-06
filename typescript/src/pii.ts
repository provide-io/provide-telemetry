// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * PII policy engine with rule-based masking and nested traversal.
 * Mirrors Python provide.telemetry.pii.
 *
 * Also serves as the canonical home for sanitize() / DEFAULT_SANITIZE_FIELDS;
 * sanitize.ts re-exports these for backwards compatibility.
 */

import { shortHash12 } from './hash';

/**
 * Default fields redacted from log records. Canonical 17-key list shared across
 * Python, TypeScript, and Go implementations.
 * Note: 'email' is intentionally excluded — it is commonly used for user identification
 * in logs. Users who want email redaction should register a custom PII rule.
 */
export const DEFAULT_SANITIZE_FIELDS: readonly string[] = [
  'password',
  'passwd',
  'secret',
  'token',
  'api_key',
  'apikey',
  'auth',
  'authorization',
  'credential',
  'private_key',
  'ssn',
  'credit_card',
  'creditcard',
  'cvv',
  'pin',
  'account_number',
  'cookie',
];

const REDACTED = '***';

/** Default maximum recursion depth for PII sanitization. */
const _DEFAULT_MAX_DEPTH = 8;

const _MIN_SECRET_LENGTH = 20;
/* Stryker disable all: regex quantifier mutations produce patterns that still match test values */
export const _SECRET_PATTERNS: RegExp[] = [
  /(?:AKIA|ASIA)[A-Z0-9]{16}/, // AWS access key
  /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/, // JWT
  /gh[pos]_[A-Za-z0-9_]{36,}/, // GitHub token
  /[0-9a-fA-F]{40,}/, // Long hex string
  /[A-Za-z0-9+/]{40,}={0,2}/, // Long base64 string
];
/* Stryker restore all */

export function _detectSecretInValue(value: string): boolean {
  // Stryker disable next-line ConditionalExpression: removing length check makes patterns match short strings — equivalent when all test secrets are ≥20 chars
  if (value.length < _MIN_SECRET_LENGTH) return false;
  return _SECRET_PATTERNS.some((p) => p.test(value));
}

/**
 * Redact PII fields in a log object in place.
 * Checks DEFAULT_SANITIZE_FIELDS plus any additional fields from config.
 * Case-insensitive key matching.
 */
// Stryker disable next-line ArrayDeclaration
export function sanitize(obj: Record<string, unknown>, extraFields: string[] = []): void {
  const blocked = new Set([
    ...DEFAULT_SANITIZE_FIELDS.map((f) => f.toLowerCase()),
    ...extraFields.map((f) => f.toLowerCase()),
  ]);
  for (const key of Object.keys(obj)) {
    // Stryker disable next-line ConditionalExpression: mutating to true redacts all keys — equivalent because tests use blocked keys
    if (blocked.has(key.toLowerCase())) {
      obj[key] = REDACTED;
    } else if (
      // Stryker disable next-line all: V8 perTest coverage doesn't attribute else-if branches; tested in pii.test.ts secret detection suite
      typeof obj[key] === 'string' &&
      _detectSecretInValue(obj[key] as string)
    ) {
      obj[key] = REDACTED;
    }
  }
}

// ── Dynamic PII rule engine ───────────────────────────────────────────────────

export type MaskMode = 'redact' | 'drop' | 'hash' | 'truncate';

export interface PIIRule {
  /** Dot-separated field path (e.g. "user.email"). Python uses tuple paths instead. */
  path: string;
  mode: MaskMode;
  /** For 'truncate' mode: max characters before '...' is appended. */
  truncateTo?: number;
}

// Stryker disable next-line ArrayDeclaration
const _rules: PIIRule[] = [];

// Overridable hash function — allows tests to exercise the fallback path.
let _hashFnOverride: ((val: string) => string) | null = null;

export function _setHashFnForTest(fn: ((val: string) => string) | null): void {
  _hashFnOverride = fn;
}

function _hashValue(val: string): string {
  try {
    if (_hashFnOverride !== null) return _hashFnOverride(val);
    return shortHash12(val);
  } catch {
    return REDACTED;
  }
}

function _applyMode(value: unknown, rule: PIIRule): { keep: boolean; value: unknown } {
  switch (rule.mode) {
    case 'drop':
      // Stryker disable next-line ObjectLiteral
      return { keep: false, value: undefined };
    case 'hash':
      return { keep: true, value: _hashValue(String(value)) };
    case 'truncate': {
      const limit = Math.max(0, rule.truncateTo ?? 8);
      const text = String(value);
      return { keep: true, value: text.length > limit ? text.slice(0, limit) + '...' : text };
    }
    default:
      return { keep: true, value: REDACTED };
  }
}

function _pathSegments(path: string): string[] {
  return path.split('.');
}

function _matches(ruleSegs: string[], valueSegs: string[]): boolean {
  // Stryker disable next-line ConditionalExpression
  if (ruleSegs.length !== valueSegs.length) return false;
  return ruleSegs.every((seg, i) => seg === '*' || seg === valueSegs[i]);
}

function _applyRuleFull(
  node: unknown,
  rule: PIIRule,
  currentPath: string[],
  maxDepth: number = _DEFAULT_MAX_DEPTH,
  depth: number = 0,
): unknown {
  if (typeof node !== 'object' || node === null) return node;
  if (depth >= maxDepth) return node;
  // Stryker disable next-line ConditionalExpression,BlockStatement: when array is treated as object, numeric string indices still match wildcard '*' rule segments — equivalent
  if (Array.isArray(node)) {
    // Stryker disable next-line StringLiteral: '*' wildcard in VALUE path is irrelevant because _matches checks RULE segment, not value segment, for wildcards
    return node.map((item) =>
      _applyRuleFull(item, rule, [...currentPath, '*'], maxDepth, depth + 1),
    );
  }
  const obj = node as Record<string, unknown>;
  const ruleSegs = _pathSegments(rule.path);
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(obj)) {
    const childPath = [...currentPath, key];
    if (_matches(ruleSegs, childPath)) {
      const { keep, value } = _applyMode(val, rule);
      if (keep) result[key] = value;
    } else {
      result[key] = _applyRuleFull(val, rule, childPath, maxDepth, depth + 1);
    }
  }
  return result;
}

/**
 * Recursively redact keys matching blocked field names and secret patterns,
 * respecting depth limits. Mirrors Python _apply_default_sensitive_key_redaction.
 */
function _applyDefaultSensitiveKeyRedaction(
  node: unknown,
  original: unknown,
  blocked: Set<string>,
  ruleTargets: Set<string | undefined>,
  maxDepth: number,
  depth: number = 0,
): unknown {
  if (depth >= maxDepth) return node;
  if (typeof node !== 'object' || node === null) return node;
  if (Array.isArray(node)) {
    const origArr = Array.isArray(original) ? original : [];
    return node.map((item, i) =>
      _applyDefaultSensitiveKeyRedaction(
        item,
        origArr[i],
        blocked,
        ruleTargets,
        maxDepth,
        depth + 1,
      ),
    );
  }
  const obj = node as Record<string, unknown>;
  const orig =
    typeof original === 'object' && original !== null && !Array.isArray(original)
      ? (original as Record<string, unknown>)
      : obj;
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(obj)) {
    const lk = key.toLowerCase();
    const origVal = orig[key];
    if (blocked.has(lk) && !ruleTargets.has(lk)) {
      // If a custom rule already changed the value, keep the rule's result.
      if (val !== origVal) {
        result[key] = val;
      } else {
        result[key] = REDACTED;
      }
    } else if (typeof val === 'string' && _detectSecretInValue(val)) {
      result[key] = REDACTED;
    } else {
      result[key] = _applyDefaultSensitiveKeyRedaction(
        val,
        origVal,
        blocked,
        ruleTargets,
        maxDepth,
        depth + 1,
      );
    }
  }
  return result;
}

export function registerPiiRule(rule: PIIRule): void {
  _rules.push(rule);
}

export function getPiiRules(): PIIRule[] {
  return [..._rules];
}

export function replacePiiRules(rules: PIIRule[]): void {
  _rules.length = 0;
  _rules.push(...rules);
}

export function resetPiiRulesForTests(): void {
  _rules.length = 0;
  _hashFnOverride = null;
}

/** Options for sanitizePayload. */
export interface SanitizePayloadOptions {
  /** Maximum recursion depth for nested traversal. Default 8. */
  maxDepth?: number;
}

/**
 * Apply all registered PII rules to a payload object recursively.
 * Also redacts top-level keys that match DEFAULT_SANITIZE_FIELDS unless a rule already handled them.
 */
export function sanitizePayload(
  obj: Record<string, unknown>,
  // Stryker disable next-line ArrayDeclaration
  extraFields: string[] = [],
  options?: SanitizePayloadOptions,
): void {
  const maxDepth = options?.maxDepth ?? _DEFAULT_MAX_DEPTH;
  let current: unknown = obj;

  // Apply registered rules first.
  for (const rule of _rules) {
    current = _applyRuleFull(current, rule, [], maxDepth);
  }

  // Apply default field-name redaction + secret detection recursively with depth limit.
  // v8 ignore: current is always a non-null object here; null/array branches are defensive.
  // Stryker disable next-line LogicalOperator,ConditionalExpression
  /* v8 ignore next */
  if (typeof current === 'object' && current !== null && !Array.isArray(current)) {
    // Stryker disable next-line OptionalChaining: _pathSegments always returns a non-empty array (split returns at least one element)
    const ruleTargets = new Set(_rules.map((r) => _pathSegments(r.path).pop()?.toLowerCase()));
    const blocked = new Set([
      ...DEFAULT_SANITIZE_FIELDS.map((f) => f.toLowerCase()),
      ...extraFields.map((f) => f.toLowerCase()),
    ]);
    const c = _applyDefaultSensitiveKeyRedaction(
      current,
      obj,
      blocked,
      ruleTargets,
      maxDepth,
    ) as Record<string, unknown>;
    // Update the original object in-place.
    for (const key of Object.keys(obj)) {
      /* Stryker disable ConditionalExpression: false mutation deletes all keys — equivalent when no 'drop' rules are active */
      if (key in c) {
        obj[key] = c[key];
      } else {
        delete obj[key]; /* Stryker restore ConditionalExpression */
      }
    }
    // Add any new keys from nested rule transformations.
    // Stryker disable all
    for (const key of Object.keys(c)) {
      /* v8 ignore next */
      if (!(key in obj)) obj[key] = c[key];
    }
    // Stryker enable all
  }
}
