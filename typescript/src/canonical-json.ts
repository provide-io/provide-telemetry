// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * RFC 8785 (JCS) canonical JSON.
 *
 * One canonicaliser, shared by the two places that hash a structured value:
 * redaction receipts (`receipts.ts`) hash a redacted value's canonical form,
 * and PII hash mode (`pii.ts`) hashes a non-string value's canonical form, so
 * both digests agree across SDKs and across types — the string `"1"` and the
 * number `1` must not collide.
 *
 * Lives in its own module rather than in receipts.ts because pii.ts needs it
 * and receipts.ts imports pii.ts; keeping it here avoids an import cycle.
 *
 * Pinned by `spec/receipt_fixtures.yaml` and the `pii_hash` cases of
 * `spec/behavioral_fixtures.yaml`.
 */

// ── RFC 8785 (JCS) canonicalization ──────────────────────────────────────────
//
// JCS was specified against ECMAScript, so most of it is already the platform's
// behavior: `JSON.stringify` emits exactly the string escaping JCS requires,
// and JavaScript's Number-to-string is the binary64 rendering JCS mandates —
// including `-0` printing as `0`, which the negative_zero_collapses vector
// pins. The only things left to do here are ordering object keys by UTF-16 code
// unit and normalizing the values JSON has no encoding for.

/**
 * Serialize a value to its RFC 8785 canonical JSON form.
 *
 * NaN and ±Infinity have no JSON encoding, so they normalize to `null` — the
 * spelling `spec/receipt_fixtures.yaml`'s non_finite_normalization case fixes
 * for every SDK. `undefined` normalizes the same way rather than vanishing,
 * because a key that disappears would change the hashed structure.
 *
 * A composite reached twice on one path — a cycle — canonicalizes to `null`
 * rather than recursing to a RangeError. The guard is path-scoped (a value
 * leaves the set when its subtree completes), so a shared *acyclic* subtree
 * serializes fully at every occurrence — Python's `receipts._canonical`
 * carries the same set the same way. Hardening replaces cycles with `'***'`
 * before they get here; this is the backstop for a direct call.
 */
export function canonicalJson(value: unknown): string {
  return _canonical(value, new Set<object>());
}

function _canonical(value: unknown, path: Set<object>): string {
  // Non-finite numbers need no branch: JSON.stringify already renders NaN and
  // ±Infinity as `null`, which is exactly the spelling the fixture fixes.
  // bigint is handled here rather than left to JSON.stringify, which throws a
  // TypeError on it. Throwing is not an option on this path: canonicalization
  // runs inside the redaction hook, so it would turn a log call into an
  // exception. In the normal pipeline hardening has already replaced these
  // with '***'; this branch covers a direct signReceipt call.
  if (typeof value === 'bigint' || typeof value === 'symbol' || typeof value === 'function') {
    return 'null';
  }
  if (value === undefined) return 'null';
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (path.has(value)) return 'null';
  path.add(value);
  try {
    if (Array.isArray(value)) {
      return `[${value.map((item) => _canonical(item, path)).join(',')}]`;
    }
    const source = value as Record<string, unknown>;
    const body = Object.keys(source)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${_canonical(source[key], path)}`)
      .join(',');
    return `{${body}}`;
  } finally {
    path.delete(value);
  }
}
