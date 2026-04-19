// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_SANITIZE_FIELDS,
  _setHashFnForTest,
  getPiiRules,
  registerPiiRule,
  replacePiiRules,
  resetPiiRulesForTests,
  sanitize,
  sanitizePayload,
} from '../src/pii';

afterEach(() => resetPiiRulesForTests());

describe('sanitize (backwards-compat)', () => {
  it('redacts default PII fields', () => {
    const obj: Record<string, unknown> = { password: 'secret', status: 200 };
    sanitize(obj);
    expect(obj['password']).toBe('***');
    expect(obj['status']).toBe(200);
  });

  it('redacts extra fields', () => {
    const obj: Record<string, unknown> = { my_field: 'val', other: 'ok' };
    sanitize(obj, ['my_field']);
    expect(obj['my_field']).toBe('***');
    expect(obj['other']).toBe('ok');
  });

  it('is case-insensitive', () => {
    const obj: Record<string, unknown> = { PASSWORD: 'x', Token: 'y' };
    sanitize(obj);
    expect(obj['PASSWORD']).toBe('***');
    expect(obj['Token']).toBe('***');
  });

  it('DEFAULT_SANITIZE_FIELDS includes standard keys', () => {
    expect(DEFAULT_SANITIZE_FIELDS).toContain('password');
    expect(DEFAULT_SANITIZE_FIELDS).toContain('token');
    expect(DEFAULT_SANITIZE_FIELDS).toContain('api_key');
  });
});

describe('PIIRule registry', () => {
  it('starts empty', () => {
    expect(getPiiRules()).toHaveLength(0);
  });

  it('registerPiiRule appends', () => {
    registerPiiRule({ path: 'user.email', mode: 'redact' });
    expect(getPiiRules()).toHaveLength(1);
    expect(getPiiRules()[0].path).toBe('user.email');
  });

  it('replacePiiRules replaces all', () => {
    registerPiiRule({ path: 'a', mode: 'drop' });
    replacePiiRules([{ path: 'b', mode: 'hash' }]);
    expect(getPiiRules()).toHaveLength(1);
    expect(getPiiRules()[0].path).toBe('b');
  });

  it('getPiiRules returns a copy', () => {
    registerPiiRule({ path: 'x', mode: 'redact' });
    const copy = getPiiRules();
    copy.push({ path: 'y', mode: 'drop' });
    expect(getPiiRules()).toHaveLength(1);
  });
});

describe('sanitizePayload — redact mode', () => {
  it('redacts a matching top-level key', () => {
    registerPiiRule({ path: 'secret', mode: 'redact' });
    const obj: Record<string, unknown> = { secret: 'abc', keep: 'me' };
    sanitizePayload(obj);
    expect(obj['secret']).toBe('***');
    expect(obj['keep']).toBe('me');
  });
});

describe('sanitizePayload — drop mode', () => {
  it('removes the key', () => {
    registerPiiRule({ path: 'token', mode: 'drop' });
    const obj: Record<string, unknown> = { token: 'jwt', other: 1 };
    sanitizePayload(obj);
    expect('token' in obj).toBe(false);
    expect(obj['other']).toBe(1);
  });
});

describe('sanitizePayload — truncate mode', () => {
  it('truncates to truncateTo chars + "..."', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 'hello world' };
    sanitizePayload(obj);
    expect(obj['note']).toBe('hello...');
  });

  it('does not truncate short values', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 20 });
    const obj: Record<string, unknown> = { note: 'hi' };
    sanitizePayload(obj);
    expect(obj['note']).toBe('hi');
  });

  it('uses default truncateTo=8 when not specified', () => {
    registerPiiRule({ path: 'note', mode: 'truncate' });
    const obj: Record<string, unknown> = { note: 'hello world 123456789' };
    sanitizePayload(obj);
    expect(String(obj['note'])).toMatch(/^.{8}\.\.\.$/);
  });
});

describe('sanitizePayload — hash mode', () => {
  it('hashes the value to a hex string', () => {
    registerPiiRule({ path: 'id', mode: 'hash' });
    const obj: Record<string, unknown> = { id: 'user-123' };
    sanitizePayload(obj);
    expect(typeof obj['id']).toBe('string');
    expect(String(obj['id'])).toMatch(/^[0-9a-f]{12}$/);
  });

  it('is deterministic — same input → same output', () => {
    registerPiiRule({ path: 'id', mode: 'hash' });
    const obj1: Record<string, unknown> = { id: 'user-abc' };
    const obj2: Record<string, unknown> = { id: 'user-abc' };
    sanitizePayload(obj1);
    sanitizePayload(obj2);
    expect(obj1['id']).toBe(obj2['id']);
  });

  it('falls back to [HASHED] when crypto is unavailable', () => {
    _setHashFnForTest(() => {
      throw new Error('no crypto');
    });
    registerPiiRule({ path: 'id', mode: 'hash' });
    const obj: Record<string, unknown> = { id: 'user-123' };
    sanitizePayload(obj);
    expect(obj['id']).toBe('***');
  });
});

