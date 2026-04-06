// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for cryptographic redaction receipts.
 */

import { createHash, createHmac } from 'crypto';
import { describe, it, expect, beforeEach } from 'vitest';
import { sanitizePayload, resetPiiRulesForTests } from '../src/pii';
import { enableReceipts, getEmittedReceiptsForTests, resetReceiptsForTests } from '../src/receipts';

beforeEach(() => {
  resetPiiRulesForTests();
  resetReceiptsForTests();
});

describe('receipts disabled by default', () => {
  it('emits no receipts before enableReceipts is called', () => {
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    expect(getEmittedReceiptsForTests()).toHaveLength(0);
  });
});

describe('receipts emitted when enabled', () => {
  it('generates a receipt when a sensitive field is sanitized', () => {
    enableReceipts({ enabled: true, serviceName: 'test-svc' });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    const r = receipts[0];
    expect(r.fieldPath).toBe('password');
    expect(r.action).toBe('redact');
    expect(r.receiptId.length).toBeGreaterThan(0);
  });
});

describe('receipt original_hash is SHA-256', () => {
  it('hashes the original value with SHA-256', () => {
    enableReceipts({ enabled: true });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    const expected = createHash('sha256').update('secret123').digest('hex');
    expect(receipts[0].originalHash).toBe(expected);
  });
});

describe('receipt HMAC when key provided', () => {
  it('computes HMAC correctly with a signing key', () => {
    enableReceipts({ enabled: true, signingKey: 'test-key' });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    const r = receipts[0];
    expect(r.hmac).not.toBe('');
    const payload = `${r.receiptId}|${r.timestamp}|${r.fieldPath}|${r.action}|${r.originalHash}`;
    const expected = createHmac('sha256', 'test-key').update(payload).digest('hex');
    expect(r.hmac).toBe(expected);
  });
});

describe('receipt HMAC empty when no key', () => {
  it('leaves hmac as empty string when no signing key', () => {
    enableReceipts({ enabled: true });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    expect(receipts[0].hmac).toBe('');
  });
});

describe('receipt tamper detection', () => {
  it('produces a different HMAC after tampering with field_path', () => {
    enableReceipts({ enabled: true, signingKey: 'test-key' });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    const r = receipts[0];
    const tamperedPayload = `${r.receiptId}|${r.timestamp}|tampered.path|${r.action}|${r.originalHash}`;
    const tamperedHMAC = createHmac('sha256', 'test-key').update(tamperedPayload).digest('hex');
    expect(r.hmac).not.toBe(tamperedHMAC);
  });
});

describe('enable/disable toggle', () => {
  it('unregisters the hook when enabled=false', () => {
    enableReceipts({ enabled: true });
    enableReceipts({ enabled: false });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    expect(getEmittedReceiptsForTests()).toHaveLength(0);
  });
});

describe('receipt_id is UUID format', () => {
  it('receipt_id has UUID format (36 chars, dashes)', () => {
    enableReceipts({ enabled: true });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    const rid = receipts[0].receiptId;
    expect(rid).toHaveLength(36);
    expect(rid[8]).toBe('-');
    expect(rid[13]).toBe('-');
    expect(rid[18]).toBe('-');
    expect(rid[23]).toBe('-');
  });
});

describe('service name is set in receipt', () => {
  it('receipt.serviceName reflects the configured service name', () => {
    enableReceipts({ enabled: true, serviceName: 'my-service' });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    expect(receipts[0].serviceName).toBe('my-service');
  });
});
