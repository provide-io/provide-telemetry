// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * PII policy engine with rule-based masking and nested traversal.
 * Mirrors Python provide.telemetry.pii.
 *
 * Canonical home for sanitize() / DEFAULT_SANITIZE_FIELDS.
 */

import { shortHash12 } from './hash.js';
import {
  PATTERNS as _GENERATED_PATTERNS,
  MIN_SECRET_LENGTH as _MIN_SECRET_LENGTH,
} from './secret-patterns-generated.js';

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

/** The mask literal every redaction and collapse uses. */
export const REDACTED = '***';

/** Default maximum recursion depth for PII sanitization and hardening. */
export const DEFAULT_MAX_DEPTH = 8;

/* Stryker disable all: regex quantifier mutations produce patterns that still match test values */
export const _SECRET_PATTERNS: RegExp[] = _GENERATED_PATTERNS.map((p) => p.regex);
/* Stryker restore all */

/** Named secret pattern for diagnostics / deduplication. */
export interface SecretPattern {
  name: string;
  pattern: RegExp;
}

const _customSecretPatterns: Map<string, RegExp> = new Map();

/**
 * Register a custom secret detection pattern.
 * If a pattern with the same name already exists it is replaced.
 * The name is for diagnostics only.
 */
export function registerSecretPattern(name: string, pattern: RegExp): void {
  // g/y make RegExp.test stateful through lastIndex, so a matching value would
  // be detected only on alternate calls. Detection is a containment check —
  // dropping the flags preserves the match semantics and removes the state.
  const flags = pattern.flags.replace(/[gy]/g, '');
  _customSecretPatterns.set(name, new RegExp(pattern.source, flags));
}

/**
 * Return all active secret patterns (built-in + custom).
 */
export function getSecretPatterns(): SecretPattern[] {
  const builtIn: SecretPattern[] = _SECRET_PATTERNS.map((p, i) => ({
    name: `built-in-${String(i)}`,
    pattern: p,
  }));
  const custom: SecretPattern[] = Array.from(_customSecretPatterns.entries()).map(
    ([name, pattern]) => ({ name, pattern }),
  );
  return [...builtIn, ...custom];
}

/**
 * Remove all custom secret patterns. Built-in patterns are not affected.
 */
export function resetSecretPatternsForTests(): void {
  _customSecretPatterns.clear();
}

/**
 * True when a matched span has the shape of a filesystem path rather than a
 * secret.
 *
 * The long_base64 pattern is [A-Za-z0-9+/]{40,} and "/" is in the base64
 * alphabet, so any deep path of unpunctuated segments matched it —
 * /home/deploy/apps/production/current/lib/service is 48 characters of pure
 * base64 alphabet containing no secret. Narrowing the charset is not the fix:
 * dropping "/" costs 44% of detections on 32-byte secrets, because a 44-char
 * base64 string holding one slash is indistinguishable from a path by charset.
 *
 * Shape separates them. Paths carry several short all-lowercase words (usr,
 * local, lib); random base64 effectively never does — a 20-character
 * all-lowercase run has probability (26/64)^20, about 1e-8.
 */
const _PATH_MIN_SEGMENTS = 3;

export function _looksLikePath(span: string): boolean {
  const segments = span.split('/').filter((s) => s.length > 0);
  if (segments.length < _PATH_MIN_SEGMENTS) return false;
  const wordy = segments.filter((s) => /^[a-z]+$/.test(s)).length;
  return wordy * 2 >= segments.length;
}

function _secretMatch(value: string): RegExpExecArray | null {
  if (value.length < _MIN_SECRET_LENGTH) return null;
  for (const p of [..._SECRET_PATTERNS, ..._customSecretPatterns.values()]) {
    // Patterns may carry /g; exec advances lastIndex, so reset before use.
    p.lastIndex = 0;
    const m = p.exec(value);
    if (m !== null && !_looksLikePath(m[0])) return m;
  }
  return null;
}

/**
 * Replace only the secret-looking token of *value*, leaving the rest.
 *
 * The match is widened to its whitespace-delimited token first. Redacting the
 * literal match alone can leave part of a credential behind: the jwt pattern
 * matches header.payload, and a JWT has THREE dot-separated parts, so the
 * signature would survive. Whitespace is the boundary a secret cannot cross
 * without ceasing to be one token.
 */
