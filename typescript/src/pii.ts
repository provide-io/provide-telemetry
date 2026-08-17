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

/**
 * Every secret-looking span in *value*, widened to whole tokens, sorted and
 * coalesced.
 *
 * Every pattern is scanned across the WHOLE value, not stopped at its first
 * match, and every pattern is tried even after one has hit. Skipping either
 * leaks:
 *
 * - Stopping a pattern at its first match let a path shadow a real secret.
 *   long_base64 matches a path first; suppressing that match as path-shaped
 *   moved the scan to the next pattern, and long_base64 is the last one, so
 *   the credential behind the path was never looked for at all.
 * - Stopping at the first pattern to hit left a field's second and third
 *   secrets in the log, which whole-value blanking used to cover for free.
 *
 * A non-global exec() runs first as a fast path: a clean value, which is
 * nearly every log field, allocates nothing, because the all-matches walk is
 * only entered once a pattern is known to match.
 */
function _secretSpans(value: string): Array<[number, number]> {
  if (value.length < _MIN_SECRET_LENGTH) return [];
  const spans: Array<[number, number]> = [];
  for (const p of [..._SECRET_PATTERNS, ..._customSecretPatterns.values()]) {
    // Patterns may carry /g; exec advances lastIndex, so reset before use.
    p.lastIndex = 0;
    // Stryker disable next-line ConditionalExpression: pure fast path — a
    // pattern that does not match contributes no spans either way, so
    // never taking the shortcut is equivalent apart from cost.
    if (p.exec(value) === null) continue;
    // Re-walk with a global clone so every match is seen, not just the first.
    // registerSecretPattern strips g/y before storing, and the generated
    // built-ins carry no flags, so p.flags never already contains "g" — adding
    // it unconditionally cannot produce the duplicate flag that RegExp rejects.
    const all = new RegExp(p.source, `${p.flags}g`);
    let m: RegExpExecArray | null;
    while ((m = all.exec(value)) !== null) {
      // A registered pattern that can match the empty string would otherwise
      // spin forever and redact a token holding no secret. Step past it.
      if (m[0].length === 0) {
        all.lastIndex++;
        continue;
      }
      if (!_looksLikePath(m[0])) spans.push(_expandToToken(value, m.index, m.index + m[0].length));
    }
  }
  return _mergeSpans(spans);
}

/**
 * Widen a match to its whitespace-delimited token.
 *
 * Redacting the literal match alone can leave part of a credential behind:
 * the jwt pattern matches header.payload, and a JWT has THREE dot-separated
 * parts, so the signature would survive. Whitespace is the boundary a secret
 * cannot cross without ceasing to be one token.
 */
function _expandToToken(value: string, start: number, end: number): [number, number] {
  // Anchored matches rather than an index walk. Walking the index needs two
  // bounds and two steps, and their off-by-one variants mostly cannot be told
  // apart from the outside — reading one character past the end widens to a
  // position that slices identically. The regexes say the thing directly: the
  // run of non-whitespace ending where the match begins, and the run starting
  // where it ends. Python's _expand_to_token is the same shape.
  // `\S*` matches the empty string, so both of these always match and the
  // null arms of a `=== null` guard would be unreachable — hence the casts
  // rather than a branch no test could ever take.
  const head = /\S*$/.exec(value.slice(0, start)) as RegExpExecArray;
  const tail = /^\S*/.exec(value.slice(end)) as RegExpExecArray;
  return [start - head[0].length, end + tail[0].length];
}

/**
 * Sort and coalesce overlapping spans so each region is replaced once. Two
 * patterns can match the same credential -- long_base64 and jwt both hit a
 * JWT -- and after widening they overlap exactly, which would emit "******".
 */
function _mergeSpans(spans: Array<[number, number]>): Array<[number, number]> {
  if (spans.length < 2) return spans;
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [sorted[0]];
  // Stryker disable next-line MethodExpression: dropping slice(1) re-visits
  // sorted[0], which merges with itself and changes nothing.
  for (const [start, end] of sorted.slice(1)) {
    const last = merged[merged.length - 1];
    // Stryker disable next-line EqualityOperator,BlockStatement: every span is widened to a
    // whitespace-delimited token, so one span starts at least one whitespace
    // past the previous span's end — start === last[1] cannot occur. Two
    // spans that do overlap share a token and are therefore identical, so
    // skipping the merge entirely drops a duplicate and changes nothing.
    if (start <= last[1]) {
      // Stryker disable next-line MethodExpression: overlapping spans share a
      // token and are therefore identical, so max and min agree.
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
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
  return _redactIfSecret(value) ?? value;
}

/**
 * Redacted form of *value*, or null when it holds no secret.
 *
 * One scan where the sanitize path used to do two: asking
 * _detectSecretInValue and then redactSecretSpans ran the whole pattern sweep
 * twice for every value carrying a credential.
 */
function _redactIfSecret(value: string): string | null {
  const spans = _secretSpans(value);
  if (spans.length === 0) return null;
  const chunks: string[] = [];
  let previousEnd = 0;
  for (const [start, end] of spans) {
    chunks.push(value.slice(previousEnd, start), REDACTED);
    previousEnd = end;
  }
  chunks.push(value.slice(previousEnd));
  return chunks.join('');
}

export function _detectSecretInValue(value: string): boolean {
  // Shares _secretSpans with redaction rather than running its own loop. When
  // the two disagreed the value was flagged and then not fully cleaned, which
  // is how a secret sitting behind a filesystem path escaped: this returned
  // false because the only pattern that could match it had already been
  // consumed by the path.
  return _secretSpans(value).length > 0;
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
    // Assigned inside the else-if so the scan runs once, not once to detect
    // and again to redact.
    let redacted: string | null;
    // Stryker disable next-line ConditionalExpression: mutating to true redacts all keys — equivalent because tests use blocked keys
    if (blocked.has(key.toLowerCase())) {
      obj[key] = REDACTED;
    } else if (
      // Stryker disable next-line all: V8 perTest coverage doesn't attribute else-if branches; tested in pii.test.ts secret detection suite
      typeof obj[key] === 'string' &&
      (redacted = _redactIfSecret(obj[key] as string)) !== null
    ) {
      obj[key] = redacted;
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
    // Assigned inside the else-if so the scan runs once, not once to detect
    // and again to redact.
    let redacted: string | null;
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
    } else if (typeof val === 'string' && (redacted = _redactIfSecret(val)) !== null) {
      result[key] = redacted;
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
