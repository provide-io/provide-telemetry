// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for cryptographic redaction receipts.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { harden } from '../src/harden.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { hmacSha256Hex, sha256Hex } from '../src/hash.js';
import { sanitizePayload, resetPiiRulesForTests, registerPiiRule } from '../src/pii.js';
import {
  canonicalJson,
  enableReceipts,
  getEmittedReceiptsForTests,
  emitReceipt,
  MissingReceiptSinkError,
  receiptPayload,
  TEST_RECEIPT_CAPACITY,
  TestReceiptCollector,
  resetReceiptsForTests,
  signReceipt,
  _setTestModeForTests,
} from '../src/receipts.js';
import type { RedactionReceipt } from '../src/receipts.js';

const enc = new TextEncoder();

function makeReceipt(): RedactionReceipt {
  return {
    receiptId: 'r-1',
    timestamp: '2026-08-07T00:00:00.000Z',
    serviceName: 'svc',
    fieldPath: 'user.password',
    action: 'redact',
    originalHash: 'a'.repeat(64),
    hmac: '',
  };
}

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

describe('receipt original_hash is SHA-256 over the canonical JSON form', () => {
  it('hashes the JCS serialization, not the display form', () => {
    enableReceipts({ enabled: true });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(1);
    expect(receipts[0].originalHash).toBe(sha256Hex('"secret123"'));
  });

  it('distinguishes a numeric value from its string spelling', () => {
    // The point of canonicalizing rather than calling String(): hashing the
    // display form makes the number 1 and the string "1" indistinguishable in
    // the audit trail.
    enableReceipts({ enabled: true });
    const asNumber = { password: 1 };
    const asString = { password: '1' };
    sanitizePayload(asNumber);
    sanitizePayload(asString);
    const receipts = getEmittedReceiptsForTests();
    expect(receipts).toHaveLength(2);
    expect(receipts[0].originalHash).not.toBe(receipts[1].originalHash);
    expect(receipts[0].originalHash).toBe(sha256Hex('1'));
    expect(receipts[1].originalHash).toBe(sha256Hex('"1"'));
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
    expect(receiptPayload(r)).toBe(payload);
    expect(r.hmac).toBe(hmacSha256Hex(enc.encode('test-key'), enc.encode(payload)));
  });

  it('is a real HMAC, not a keyed digest of the concatenation', () => {
    // The predecessor computed sha256("key|payload"), which reproduces no
    // cross-language vector and is length-extendable.
    enableReceipts({ enabled: true, signingKey: 'test-key' });
    const obj = { password: 'secret123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    const r = getEmittedReceiptsForTests()[0];
    expect(r.hmac).not.toBe(sha256Hex(`test-key|${receiptPayload(r)}`));
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
    const tamperedHMAC = hmacSha256Hex(enc.encode('test-key'), enc.encode(tamperedPayload));
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

describe('production mode (testMode=false) requires a sink', () => {
  it('delivers to the configured sink instead of the test collector', () => {
    _setTestModeForTests(false);
    try {
      const delivered: unknown[] = [];
      enableReceipts({
        enabled: true,
        sink: {
          emit: (r) => {
            delivered.push(r);
            return true;
          },
        },
      });
      const obj = { password: 'secret123' }; // pragma: allowlist secret
      sanitizePayload(obj);
      expect(delivered).toHaveLength(1);
      expect(getEmittedReceiptsForTests()).toHaveLength(0);
    } finally {
      _setTestModeForTests(true);
    }
  });

  it('refuses to enable without a sink rather than discarding receipts', () => {
    // Previously this configuration signed a receipt for every redaction and
    // then dropped it, so a service could believe it had an audit trail.
    _setTestModeForTests(false);
    try {
      expect(() => {
        enableReceipts({ enabled: true });
      }).toThrow(MissingReceiptSinkError);
      // The message is the whole value of this error: it has to say what was
      // misconfigured and what to do, or a caller just sees a thrown class.
      let caught: unknown;
      try {
        enableReceipts({ enabled: true });
      } catch (error) {
        caught = error;
      }
      expect((caught as Error).name).toBe('MissingReceiptSinkError');
      expect((caught as Error).message).toBe(
        'receipts are enabled but no receiptSink is configured; ' +
          'generated receipts would be computed and then discarded. ' +
          'Pass a ReceiptSink, or disable receipts.',
      );
    } finally {
      _setTestModeForTests(true);
    }
  });

  it('still allows disabling receipts without a sink', () => {
    _setTestModeForTests(false);
    try {
      expect(() => {
        enableReceipts({ enabled: false });
      }).not.toThrow();
    } finally {
      _setTestModeForTests(true);
    }
  });
});

describe('signReceipt defaults', () => {
  it('defaults serviceName to "unknown" when the caller omits it', () => {
    const receipt = signReceipt('value', {
      receiptId: 'r-1',
      timestamp: '2026-08-07T00:00:00.000Z',
      fieldPath: 'user.password',
      action: 'redact',
    });
    expect(receipt.serviceName).toBe('unknown');
  });

  it('uses the caller service name when given', () => {
    const receipt = signReceipt('value', {
      receiptId: 'r-1',
      timestamp: '2026-08-07T00:00:00.000Z',
      fieldPath: 'user.password',
      action: 'redact',
      serviceName: 'billing',
    });
    expect(receipt.serviceName).toBe('billing');
  });

  it('hashes non-finite numbers as the null spelling, so digests agree across SDKs', () => {
    const opts = {
      receiptId: 'r-1',
      timestamp: '2026-08-10T00:00:00.000Z',
      fieldPath: 'metrics.ratio',
      action: 'redact',
    };
    const nullHash = signReceipt(null, opts).originalHash;
    expect(signReceipt(Number.NaN, opts).originalHash).toBe(nullHash);
    expect(signReceipt(Number.POSITIVE_INFINITY, opts).originalHash).toBe(nullHash);
    expect(signReceipt(Number.NEGATIVE_INFINITY, opts).originalHash).toBe(nullHash);
    // Hardening passes non-finite numbers through unchanged (it no longer
    // redacts them to '***'), so a hardened value signs to the same digest —
    // in every SDK, not just this one.
    expect(signReceipt(harden(Number.NaN), opts).originalHash).toBe(nullHash);
  });
});

describe('canonicalJson', () => {
  it('orders object keys by UTF-16 code unit, not insertion order', () => {
    expect(canonicalJson({ zeta: 1, Alpha: 2, alpha: 3 })).toBe('{"Alpha":2,"alpha":3,"zeta":1}');
  });

  it('collapses negative zero, which JSON.stringify already does and JCS requires', () => {
    expect(canonicalJson({ balance: -0 })).toBe('{"balance":0}');
  });

  it('normalizes values JSON cannot encode to null', () => {
    expect(canonicalJson(Number.NaN)).toBe('null');
    expect(canonicalJson(Number.POSITIVE_INFINITY)).toBe('null');
    expect(canonicalJson(Number.NEGATIVE_INFINITY)).toBe('null');
    expect(canonicalJson(undefined)).toBe('null');
  });

  it('normalizes bigint, symbol, and function without throwing', () => {
    // JSON.stringify throws a TypeError on a bigint. Throwing here would turn
    // a log call into an exception, because canonicalization runs inside the
    // redaction hook.
    expect(canonicalJson(10n)).toBe('null');
    expect(canonicalJson(Symbol('s'))).toBe('null');
    expect(canonicalJson(() => 1)).toBe('null');
    expect(canonicalJson({ n: 10n })).toBe('{"n":null}');
  });

  it('encodes the JSON scalars it can', () => {
    expect(canonicalJson('a"b')).toBe('"a\\"b"');
    expect(canonicalJson(1.5)).toBe('1.5');
    expect(canonicalJson(true)).toBe('true');
    expect(canonicalJson(null)).toBe('null');
  });

  it('keeps undefined array elements and object values as null rather than dropping them', () => {
    // A vanishing key would change the hashed structure.
    expect(canonicalJson([1, undefined, 3])).toBe('[1,null,3]');
    expect(canonicalJson({ a: undefined })).toBe('{"a":null}');
  });

  it('recurses through nested arrays and objects', () => {
    expect(canonicalJson({ b: [{ d: 1, c: 2 }], a: null })).toBe('{"a":null,"b":[{"c":2,"d":1}]}');
  });

  it('serializes a self-referential object as null instead of recursing to a RangeError', () => {
    // Mirrors Python receipts._canonical: a composite already on the current
    // serialization path spells null, the same spelling every other
    // JSON-unencodable value gets.
    const cyclic: Record<string, unknown> = { name: 'root' };
    cyclic['self'] = cyclic;
    expect(canonicalJson(cyclic)).toBe('{"name":"root","self":null}');
  });

  it('serializes an array cycle as null', () => {
    const arr: unknown[] = [1];
    arr.push(arr);
    expect(canonicalJson(arr)).toBe('[1,null]');
  });

  it('serializes an indirect cycle at the point it closes', () => {
    const inner: Record<string, unknown> = {};
    const outer = { inner };
    inner['back'] = outer;
    expect(canonicalJson(outer)).toBe('{"inner":{"back":null}}');
  });

  it('serializes a shared acyclic subtree fully at every occurrence', () => {
    // The guard is path-scoped: a value leaves the set when its subtree
    // completes, so sharing is not mistaken for a cycle.
    const shared = { k: 1 };
    expect(canonicalJson({ a: shared, b: shared })).toBe('{"a":{"k":1},"b":{"k":1}}');
    expect(canonicalJson([shared, shared])).toBe('[{"k":1},{"k":1}]');
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

describe('sink accounting (health.receiptFailures)', () => {
  beforeEach(() => {
    _resetHealthForTests();
  });

  it('counts a refused receipt without logging', () => {
    // The error path must never log: the logger produces redactions,
    // redactions produce receipts, and a sink that fails on every receipt
    // would otherwise drive an unbounded log -> receipt -> log cycle.
    const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      emitReceipt(makeReceipt(), { emit: () => false });
      expect(getHealthSnapshot().receiptFailures).toBe(1);
      expect(consoleSpy).not.toHaveBeenCalled();
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      consoleSpy.mockRestore();
      errorSpy.mockRestore();
    }
  });

  it('counts a throwing sink the same as a refusing one', () => {
    emitReceipt(makeReceipt(), {
      emit: () => {
        throw new Error('sink is down');
      },
    });
    expect(getHealthSnapshot().receiptFailures).toBe(1);
  });

  it('does not count an accepted receipt', () => {
    const sink = new TestReceiptCollector();
    emitReceipt(makeReceipt(), sink);
    expect(getHealthSnapshot().receiptFailures).toBe(0);
    expect(sink.receipts).toHaveLength(1);
  });

  it('accumulates across failures', () => {
    const failing = { emit: () => false };
    emitReceipt(makeReceipt(), failing);
    emitReceipt(makeReceipt(), failing);
    expect(getHealthSnapshot().receiptFailures).toBe(2);
  });

  it('counts refusals raised through the live redaction path', () => {
    _setTestModeForTests(false);
    try {
      enableReceipts({ enabled: true, sink: { emit: () => false } });
      const obj = { password: 'secret123' }; // pragma: allowlist secret
      sanitizePayload(obj);
      expect(getHealthSnapshot().receiptFailures).toBe(1);
    } finally {
      _setTestModeForTests(true);
    }
  });
});

describe('TestReceiptCollector capacity', () => {
  it('retains the newest receipts once full, dropping the oldest', () => {
    const sink = new TestReceiptCollector();
    for (let i = 0; i < TEST_RECEIPT_CAPACITY + 5; i++) {
      sink.emit({ ...makeReceipt(), receiptId: `id-${String(i)}` });
    }
    expect(sink.receipts).toHaveLength(TEST_RECEIPT_CAPACITY);
    expect(sink.receipts[0].receiptId).toBe('id-5');
    expect(sink.receipts[TEST_RECEIPT_CAPACITY - 1].receiptId).toBe(
      `id-${String(TEST_RECEIPT_CAPACITY + 4)}`,
    );
  });

  it('keeps every receipt below the cap', () => {
    const sink = new TestReceiptCollector();
    for (let i = 0; i < TEST_RECEIPT_CAPACITY; i++) {
      sink.emit({ ...makeReceipt(), receiptId: `id-${String(i)}` });
    }
    expect(sink.receipts).toHaveLength(TEST_RECEIPT_CAPACITY);
    expect(sink.receipts[0].receiptId).toBe('id-0');
  });
});
