// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Recursive input hardening — the structural stage of the signal pipeline.
 *
 * Split out of pii.ts because it is a different kind of work: pii.ts decides
 * *policy* (which fields are sensitive, and what to do with them), while this
 * decides *shape* (how deep, how wide, how long, and what to do with values
 * JSON cannot represent). Hardening runs first, so everything downstream —
 * rule matching, secret detection, serialization, export — operates on a
 * finite, JSON-shaped value.
 *
 * Before this existed, TypeScript hardened only the top level of the OTel
 * export path: one pass of string truncation and an attribute-count cap. A
 * nested object went to the exporter unbounded, and a self-referential one
 * reached its serializer intact.
 */

import { DEFAULT_MAX_DEPTH, REDACTED } from './pii.js';

/**
 * Control characters stripped from hardened strings.
 *
 * TAB, LF and CR survive — they are legitimate content in a message or stack
 * trace. The range is character-for-character the one Python's `harden_input`
 * uses (`logger/processors.py:_CONTROL_CHAR_RE`), so the same input yields the
 * same string in both SDKs.
 */
// eslint-disable-next-line no-control-regex -- stripping control characters is the point
const _CONTROL_CHARS = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;

/**
 * Control characters stripped from hardened object keys.
 *
 * Keys are rendered bare by the pretty renderer, so unlike values they cannot
 * keep TAB/LF/CR either: any of the three splits or misaligns the rendered
 * line — a key containing `"\n2026-08-10 [error] ..."` forges a second,
 * attacker-controlled log record. The range is character-for-character the one
 * Python's `_harden_keys` uses (`logger/processors.py:_CONTROL_CHAR_KEY_RE`).
 */
// eslint-disable-next-line no-control-regex -- stripping control characters is the point
const _KEY_CONTROL_CHARS = /[\x00-\x1f\x7f]/g;

/** Default caps, matching TelemetryConfig's security defaults. */
const _DEFAULT_MAX_VALUE_LENGTH = 1024;
const _DEFAULT_MAX_ATTR_COUNT = 64;

export interface HardenOptions {
  /** Strings longer than this are truncated and suffixed with '...'. Default 1024. */
  maxValueLength?: number;
  /** Maximum keys retained per object. 0 disables the cap. Default 64. */
  maxAttrCount?: number;
  /** Maximum nesting depth before a composite collapses to '***'. Default 8. */
  maxDepth?: number;
}

/**
 * Recursively bound a value to a finite, JSON-shaped, non-cyclic form.
 *
 * Composites are traversed through a `WeakSet`, so a value reached more than
 * once — a true cycle, or a shared subtree — collapses to `'***'` rather than
 * expanding. That bound is the point: a cycle is an infinite serializer, and a
 * shared subtree referenced n times is an n-fold blowup, and both arrive from
 * caller-supplied data.
 *
 * Anything JSON has no representation for (functions, symbols, bigints, Maps,
 * Sets, class instances with a non-plain prototype) also becomes `'***'` — the
 * alternative is each downstream serializer inventing its own answer.
 */
export function harden(value: unknown, options?: HardenOptions): unknown {
  const maxValueLength = options?.maxValueLength ?? _DEFAULT_MAX_VALUE_LENGTH;
  const maxAttrCount = options?.maxAttrCount ?? _DEFAULT_MAX_ATTR_COUNT;
  const maxDepth = options?.maxDepth ?? DEFAULT_MAX_DEPTH;
  return _harden(value, maxValueLength, maxAttrCount, maxDepth, 0, new WeakSet<object>());
}

function _isPlainObject(value: object): boolean {
  const proto = Object.getPrototypeOf(value) as object | null;
  return proto === Object.prototype || proto === null;
}

function _hardenScalar(value: unknown, maxValueLength: number): unknown {
  if (typeof value === 'string') {
    const cleaned = value.replace(_CONTROL_CHARS, '');
    return cleaned.length > maxValueLength ? cleaned.slice(0, maxValueLength) + '...' : cleaned;
  }
  // null, undefined, boolean and numbers survive as themselves — including
  // NaN and ±Infinity, which Python's harden_input and Go's hardenScalar also
  // pass through untouched. Redacting them here diverged the exported value
  // *and* the receipt digest per SDK; canonicalization is where they become
  // `null`, the spelling the receipt fixtures fix. Every other primitive
  // (bigint, symbol) has no JSON form.
  if (typeof value === 'number') return value;
  if (value === null || value === undefined || typeof value === 'boolean') return value;
  return REDACTED;
}

function _harden(
  value: unknown,
  maxValueLength: number,
  maxAttrCount: number,
  maxDepth: number,
  depth: number,
  seen: WeakSet<object>,
): unknown {
  if (typeof value !== 'object' || value === null) return _hardenScalar(value, maxValueLength);
  if (depth >= maxDepth) return REDACTED;
  if (seen.has(value)) return REDACTED;
  seen.add(value);

  if (Array.isArray(value)) {
    return value.map((item) =>
      _harden(item, maxValueLength, maxAttrCount, maxDepth, depth + 1, seen),
    );
  }
  if (!_isPlainObject(value)) return REDACTED;

  const source = value as Record<string, unknown>;
  const keys = Object.keys(source);
  const kept = maxAttrCount > 0 ? keys.slice(0, maxAttrCount) : keys;
  const result: Record<string, unknown> = {};
  for (const key of kept) {
    // Keys are hardened as well as values, at every level, mirroring Python's
    // _harden_keys. Cleaning is many-to-one ("trace_i\x00d" and "trace_id"
    // both come out as "trace_id"), and Object.keys never yields duplicates,
    // so an untouched key colliding with an occupied slot always means a
    // sanitized key squatted there first: a key that needed cleaning never
    // displaces one already present, and a key that needed no cleaning always
    // reclaims its slot — re-assignment keeps the original insertion position,
    // so reclaiming does not reorder the record. Two sanitized keys that
    // collide keep the first, which is arbitrary but loses no genuine field.
    const name = key.replace(_KEY_CONTROL_CHARS, '');
    // hasOwnProperty rather than `name in result`: a key cleaned down to
    // "toString" must collide with a genuine "toString" field, not with
    // Object.prototype.
    if (Object.prototype.hasOwnProperty.call(result, name) && name !== key) continue;
    result[name] = _harden(source[key], maxValueLength, maxAttrCount, maxDepth, depth + 1, seen);
  }
  return result;
}

/**
 * Harden a log record in place, preserving the caller's object identity.
 *
 * The logger and OTel paths both hold a reference to the record they are
 * building, so they need the mutation rather than a replacement value.
 */
export function hardenRecord(obj: Record<string, unknown>, options?: HardenOptions): void {
  const hardened = harden(obj, options) as Record<string, unknown>;
  // Clear unconditionally rather than diffing: hardening can drop keys (the
  // attribute cap), and re-assigning restores the survivors in their original
  // order, so a membership check would only be a branch that never differs.
  for (const key of Object.keys(obj)) delete obj[key];
  Object.assign(obj, hardened);
}
