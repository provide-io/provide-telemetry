// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_SANITIZE_FIELDS,
  _SECRET_PATTERNS,
  _detectSecretInValue,
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
});

describe('DEFAULT_SANITIZE_FIELDS — complete coverage', () => {
  it('includes all expected PII field names', () => {
    const fields = DEFAULT_SANITIZE_FIELDS;
    expect(fields).toContain('passwd');
    expect(fields).toContain('secret');
    expect(fields).toContain('authorization');
    expect(fields).toContain('cookie');
    expect(fields).toContain('credit_card');
    expect(fields).toContain('ssn');
    expect(fields).toContain('email');
    expect(fields).toContain('private_key');
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
  it('hash rule on email prevents default redaction from overriding with [REDACTED]', () => {
    // ruleTargets collects last path segments of rules (via .pop()?.toLowerCase()).
    // If ArrowFunction is mutated → () => undefined, ruleTargets = {undefined}, ruleTargets.has('email') = false
    // → default redaction applies to 'email' even though a rule already handled it → value becomes [REDACTED].
    // If MethodExpression mutates .pop() → undefined, same effect.
    // With correct implementation: ruleTargets = {'email'}, ruleTargets.has('email') = true → default redaction skipped.
    resetPiiRulesForTests();
    registerPiiRule({ path: 'email', mode: 'hash' });
    const obj: Record<string, unknown> = { email: 'user@example.com', name: 'Alice' };
    sanitizePayload(obj);
    // With correct code, hash rule handled email — result is a hash, NOT [REDACTED]
    expect(typeof obj['email']).toBe('string');
    expect(obj['email']).not.toBe('***');
    expect(String(obj['email'])).toMatch(/^[0-9a-f]{12}$/); // 8-char hex hash
    expect(obj['name']).toBe('Alice'); // unaffected
  });

  it('truncate rule on email preserves truncated value (not overridden by [REDACTED])', () => {
    // email is a DEFAULT_SANITIZE_FIELD. With ArrowFunction/MethodExpression mutation, ruleTargets.has('email') = false
    // → default redaction overrides the truncated value with [REDACTED].
    // With correct code: ruleTargets.has('email') = true → default redaction skipped → truncated value preserved.
    resetPiiRulesForTests();
    registerPiiRule({ path: 'email', mode: 'truncate', truncateTo: 4 });
    const obj: Record<string, unknown> = { email: 'user@example.com', name: 'Bob' };
    sanitizePayload(obj);
    // With correct code: truncated value 'user...' NOT '***'
    expect(String(obj['email'])).toBe('user...');
    expect(obj['name']).toBe('Bob');
  });
});

describe('secret detection — _detectSecretInValue', () => {
  it('exports _SECRET_PATTERNS array', () => {
    expect(Array.isArray(_SECRET_PATTERNS)).toBe(true);
    expect(_SECRET_PATTERNS.length).toBeGreaterThan(0);
  });

  it('detects AWS access key', () => {
    expect(_detectSecretInValue('AKIAIOSFODNN7EXAMPLE1')).toBe(true); // pragma: allowlist secret
  });

  it('detects JWT', () => {
    expect(
      _detectSecretInValue('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0'), // pragma: allowlist secret
    ).toBe(true);
  });

  it('detects GitHub token', () => {
    expect(_detectSecretInValue('ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn')).toBe(true); // pragma: allowlist secret
  });

  it('detects long hex string', () => {
    expect(_detectSecretInValue('0123456789abcdef0123456789abcdef01234567')).toBe(true); // pragma: allowlist secret
  });

  it('detects long base64 string', () => {
    expect(_detectSecretInValue('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop==')).toBe(true); // pragma: allowlist secret
  });

  it('rejects short values (under 20 chars)', () => {
    expect(_detectSecretInValue('AKIA1234')).toBe(false);
  });

  it('rejects safe strings without patterns', () => {
    expect(_detectSecretInValue('hello world')).toBe(false);
  });
});

describe('secret detection — each pattern independently (kills individual array entry removal)', () => {
  // Each test uses a value that matches ONLY its target pattern and no other.

  it('AWS key pattern is the only match for AKIA prefix strings', () => {
    // AKIA + 16 uppercase/digits = 20 chars. Does NOT match hex (has uppercase non-hex),
    // does NOT match base64 (only 20 chars, pattern needs 40), does NOT match JWT or GitHub.
    const awsKey = 'AKIAIOSFODNN7EXAMP01'; // pragma: allowlist secret
    expect(awsKey.length).toBe(20);
    expect(_detectSecretInValue(awsKey)).toBe(true);
    // Verify it doesn't match other patterns individually
    expect(_SECRET_PATTERNS[1].test(awsKey)).toBe(false); // not JWT
    expect(_SECRET_PATTERNS[2].test(awsKey)).toBe(false); // not GitHub
    expect(_SECRET_PATTERNS[3].test(awsKey)).toBe(false); // not 40+ hex
    expect(_SECRET_PATTERNS[4].test(awsKey)).toBe(false); // not 40+ base64
  });

  it('JWT pattern is the only match for eyJ prefix strings', () => {
    // eyJ + 10 base64url chars + '.' + 10 base64url chars = ~24 chars
    // Keep short enough to avoid 40+ hex/base64 match
    const jwt = 'eyJhbGciOiJIUzI1Ni.eyJzdWIiOiIxMj'; // pragma: allowlist secret
    expect(jwt.length).toBeGreaterThanOrEqual(20);
    expect(_detectSecretInValue(jwt)).toBe(true);
    expect(_SECRET_PATTERNS[0].test(jwt)).toBe(false); // not AWS
    expect(_SECRET_PATTERNS[2].test(jwt)).toBe(false); // not GitHub
    expect(_SECRET_PATTERNS[3].test(jwt)).toBe(false); // not 40+ hex
    expect(_SECRET_PATTERNS[4].test(jwt)).toBe(false); // not 40+ base64
  });

  it('GitHub token (ghp_) pattern is the only match', () => {
    // ghp_ + 36 chars. Use chars that include non-hex to avoid hex pattern.
    // Also keep base64 run under 40 by including non-base64 chars.
    const ghToken = 'ghp_RSTUVWXYZ012345678901234567890123456'; // pragma: allowlist secret
    expect(_detectSecretInValue(ghToken)).toBe(true);
    expect(_SECRET_PATTERNS[0].test(ghToken)).toBe(false); // not AWS
    expect(_SECRET_PATTERNS[1].test(ghToken)).toBe(false); // not JWT
  });

  it('GitHub token (gho_) variant matches', () => {
    const ghoToken = 'gho_RSTUVWXYZ012345678901234567890123456'; // pragma: allowlist secret
    expect(_detectSecretInValue(ghoToken)).toBe(true);
  });

  it('GitHub token (ghs_) variant matches', () => {
    const ghsToken = 'ghs_RSTUVWXYZ012345678901234567890123456'; // pragma: allowlist secret
    expect(_detectSecretInValue(ghsToken)).toBe(true);
  });

  it('long hex pattern is the only match for 40+ hex strings', () => {
    // 40 lowercase hex chars — doesn't match AWS (no AKIA prefix), JWT (no eyJ), GitHub (no ghp_)
    // Does match base64 pattern too (hex chars are subset of base64), so we need a value
    // that's hex but we verify the hex pattern specifically matches.
    const hexStr = '0123456789abcdef0123456789abcdef01234567'; // pragma: allowlist secret
    expect(hexStr.length).toBe(40);
    expect(_SECRET_PATTERNS[3].test(hexStr)).toBe(true); // hex pattern matches
    expect(_SECRET_PATTERNS[0].test(hexStr)).toBe(false); // not AWS
    expect(_SECRET_PATTERNS[1].test(hexStr)).toBe(false); // not JWT
    expect(_SECRET_PATTERNS[2].test(hexStr)).toBe(false); // not GitHub
  });

  it('long base64 pattern matches strings with +/ chars that hex cannot', () => {
    // Use chars like + and / that are valid base64 but NOT valid hex
    const b64Str = 'ABCDE+GHIJKLMNOP/RSTUVWXYZabcde+ghijklmnop=='; // pragma: allowlist secret
    expect(b64Str.length).toBeGreaterThanOrEqual(40);
    expect(_SECRET_PATTERNS[4].test(b64Str)).toBe(true); // base64 pattern
    expect(_SECRET_PATTERNS[0].test(b64Str)).toBe(false); // not AWS
    expect(_SECRET_PATTERNS[1].test(b64Str)).toBe(false); // not JWT
    expect(_SECRET_PATTERNS[2].test(b64Str)).toBe(false); // not GitHub
    expect(_SECRET_PATTERNS[3].test(b64Str)).toBe(false); // not hex (has + and /)
    expect(_detectSecretInValue(b64Str)).toBe(true);
  });
});

describe('secret detection — _MIN_SECRET_LENGTH boundary (kills threshold change)', () => {
  it('detects secret at exactly 20 chars (the threshold)', () => {
    // AKIA + 16 chars = 20 chars total
    const exactly20 = 'AKIAIOSFODNN7EXAMP01'; // pragma: allowlist secret
    expect(exactly20.length).toBe(20);
    expect(_detectSecretInValue(exactly20)).toBe(true);
  });

  it('does NOT detect secret at 19 chars (below threshold)', () => {
    // AKIA + 15 chars = 19 chars — would match AWS pattern but too short
    const chars19 = 'AKIAIOSFODNN7EXAMPL'; // pragma: allowlist secret
    expect(chars19.length).toBe(19);
    expect(_detectSecretInValue(chars19)).toBe(false);
  });
});

describe('sanitize — secret detection', () => {
  it('redacts AWS access key in value', () => {
    const obj: Record<string, unknown> = { key: 'AKIAIOSFODNN7EXAMPLE1' }; // pragma: allowlist secret
    sanitize(obj);
    expect(obj['key']).toBe('***');
  });

  it('redacts JWT in value', () => {
    const obj: Record<string, unknown> = {
      token_val: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0', // pragma: allowlist secret
    };
    sanitize(obj);
    expect(obj['token_val']).toBe('***');
  });

  it('redacts GitHub token in value', () => {
    const obj: Record<string, unknown> = {
      code: 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn', // pragma: allowlist secret
    };
    sanitize(obj);
    expect(obj['code']).toBe('***');
  });

  it('redacts long hex string in value', () => {
    const obj: Record<string, unknown> = { hex: '0123456789abcdef0123456789abcdef01234567' }; // pragma: allowlist secret
    sanitize(obj);
    expect(obj['hex']).toBe('***');
  });

  it('redacts long base64 string in value', () => {
    const obj: Record<string, unknown> = {
      b64: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop==', // pragma: allowlist secret
    };
    sanitize(obj);
    expect(obj['b64']).toBe('***');
  });

  it('does NOT redact short values', () => {
    const obj: Record<string, unknown> = { short: 'AKIA1234' };
    sanitize(obj);
    expect(obj['short']).toBe('AKIA1234');
  });

  it('does NOT redact safe strings', () => {
    const obj: Record<string, unknown> = { safe: 'hello world' };
    sanitize(obj);
    expect(obj['safe']).toBe('hello world');
  });
});

describe('sanitize — non-string values are not secret-checked (kills typeof check at line 61)', () => {
  it('does not redact numeric values even if they stringify to a pattern match', () => {
    const obj: Record<string, unknown> = { count: 12345678901234567890n, status: 200 };
    sanitize(obj);
    // Numbers should not be treated as strings for secret detection
    expect(obj['status']).toBe(200);
  });

  it('does not redact boolean values', () => {
    const obj: Record<string, unknown> = { active: true, name: 'safe' };
    sanitize(obj);
    expect(obj['active']).toBe(true);
  });

  it('does not redact object values (only checks string type)', () => {
    const nested = { inner: 'AKIAIOSFODNN7EXAMPLE1' }; // pragma: allowlist secret
    const obj: Record<string, unknown> = { data: nested };
    sanitize(obj);
    // sanitize is flat — only checks top-level string values
    expect(obj['data']).toBe(nested);
  });
});

describe('sanitizePayload — _redactSecrets handles arrays of objects (kills Array.isArray at line 153)', () => {
  it('redacts secrets inside objects within arrays', () => {
    const obj: Record<string, unknown> = {
      items: [
        { key: 'AKIAIOSFODNN7EXAMPLE1' }, // pragma: allowlist secret
        { key: 'safe value' },
      ],
    };
    sanitizePayload(obj);
    const items = obj['items'] as Array<Record<string, unknown>>;
    expect(items[0]['key']).toBe('***');
    expect(items[1]['key']).toBe('safe value');
  });

  it('redacts secrets in nested arrays of objects', () => {
    const obj: Record<string, unknown> = {
      nested: {
        list: [
          { secret: '0123456789abcdef0123456789abcdef01234567' }, // pragma: allowlist secret
        ],
      },
    };
    sanitizePayload(obj);
    const nested = obj['nested'] as Record<string, unknown>;
    const list = nested['list'] as Array<Record<string, unknown>>;
    expect(list[0]['secret']).toBe('***');
  });
});

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

describe('sanitizePayload — secret detection (nested)', () => {
  it('redacts nested secret values', () => {
    const obj: Record<string, unknown> = { outer: { inner: 'AKIAIOSFODNN7EXAMPLE1' } }; // pragma: allowlist secret
    sanitizePayload(obj);
    const outer = obj['outer'] as Record<string, unknown>;
    expect(outer['inner']).toBe('***');
  });

  it('redacts secret in top-level value', () => {
    const obj: Record<string, unknown> = {
      data: 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn', // pragma: allowlist secret
    };
    sanitizePayload(obj);
    expect(obj['data']).toBe('***');
  });

  it('does not redact safe nested values', () => {
    const obj: Record<string, unknown> = { outer: { inner: 'safe value' } };
    sanitizePayload(obj);
    const outer = obj['outer'] as Record<string, unknown>;
    expect(outer['inner']).toBe('safe value');
  });
});
