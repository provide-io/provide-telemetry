// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  _classifyField,
  getClassificationPolicy,
  registerClassificationRules,
  resetClassificationForTests,
  setClassificationPolicy,
} from '../src/classification';
import type { ClassificationPolicy, ClassificationRule, DataClass } from '../src/classification';
import {
  resetPiiRulesForTests,
  sanitizePayload,
  _classificationHook,
  _policyHook,
} from '../src/pii';

afterEach(() => {
  resetClassificationForTests();
  resetPiiRulesForTests();
});

// ── DataClass type values ─────────────────────────────────────────────────────

describe('DataClass type values', () => {
  it('PUBLIC is a valid DataClass', () => {
    const dc: DataClass = 'PUBLIC';
    expect(dc).toBe('PUBLIC');
  });
  it('INTERNAL is a valid DataClass', () => {
    const dc: DataClass = 'INTERNAL';
    expect(dc).toBe('INTERNAL');
  });
  it('PII is a valid DataClass', () => {
    const dc: DataClass = 'PII';
    expect(dc).toBe('PII');
  });
  it('PHI is a valid DataClass', () => {
    const dc: DataClass = 'PHI';
    expect(dc).toBe('PHI');
  });
  it('PCI is a valid DataClass', () => {
    const dc: DataClass = 'PCI';
    expect(dc).toBe('PCI');
  });
  it('SECRET is a valid DataClass', () => {
    const dc: DataClass = 'SECRET';
    expect(dc).toBe('SECRET');
  });
});

// ── Default policy ────────────────────────────────────────────────────────────

describe('default ClassificationPolicy', () => {
  it('has correct default values', () => {
    const p = getClassificationPolicy();
    expect(p.PUBLIC).toBe('pass');
    expect(p.INTERNAL).toBe('pass');
    expect(p.PII).toBe('redact');
    expect(p.PHI).toBe('drop');
    expect(p.PCI).toBe('hash');
    expect(p.SECRET).toBe('drop');
  });
});

// ── No rules → hook is null ───────────────────────────────────────────────────

describe('hook state', () => {
  it('hook is null before any rules are registered', () => {
    // After afterEach reset, hook should be null.
    expect(_classificationHook).toBeNull();
  });

  it('registerClassificationRules installs the hook', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    // Access _classificationHook from pii module via sanitizePayload side-effects.
    const obj: Record<string, unknown> = { email: 'alice@example.com' };
    sanitizePayload(obj);
    expect(obj['__email__class']).toBe('PII');
  });

  it('registering empty list installs the hook', () => {
    registerClassificationRules([]);
    // Hook installed, but empty rules → no tags.
    const obj: Record<string, unknown> = { email: 'alice@example.com' };
    sanitizePayload(obj);
    expect(obj['__email__class']).toBeUndefined();
  });
});

// ── Classification tags in sanitizePayload ────────────────────────────────────

describe('classification tags', () => {
  it('adds __key__class tag for matched key', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    const obj: Record<string, unknown> = { email: 'alice@example.com', name: 'Alice' };
    sanitizePayload(obj);
    expect(obj['__email__class']).toBe('PII');
    expect(obj['__name__class']).toBeUndefined();
  });

  it('drops PHI key (default policy: PHI=drop)', () => {
    registerClassificationRules([{ pattern: 'dob', classification: 'PHI' }]);
    const obj: Record<string, unknown> = { dob: '1990-01-01' };
    sanitizePayload(obj);
    // PHI defaults to "drop" — key is removed and no class tag appears.
    expect(obj['dob']).toBeUndefined();
    expect(obj['__dob__class']).toBeUndefined();
  });

  it('adds PCI tag', () => {
    registerClassificationRules([{ pattern: 'card_num', classification: 'PCI' }]);
    const obj: Record<string, unknown> = { card_num: '4111111111111111' };
    sanitizePayload(obj);
    expect(obj['__card_num__class']).toBe('PCI');
  });
});

// ── First-match wins ──────────────────────────────────────────────────────────

