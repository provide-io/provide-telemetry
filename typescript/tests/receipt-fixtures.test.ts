// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Cross-language governance vectors: spec/receipt_fixtures.yaml.
//
// These are the only receipt tests that can fail for being *different from the
// other SDKs* rather than different from themselves. The canonical strings and
// digests were produced by independent implementations — `rfc8785` for JCS,
// Python's `hmac` for the signature — so reproducing them byte for byte is
// evidence of agreement, not of self-consistency.

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parse } from 'yaml';
import { specFixturePath } from './support/spec-fixtures.js';
import { hmacSha256Hex, sha256Hex } from '../src/hash.js';
import { canonicalJson, receiptPayload, signReceipt } from '../src/receipts.js';

interface ReceiptVector {
  id: string;
  key: string;
  input: unknown;
  normalized: unknown;
  canonical_json: string;
  receipt_id: string;
  timestamp: string;
  field_path: string;
  action: string;
  original_hash: string;
  payload: string;
  signature: string;
}

const FIXTURES = specFixturePath('receipt_fixtures.yaml');
const vectors = (parse(readFileSync(FIXTURES, 'utf8')) as { cases: ReceiptVector[] }).cases;
const enc = new TextEncoder();

describe('receipt vectors', () => {
  it('loads every committed case', () => {
    // Guards against a silently empty suite: a parse that yields no cases would
    // otherwise make every it.each below vacuously pass.
    expect(vectors.length).toBeGreaterThanOrEqual(7);
  });

  it.each(vectors)('canonicalizes $id to the committed JCS bytes', (vector) => {
    expect(canonicalJson(vector.normalized)).toBe(vector.canonical_json);
  });

  it.each(vectors)('signs $id to the committed payload and signature', (vector) => {
    const receipt = signReceipt(vector.normalized, {
      receiptId: vector.receipt_id,
      timestamp: vector.timestamp,
      fieldPath: vector.field_path,
      action: vector.action,
      key: enc.encode(vector.key),
    });
    expect(receipt.originalHash).toBe(vector.original_hash);
    expect(receiptPayload(receipt)).toBe(vector.payload);
    expect(receipt.hmac).toBe(vector.signature);
  });

  it.each(vectors)('derives $id digests from the canonical bytes, not the object', (vector) => {
    expect(sha256Hex(vector.canonical_json)).toBe(vector.original_hash);
    expect(hmacSha256Hex(enc.encode(vector.key), enc.encode(vector.payload))).toBe(
      vector.signature,
    );
  });
});

describe('non-finite normalization', () => {
  it('canonicalizes the raw input to the same bytes as the normalized form', () => {
    // The fixture carries `input` (with NaN/±Infinity) and `normalized` (with
    // nulls) separately so normalization is part of the contract rather than
    // left to each SDK to invent. YAML cannot express NaN portably, so the raw
    // values are rebuilt here from the case that declares them.
    const vector = vectors.find((v) => v.id === 'non_finite_normalization');
    expect(vector).toBeDefined();
    const raw = {
      ratio: Number.NaN,
      ceiling: Number.POSITIVE_INFINITY,
      floor: Number.NEGATIVE_INFINITY,
      ok: 2.0,
    };
    expect(canonicalJson(raw)).toBe((vector as ReceiptVector).canonical_json);
  });
});

describe('signReceipt without a key', () => {
  it('leaves the signature empty rather than signing under an empty key', () => {
    const vector = vectors[0] as ReceiptVector;
    const receipt = signReceipt(vector.normalized, {
      receiptId: vector.receipt_id,
      timestamp: vector.timestamp,
      fieldPath: vector.field_path,
      action: vector.action,
    });
    expect(receipt.originalHash).toBe(vector.original_hash);
    expect(receipt.hmac).toBe('');
    expect(receipt.serviceName).toBe('unknown');
  });

  it('carries the configured service name onto the receipt', () => {
    const vector = vectors[0] as ReceiptVector;
    const receipt = signReceipt(vector.normalized, {
      receiptId: vector.receipt_id,
      timestamp: vector.timestamp,
      fieldPath: vector.field_path,
      action: vector.action,
      serviceName: 'billing',
    });
    expect(receipt.serviceName).toBe('billing');
  });
});