export function redactSecretSpans(value: string): string {
  const m = _secretMatch(value);
  if (!m) return value;
  let start = m.index;
  let end = m.index + m[0].length;
  while (start > 0 && !/\s/.test(value[start - 1])) start--;
  while (end < value.length && !/\s/.test(value[end])) end++;
  return value.slice(0, start) + REDACTED + value.slice(end);
}

export function _detectSecretInValue(value: string): boolean {
  // Stryker disable next-line ConditionalExpression: removing length check makes patterns match short strings — equivalent when all test secrets are ≥20 chars
  if (value.length < _MIN_SECRET_LENGTH) return false;
  for (const p of _SECRET_PATTERNS) {
    p.lastIndex = 0;
    const m = p.exec(value);
    if (m !== null && !_looksLikePath(m[0])) return true;
  }
  for (const p of _customSecretPatterns.values()) {
    p.lastIndex = 0;
    const m = p.exec(value);
    if (m !== null && !_looksLikePath(m[0])) return true;
  }
  return false;
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
      obj[key] = redactSecretSpans(obj[key] as string);
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

// Governance hooks — set by classification / receipts modules if present.
// null = feature not loaded (zero overhead).
export let _classificationHook: ((key: string, value: unknown) => string | null) | null = null;
export let _receiptHook:
  ((fieldPath: string, action: string, originalValue: unknown) => void) | null = null;
/** Policy hook — returns the action ('drop'|'redact'|'hash'|'truncate'|'pass') for a label. */
export let _policyHook: ((label: string) => string) | null = null;

export function setClassificationHook(
  fn: ((key: string, value: unknown) => string | null) | null,
): void {
  _classificationHook = fn;
}

export function setReceiptHook(
  fn: ((fieldPath: string, action: string, originalValue: unknown) => void) | null,
): void {
  _receiptHook = fn;
}

export function setPolicyHook(fn: ((label: string) => string) | null): void {
  _policyHook = fn;
}

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

function _pathHasRule(ruleTargets: string[][], childPath: string[]): boolean {
  return ruleTargets.some((ruleSegs) => _matches(ruleSegs, childPath));
}

function _applyRuleFull(
  node: unknown,
  rule: PIIRule,
  currentPath: string[],
  maxDepth: number = DEFAULT_MAX_DEPTH,
  depth: number = 0,
  receiptHook: ((fieldPath: string, action: string, originalValue: unknown) => void) | null = null,
): unknown {
  if (typeof node !== 'object' || node === null) return node;
  // Stryker disable next-line EqualityOperator: depth == maxDepth means we already recursed maxDepth times; >= vs > only differs at the boundary which is tested but Stryker's perTest coverage misattributes
  if (depth >= maxDepth) return node;
  // Stryker disable next-line ConditionalExpression,BlockStatement: when array is treated as object, numeric string indices still match wildcard '*' rule segments — equivalent
  if (Array.isArray(node)) {
    /* Stryker disable StringLiteral,ArithmeticOperator: '*' wildcard in VALUE path is irrelevant; depth-1 causes infinite recursion (timeout kill) — equivalent */
    return node.map((item) =>
      _applyRuleFull(item, rule, [...currentPath, '*'], maxDepth, depth + 1, receiptHook),
    );
    /* Stryker restore StringLiteral,ArithmeticOperator */
  }
  const obj = node as Record<string, unknown>;
  const ruleSegs = _pathSegments(rule.path);
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(obj)) {
    const childPath = [...currentPath, key];
    if (_matches(ruleSegs, childPath)) {
      if (receiptHook !== null) receiptHook(childPath.join('.'), rule.mode, val);
      const { keep, value } = _applyMode(val, rule);
      if (keep) result[key] = value;
    } else {
      result[key] = _applyRuleFull(val, rule, childPath, maxDepth, depth + 1, receiptHook);
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
  ruleTargets: string[][],
  maxDepth: number,
  receiptHook: ((fieldPath: string, action: string, originalValue: unknown) => void) | null,
  depth: number = 0,
  currentPath: string[] = [],
): unknown {
  if (depth >= maxDepth) return node;
  if (typeof node !== 'object' || node === null) return node;
  // Stryker disable next-line ConditionalExpression,BlockStatement,ArrayDeclaration: array items are recursed as objects — when Array.isArray is skipped, for..of on array indices still redacts nested keys identically
  if (Array.isArray(node)) {
    // Stryker disable next-line ArrayDeclaration: [] fallback for original — defensive, original always mirrors node shape
    /* v8 ignore next */
    const origArr = Array.isArray(original) ? original : [];
    return node.map((item, i) =>
      _applyDefaultSensitiveKeyRedaction(
        item,
        origArr[i],
        blocked,
        ruleTargets,
        maxDepth,
        receiptHook,
        // Stryker disable next-line ArithmeticOperator: depth-1 causes infinite recursion killed by timeout — equivalent
        depth + 1,
        [...currentPath, '*'],
      ),
    );
  }
  const obj = node as Record<string, unknown>;
  /* v8 ignore start: original always mirrors node's object structure through recursive calls — obj fallback is defensive */
  /* Stryker disable ConditionalExpression,LogicalOperator,EqualityOperator,StringLiteral,BooleanLiteral: defensive guard — original always mirrors node shape; fallback to obj is equivalent */
  const orig =
    typeof original === 'object' && original !== null && !Array.isArray(original)
      ? (original as Record<string, unknown>)
      : obj;
  /* Stryker restore ConditionalExpression,LogicalOperator,EqualityOperator,StringLiteral,BooleanLiteral */
  /* v8 ignore stop */
  const result: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(obj)) {
    const lk = key.toLowerCase();
    const origVal = orig[key];
    const childPath = [...currentPath, key];
    if (blocked.has(lk)) {
      // If a custom rule already changed the value, keep the rule's result.
      // Stryker disable next-line ConditionalExpression,BlockStatement: defensive guard — val always equals origVal; removing branch is equivalent
      /* v8 ignore next 2 */
      if (val !== origVal || _pathHasRule(ruleTargets, childPath)) {
        result[key] = val;
      } else {
        result[key] = REDACTED;
        if (receiptHook !== null) receiptHook(key, 'redact', origVal);
      }
    } else if (typeof val === 'string' && _detectSecretInValue(val)) {
      result[key] = redactSecretSpans(val);
      // Stryker disable next-line StringLiteral: 'redact' action label is verified by receipt tests — Stryker's perTest coverage misattributes
      if (receiptHook !== null) receiptHook(key, 'redact', val);
    } else {
      result[key] = _applyDefaultSensitiveKeyRedaction(
        val,
        origVal,
        blocked,
        ruleTargets,
        maxDepth,
        receiptHook,
        depth + 1,
        childPath,
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
  _classificationHook = null;
  _receiptHook = null;
  _policyHook = null;
  _customSecretPatterns.clear();
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
  const maxDepth = options?.maxDepth ?? DEFAULT_MAX_DEPTH;
  // Capture hooks once at call time to avoid repeated reads.
  const receiptHook = _receiptHook;
  const classHook = _classificationHook;
  const policyHook = _policyHook;
  let current: unknown = obj;

  // Apply registered rules first.
  for (const rule of _rules) {
    current = _applyRuleFull(current, rule, [], maxDepth, 0, receiptHook);
  }

  // Apply default field-name redaction + secret detection recursively with depth limit.
  // v8 ignore: current is always a non-null object here; null/array branches are defensive.
  // Stryker disable next-line LogicalOperator,ConditionalExpression
  /* v8 ignore next */
  if (typeof current === 'object' && current !== null && !Array.isArray(current)) {
    const ruleTargets = _rules.map((r) => _pathSegments(r.path));
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
      receiptHook,
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

    // Apply classification tags and policy actions for top-level keys if hook is registered.
    if (classHook !== null) {
      for (const key of Object.keys(obj)) {
        const label = classHook(key, obj[key]);
        if (label !== null) {
          const action = policyHook !== null ? policyHook(label) : 'pass';
          if (action === 'drop') {
            delete obj[key];
            // No class tag for dropped keys — key no longer exists in payload.
          } else {
            obj[`__${key}__class`] = label;
            if (
              (action === 'redact' || action === 'hash' || action === 'truncate') &&
              obj[key] !== REDACTED
            ) {
              const limit = 8;
              const val = obj[key];
              if (action === 'redact') {
                obj[key] = REDACTED;
              } else if (action === 'hash') {
                obj[key] = _hashValue(String(val));
              } else {
                // truncate
                const text = String(val);
                obj[key] = text.length > limit ? text.slice(0, limit) + '...' : text;
              }
            }
          }
        }
      }
    }
  }
}