describe('first-match semantics', () => {
  it('first matching rule wins', () => {
    const rules: ClassificationRule[] = [
      { pattern: 'email', classification: 'PII' },
      { pattern: 'email', classification: 'PHI' },
    ];
    registerClassificationRules(rules);
    expect(_classifyField('email', 'alice@example.com')).toBe('PII');
  });
});

// ── Wildcard patterns ─────────────────────────────────────────────────────────

describe('wildcard patterns', () => {
  it('* wildcard matches multiple keys', () => {
    registerClassificationRules([{ pattern: 'user_*', classification: 'INTERNAL' }]);
    expect(_classifyField('user_id', 42)).toBe('INTERNAL');
    expect(_classifyField('user_name', 'Alice')).toBe('INTERNAL');
  });

  it('wildcard does not match unrelated key', () => {
    registerClassificationRules([{ pattern: 'user_*', classification: 'INTERNAL' }]);
    expect(_classifyField('email', 'alice@example.com')).toBeNull();
  });
});

// ── Regex special char escaping in glob pattern ─────────────────────────────

describe('glob pattern escaping', () => {
  it('dot in pattern is escaped and matched literally (not as regex wildcard)', () => {
    registerClassificationRules([{ pattern: 'user.email', classification: 'PII' }]);
    // 'user.email' should match literally — dot is NOT a wildcard
    expect(_classifyField('user.email', 'a@b.com')).toBe('PII');
    // If dot is not escaped, 'userXemail' would also match — should NOT
    expect(_classifyField('userXemail', 'a@b.com')).toBeNull();
  });
});

// ── No match → null ───────────────────────────────────────────────────────────

describe('no match', () => {
  it('returns null when no rules registered', () => {
    expect(_classifyField('email', 'alice@example.com')).toBeNull();
  });

  it('returns null when no rule matches', () => {
    registerClassificationRules([{ pattern: 'dob', classification: 'PHI' }]);
    expect(_classifyField('email', 'alice@example.com')).toBeNull();
  });
});

// ── Unmatched key → no tag in payload ────────────────────────────────────────

describe('unmatched key in payload', () => {
  it('adds no class tag for unmatched key', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    const obj: Record<string, unknown> = { name: 'Alice' };
    sanitizePayload(obj);
    expect(Object.keys(obj).some((k) => k.endsWith('__class'))).toBe(false);
  });
});

// ── setClassificationPolicy / getClassificationPolicy ────────────────────────

describe('policy management', () => {
  it('set and get policy roundtrip', () => {
    const policy: ClassificationPolicy = {
      PUBLIC: 'pass',
      INTERNAL: 'pass',
      PII: 'drop',
      PHI: 'redact',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    };
    setClassificationPolicy(policy);
    const got = getClassificationPolicy();
    expect(got.PII).toBe('drop');
    expect(got.PHI).toBe('redact');
  });

  it('getClassificationPolicy returns a copy (not reference)', () => {
    const p1 = getClassificationPolicy();
    p1.PII = 'mutated';
    const p2 = getClassificationPolicy();
    expect(p2.PII).toBe('redact');
  });
});

// ── resetClassificationForTests ───────────────────────────────────────────────

describe('resetClassificationForTests', () => {
  it('clears rules after reset', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    resetClassificationForTests();
    expect(_classifyField('email', 'alice@example.com')).toBeNull();
  });

  it('removes hook after reset', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    resetClassificationForTests();
    const obj: Record<string, unknown> = { email: 'alice@example.com' };
    sanitizePayload(obj);
    expect(obj['__email__class']).toBeUndefined();
  });

  it('restores default policy after reset', () => {
    setClassificationPolicy({
      PUBLIC: 'pass',
      INTERNAL: 'pass',
      PII: 'drop',
      PHI: 'drop',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    });
    resetClassificationForTests();
    expect(getClassificationPolicy().PII).toBe('redact');
  });
});

// ── Multiple registerClassificationRules calls accumulate ────────────────────

describe('accumulation', () => {
  it('multiple calls accumulate rules', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    registerClassificationRules([{ pattern: 'dob', classification: 'PHI' }]);
    expect(_classifyField('email', '')).toBe('PII');
    expect(_classifyField('dob', '')).toBe('PHI');
  });
});