describe('sanitizePayload — array values', () => {
  it('applies rules recursively to array items using wildcard path', () => {
    // Rule: 'items.*.id' targets the 'id' field inside each array element of 'items'
    registerPiiRule({ path: 'items.*.id', mode: 'drop' });
    const obj: Record<string, unknown> = {
      items: [
        { id: 'u1', name: 'Alice' },
        { id: 'u2', name: 'Bob' },
      ],
    };
    sanitizePayload(obj);
    const items = obj['items'] as Array<Record<string, unknown>>;
    expect('id' in items[0]).toBe(false);
    expect('id' in items[1]).toBe(false);
    expect(items[0]['name']).toBe('Alice');
    expect(items[1]['name']).toBe('Bob');
  });
});

describe('sanitizePayload — default sensitive keys', () => {
  it('redacts default sensitive keys even without a rule', () => {
    const obj: Record<string, unknown> = { password: 'secret', name: 'Alice' };
    sanitizePayload(obj);
    expect(obj['password']).toBe('***');
    expect(obj['name']).toBe('Alice');
  });

  it('extraFields parameter also gets redacted', () => {
    const obj: Record<string, unknown> = { ssn: '123', custom: 'val' };
    sanitizePayload(obj, ['custom']);
    expect(obj['ssn']).toBe('***');
    expect(obj['custom']).toBe('***');
  });

  it('does not double-redact keys already handled by a rule', () => {
    registerPiiRule({ path: 'token', mode: 'drop' });
    const obj: Record<string, unknown> = { token: 'jwt', other: 1 };
    sanitizePayload(obj);
    expect('token' in obj).toBe(false); // rule says drop
  });

  it('uses exact-match default key detection instead of substring matching', () => {
    const obj: Record<string, unknown> = {
      author_id: 'safe-author',
      spinning_wheel: 'safe-spin',
      glassness: 'safe-word',
    };
    sanitizePayload(obj);
    expect(obj['author_id']).toBe('safe-author');
    expect(obj['spinning_wheel']).toBe('safe-spin');
    expect(obj['glassness']).toBe('safe-word');
  });
});

describe('DEFAULT_SANITIZE_FIELDS — complete coverage', () => {
  it('includes all expected PII field names (canonical 17-key list)', () => {
    const fields = DEFAULT_SANITIZE_FIELDS;
    expect(fields).toContain('passwd');
    expect(fields).toContain('secret');
    expect(fields).toContain('authorization');
    expect(fields).toContain('cookie');
    expect(fields).toContain('credit_card');
    expect(fields).toContain('ssn');
    expect(fields).toContain('private_key');
    // New keys in the canonical list
    expect(fields).toContain('credential');
    expect(fields).toContain('cvv');
    expect(fields).toContain('pin');
    expect(fields).toContain('account_number');
    expect(fields).toContain('apikey');
    expect(fields).toContain('creditcard');
    expect(fields).toContain('auth');
    // email is intentionally NOT in the default list
    expect(fields).not.toContain('email');
  });
});

describe('sanitizePayload — truncate boundary', () => {
  it('does NOT truncate when value length equals truncateTo exactly', () => {
    // text.length > limit (not >=): value of exactly truncateTo chars should be preserved
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 'hello' }; // length=5 == truncateTo=5
    sanitizePayload(obj);
    expect(obj['note']).toBe('hello'); // not 'hello...'
  });

  it('truncates when value length is one more than truncateTo', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 'hello!' }; // length=6 > truncateTo=5
    sanitizePayload(obj);
    expect(obj['note']).toBe('hello...');
  });
});

describe('sanitizePayload — wildcard on object keys', () => {
  it('applies rule to object field matched by wildcard segment', () => {
    // Rule 'users.*.email' should match object like { users: { alice: { email: '...' } } }
    registerPiiRule({ path: 'users.*.email', mode: 'redact' });
    const obj: Record<string, unknown> = {
      users: {
        alice: { email: 'alice@example.com', role: 'admin' },
        bob: { email: 'bob@example.com', role: 'user' },
      },
    };
    sanitizePayload(obj);
    const users = obj['users'] as Record<string, Record<string, unknown>>;
    expect(users['alice']['email']).toBe('***');
    expect(users['bob']['email']).toBe('***');
    expect(users['alice']['role']).toBe('admin'); // unaffected
  });
});

describe('pii — null node passthrough (kills ConditionalExpression on node===null)', () => {
  it('sanitizePayload with null nested value does not throw', () => {
    registerPiiRule({ path: 'user.email', mode: 'redact' });
    const obj: Record<string, unknown> = { user: null };
    expect(() => sanitizePayload(obj)).not.toThrow();
    expect(obj['user']).toBeNull();
  });

  it('sanitizePayload with primitive nested value does not throw', () => {
    registerPiiRule({ path: 'meta.token', mode: 'redact' });
    const obj: Record<string, unknown> = { meta: 42 };
    expect(() => sanitizePayload(obj)).not.toThrow();
    expect(obj['meta']).toBe(42);
  });
});

