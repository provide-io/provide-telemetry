// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for cryptographic redaction receipts.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { sha256Hex } from '../src/hash';
import { sanitizePayload, resetPiiRulesForTests, registerPiiRule } from '../src/pii';
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
    const expected = sha256Hex('secret123');
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
    const expected = sha256Hex(`test-key|${payload}`);
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
    const tamperedHMAC = sha256Hex(`test-key|${tamperedPayload}`);
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

  it('receipt.serviceName defaults to "unknown" when not specified', () => {
    enableReceipts({ enabled: true });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    expect(receipts[0].serviceName).toBe('unknown');
  });
});

describe('receipts from custom PII rules (covers _applyRuleFull receipt hook path)', () => {
  it('emits a receipt when a custom rule matches a field', () => {
    enableReceipts({ enabled: true, serviceName: 'rule-svc' });
    registerPiiRule({ path: 'user.email', mode: 'redact' });
    const obj = { user: { email: 'alice@example.com' } };
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    expect(receipts[0].fieldPath).toBe('user.email');
    expect(receipts[0].action).toBe('redact');
  });
});

describe('receipts emitted for secret detection in non-blocked keys (covers _applyDefaultSensitiveKeyRedaction secret path)', () => {
  it('emits a receipt when a secret pattern is detected in an unblocked field', () => {
    enableReceipts({ enabled: true });
    // 'custom_field' is not a blocked key — secret is detected by VALUE pattern (40+ hex chars)
    const obj = { custom_field: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    expect(receipts[0].fieldPath).toBe('custom_field');
  });
});

describe('receipts emitted for sensitive keys inside arrays (covers array branch in _applyDefaultSensitiveKeyRedaction)', () => {
  it('emits receipts for sensitive fields inside array items', () => {
    enableReceipts({ enabled: true });
    const obj = { users: [{ password: 'pass1' }, { password: 'pass2' }] }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts.length).toBeGreaterThanOrEqual(2);
    expect(receipts.every((r) => r.action === 'redact')).toBe(true);
  });
});