// ── PUBLIC and SECRET labels ──────────────────────────────────────────────────

describe('all DataClass labels', () => {
  it('PUBLIC label', () => {
    registerClassificationRules([{ pattern: 'status', classification: 'PUBLIC' }]);
    expect(_classifyField('status', 'ok')).toBe('PUBLIC');
  });

  it('SECRET label', () => {
    registerClassificationRules([{ pattern: 'api_token', classification: 'SECRET' }]);
    expect(_classifyField('api_token', 'xyz')).toBe('SECRET');
  });
});

// ── Policy hook installation ──────────────────────────────────────────────────

describe('policy hook', () => {
  it('_policyHook is null before rules are registered', () => {
    expect(_policyHook).toBeNull();
  });

  it('_policyHook returns pass for an unknown label', () => {
    registerClassificationRules([]);
    // The hook is installed — call it with a label not in any DataClass.
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const action = _policyHook!('UNKNOWN_LABEL');
    expect(action).toBe('pass');
  });

  it('_policyHook is installed after registerClassificationRules', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    expect(_policyHook).not.toBeNull();
  });

  it('_policyHook is cleared by resetClassificationForTests', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    resetClassificationForTests();
    expect(_policyHook).toBeNull();
  });
});

// ── Policy action dispatch ────────────────────────────────────────────────────

describe('policy action: drop', () => {
  it('drop action removes the key entirely', () => {
    registerClassificationRules([{ pattern: 'dob', classification: 'PHI' }]);
    // PHI default = "drop"
    const obj: Record<string, unknown> = { dob: '1990-01-01', name: 'Alice' };
    sanitizePayload(obj);
    expect(obj['dob']).toBeUndefined();
    expect(obj['name']).toBe('Alice');
  });

  it('drop action: no __key__class tag for dropped key', () => {
    registerClassificationRules([{ pattern: 'dob', classification: 'PHI' }]);
    const obj: Record<string, unknown> = { dob: '1990-01-01' };
    sanitizePayload(obj);
    expect(obj['__dob__class']).toBeUndefined();
  });

  it('drop action via custom policy', () => {
    registerClassificationRules([{ pattern: 'name', classification: 'PII' }]);
    setClassificationPolicy({
      PUBLIC: 'pass',
      INTERNAL: 'pass',
      PII: 'drop',
      PHI: 'drop',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    });
    const obj: Record<string, unknown> = { name: 'Alice' };
    sanitizePayload(obj);
    expect(obj['name']).toBeUndefined();
    expect(obj['__name__class']).toBeUndefined();
  });
});

describe('policy action: redact', () => {
  it('redact action replaces value with *** and adds class tag', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    // PII default = "redact"
    const obj: Record<string, unknown> = { email: 'alice@example.com' };
    sanitizePayload(obj);
    expect(obj['email']).toBe('***');
    expect(obj['__email__class']).toBe('PII');
  });

  it('redact action via custom policy', () => {
    registerClassificationRules([{ pattern: 'dob', classification: 'PHI' }]);
    setClassificationPolicy({
      PUBLIC: 'pass',
      INTERNAL: 'pass',
      PII: 'redact',
      PHI: 'redact',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    });
    const obj: Record<string, unknown> = { dob: '1990-01-01' };
    sanitizePayload(obj);
    expect(obj['dob']).toBe('***');
    expect(obj['__dob__class']).toBe('PHI');
  });

  it('already-redacted value is not double-masked', () => {
    registerClassificationRules([{ pattern: 'email', classification: 'PII' }]);
    const obj: Record<string, unknown> = { email: '***' };
    sanitizePayload(obj);
    // Value stays *** (no double masking), class tag still added.
    expect(obj['email']).toBe('***');
    expect(obj['__email__class']).toBe('PII');
  });
});