describe('pii — ruleTargets optimization (kills OptionalChaining + MethodExpression)', () => {
  it('does not redact fields not matching any rule leaf', () => {
    resetPiiRulesForTests();
    registerPiiRule({ path: 'user.email', mode: 'redact' });
    const obj: Record<string, unknown> = { unrelated: 'value', other_field: 'data' };
    sanitizePayload(obj);
    expect(obj['unrelated']).toBe('value');
    expect(obj['other_field']).toBe('data');
  });

  it('only applies rule for the matching leaf path segment', () => {
    resetPiiRulesForTests();
    registerPiiRule({ path: 'a.b.secret', mode: 'redact' });
    const obj: Record<string, unknown> = {
      a: { b: { secret: 'hidden', other: 'visible' } },
    };
    sanitizePayload(obj);
    const aObj = obj['a'] as Record<string, unknown>;
    const bObj = aObj['b'] as Record<string, unknown>;
    expect(bObj['secret']).toBe('***');
    expect(bObj['other']).toBe('visible');
  });
});

describe('pii — ruleTargets dedup guard (kills ArrowFunction + MethodExpression at pii.ts:178)', () => {
  it('hash rule on password prevents default redaction from overriding with [REDACTED]', () => {
    // ruleTargets collects last path segments of rules (via .pop()?.toLowerCase()).
    // If ArrowFunction is mutated → () => undefined, ruleTargets = {undefined}, ruleTargets.has('password') = false
    // → default redaction applies to 'password' even though a rule already handled it → value becomes [REDACTED].
    // If MethodExpression mutates .pop() → undefined, same effect.
    // With correct implementation: ruleTargets = {'password'}, ruleTargets.has('password') = true → default redaction skipped.
    resetPiiRulesForTests();
    registerPiiRule({ path: 'password', mode: 'hash' });
    const obj: Record<string, unknown> = { password: 'hunter2', name: 'Alice' }; // pragma: allowlist secret
    sanitizePayload(obj);
    // With correct code, hash rule handled password — result is a hash, NOT [REDACTED]
    expect(typeof obj['password']).toBe('string');
    expect(obj['password']).not.toBe('***');
    expect(String(obj['password'])).toMatch(/^[0-9a-f]{12}$/); // 12-char hex hash
    expect(obj['name']).toBe('Alice'); // unaffected
  });

  it('truncate rule on password preserves truncated value (not overridden by [REDACTED])', () => {
    // password is a DEFAULT_SANITIZE_FIELD. With ArrowFunction/MethodExpression mutation, ruleTargets.has('password') = false
    // → default redaction overrides the truncated value with [REDACTED].
    // With correct code: ruleTargets.has('password') = true → default redaction skipped → truncated value preserved.
    resetPiiRulesForTests();
    registerPiiRule({ path: 'password', mode: 'truncate', truncateTo: 4 });
    const obj: Record<string, unknown> = { password: 'hunter2', name: 'Bob' }; // pragma: allowlist secret
    sanitizePayload(obj);
    // With correct code: truncated value 'hunt...' NOT '***'
    expect(String(obj['password'])).toBe('hunt...');
    expect(obj['name']).toBe('Bob');
  });
});

// Secret detection tests (_detectSecretInValue, _SECRET_PATTERNS, registerSecretPattern) live in pii.secrets.test.ts

describe('sanitizePayload — obj key update from transformed result (kills line 225)', () => {
  it('updates original obj keys from rule-transformed result', () => {
    registerPiiRule({ path: 'data', mode: 'redact' });
    const obj: Record<string, unknown> = { data: 'secret', name: 'Alice' };
    sanitizePayload(obj);
    expect(obj['data']).toBe('***');
    expect(obj['name']).toBe('Alice');
  });

  it('deletes keys from original obj when rule drops them', () => {
    registerPiiRule({ path: 'remove_me', mode: 'drop' });
    const obj: Record<string, unknown> = { remove_me: 'gone', keep: 'here' };
    sanitizePayload(obj);
    expect('remove_me' in obj).toBe(false);
    expect(obj['keep']).toBe('here');
  });
});

describe('_applyRuleFull — depth limit (kills line 173 depth >= maxDepth branch)', () => {
  afterEach(() => resetPiiRulesForTests());

  it('stops recursing at maxDepth and leaves nested value unredacted', () => {
    registerPiiRule({ path: 'a.b.email', mode: 'redact' });
    const obj: Record<string, unknown> = { a: { b: { email: 'alice@example.com' } } };
    // maxDepth=1: _applyRuleFull reaches depth=1 at 'a' dict and returns without traversing further
    sanitizePayload(obj, [], { maxDepth: 1 });
    // The email is NOT redacted because depth limit was hit before the rule path matched
    const a = obj['a'] as Record<string, unknown>;
    const b = a['b'] as Record<string, unknown>;
    expect(b['email']).toBe('alice@example.com');
  });
});