describe('policy action: hash', () => {
  it('hash action replaces value with 12-char hex hash and adds class tag', () => {
    registerClassificationRules([{ pattern: 'card_num', classification: 'PCI' }]);
    // PCI default = "hash"
    const obj: Record<string, unknown> = { card_num: '4111111111111111' };
    sanitizePayload(obj);
    // Value should be a 12-char lowercase hex string.
    expect(typeof obj['card_num']).toBe('string');
    expect((obj['card_num'] as string).length).toBe(12);
    expect(/^[0-9a-f]{12}$/.test(obj['card_num'] as string)).toBe(true);
    expect(obj['__card_num__class']).toBe('PCI');
  });

  it('hash of the same value is deterministic', () => {
    registerClassificationRules([{ pattern: 'card_num', classification: 'PCI' }]);
    const obj1: Record<string, unknown> = { card_num: '4111111111111111' };
    const obj2: Record<string, unknown> = { card_num: '4111111111111111' };
    sanitizePayload(obj1);
    sanitizePayload(obj2);
    expect(obj1['card_num']).toBe(obj2['card_num']);
  });
});

describe('policy action: truncate', () => {
  it('truncate action shortens a long value and adds class tag', () => {
    registerClassificationRules([{ pattern: 'notes', classification: 'INTERNAL' }]);
    setClassificationPolicy({
      PUBLIC: 'pass',
      INTERNAL: 'truncate',
      PII: 'redact',
      PHI: 'drop',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    });
    const obj: Record<string, unknown> = { notes: 'abcdefghijklmnop' };
    sanitizePayload(obj);
    // Truncated to 8 chars + '...'
    expect(obj['notes']).toBe('abcdefgh...');
    expect(obj['__notes__class']).toBe('INTERNAL');
  });

  it('truncate action leaves short values unchanged', () => {
    registerClassificationRules([{ pattern: 'notes', classification: 'INTERNAL' }]);
    setClassificationPolicy({
      PUBLIC: 'pass',
      INTERNAL: 'truncate',
      PII: 'redact',
      PHI: 'drop',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    });
    const obj: Record<string, unknown> = { notes: 'short' };
    sanitizePayload(obj);
    expect(obj['notes']).toBe('short');
    expect(obj['__notes__class']).toBe('INTERNAL');
  });
});

describe('policy action: pass', () => {
  it('pass action leaves value unchanged but adds class tag', () => {
    registerClassificationRules([{ pattern: 'status', classification: 'PUBLIC' }]);
    // PUBLIC default = "pass"
    const obj: Record<string, unknown> = { status: 'ok' };
    sanitizePayload(obj);
    expect(obj['status']).toBe('ok');
    expect(obj['__status__class']).toBe('PUBLIC');
  });

  it('unknown action falls back to pass: value unchanged, tag added', () => {
    registerClassificationRules([{ pattern: 'foo', classification: 'PUBLIC' }]);
    setClassificationPolicy({
      PUBLIC: 'unknown_action',
      INTERNAL: 'pass',
      PII: 'redact',
      PHI: 'drop',
      PCI: 'hash',
      SECRET: 'drop', // pragma: allowlist secret
    });
    const obj: Record<string, unknown> = { foo: 'bar' };
    sanitizePayload(obj);
    expect(obj['foo']).toBe('bar');
    expect(obj['__foo__class']).toBe('PUBLIC');
  });
});

// ── Strippable governance: no classification module ───────────────────────────

describe('strippable governance', () => {
  it('sanitizePayload works correctly when no classification rules are registered', () => {
    // No registerClassificationRules call — hooks stay null.
    const obj: Record<string, unknown> = { email: 'alice@example.com', name: 'Alice' };
    sanitizePayload(obj);
    // email is in DEFAULT_SANITIZE_FIELDS? No — email is intentionally excluded.
    // No class tags should appear.
    expect(Object.keys(obj).some((k) => k.endsWith('__class'))).toBe(false);
  });

  it('sanitizePayload default redaction still works without classification module', () => {
    const obj: Record<string, unknown> = { password: 'hunter2', name: 'Alice' }; // pragma: allowlist secret
    sanitizePayload(obj);
    // password is in DEFAULT_SANITIZE_FIELDS — should be redacted.
    expect(obj['password']).toBe('***');
    // No class tags.
    expect(Object.keys(obj).some((k) => k.endsWith('__class'))).toBe(false);
  });
});
