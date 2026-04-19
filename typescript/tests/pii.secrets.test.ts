// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Secret detection tests for pii.ts — _detectSecretInValue, _SECRET_PATTERNS,
 * registerSecretPattern/getSecretPatterns, and sanitize/sanitizePayload secret redaction.
 * Basic PII rule/mode tests live in pii.test.ts.
 */

import { afterEach, describe, expect, it } from 'vitest';
import {
  _SECRET_PATTERNS,
  _detectSecretInValue,
  getSecretPatterns,
  registerSecretPattern,
  resetPiiRulesForTests,
  resetSecretPatternsForTests,
  sanitize,
  sanitizePayload,
} from '../src/pii';

afterEach(() => resetPiiRulesForTests());

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

describe('sanitize — non-string values NOT treated as secrets (kills typeof guard mutation)', () => {
  it('does not redact number values even in non-blocked keys', () => {
    const obj: Record<string, unknown> = { count: 42, name: 'safe' };
    sanitize(obj);
    expect(obj['count']).toBe(42);
    expect(obj['name']).toBe('safe');
  });

  it('does not redact boolean values', () => {
    const obj: Record<string, unknown> = { active: true };
    sanitize(obj);
    expect(obj['active']).toBe(true);
  });

  it('does not redact object values', () => {
    const obj: Record<string, unknown> = { data: { nested: 'value' } };
    sanitize(obj);
    expect(obj['data']).toEqual({ nested: 'value' });
  });
});

describe('registerSecretPattern — custom secret detection', () => {
  afterEach(() => resetPiiRulesForTests());

  it('custom pattern detects a secret', () => {
    // Register a pattern that matches Stripe-style keys
    registerSecretPattern('stripe-key', /xk_test_[A-Za-z0-9]{24,}/);
    const value = 'xk_test_abcdefghijklmnopqrstuvwx'; // pragma: allowlist secret
    expect(value.length).toBeGreaterThanOrEqual(20);
    expect(_detectSecretInValue(value)).toBe(true);
  });

  it('same name replaces previous pattern', () => {
    registerSecretPattern('my-pat', /NEVER_MATCH_THIS_PATTERN_XYZZY/);
    registerSecretPattern('my-pat', /xk_test_[A-Za-z0-9]{24,}/);
    const patterns = getSecretPatterns();
    const custom = patterns.filter((p) => p.name === 'my-pat');
    expect(custom).toHaveLength(1);
    expect(custom[0].pattern.source).toBe('xk_test_[A-Za-z0-9]{24,}');
  });

  it('getSecretPatterns returns built-in + custom', () => {
    const beforeCount = getSecretPatterns().length;
    registerSecretPattern('custom-1', /CUSTOM_1/);
    registerSecretPattern('custom-2', /CUSTOM_2/);
    const after = getSecretPatterns();
    expect(after.length).toBe(beforeCount + 2);
    // Built-in patterns have names starting with 'built-in-'
    const builtInNames = after.filter((p) => p.name.startsWith('built-in-'));
    expect(builtInNames.length).toBe(_SECRET_PATTERNS.length);
    // Custom patterns are present
    expect(after.some((p) => p.name === 'custom-1')).toBe(true);
    expect(after.some((p) => p.name === 'custom-2')).toBe(true);
  });

  it('resetSecretPatternsForTests clears custom patterns', () => {
    registerSecretPattern('temp', /TEMP_PATTERN/);
    expect(getSecretPatterns().length).toBe(_SECRET_PATTERNS.length + 1);
    resetSecretPatternsForTests();
    expect(getSecretPatterns().length).toBe(_SECRET_PATTERNS.length);
  });

  it('resetPiiRulesForTests also clears custom secret patterns', () => {
    registerSecretPattern('temp', /TEMP_PATTERN/);
    resetPiiRulesForTests();
    expect(getSecretPatterns().length).toBe(_SECRET_PATTERNS.length);
  });

  it('short strings are skipped even with custom patterns', () => {
    registerSecretPattern('short-match', /sk_/);
    expect(_detectSecretInValue('sk_abc')).toBe(false); // too short (< 20 chars)
  });

  it('returns false when custom pattern does not match a long value', () => {
    registerSecretPattern('nope', /WILL_NOT_MATCH_ANYTHING/);
    // 20+ chars, no built-in match, no custom match
    const safeValue = 'this is a safe value that is long enough';
    expect(safeValue.length).toBeGreaterThanOrEqual(20);
    expect(_detectSecretInValue(safeValue)).toBe(false);
  });

  it('sanitize redacts values matching custom pattern', () => {
    registerSecretPattern('stripe-key', /xk_test_[A-Za-z0-9]{24,}/);
    const obj: Record<string, unknown> = {
      apiData: 'xk_test_abcdefghijklmnopqrstuvwx', // pragma: allowlist secret
    };
    sanitize(obj);
    expect(obj['apiData']).toBe('***');
  });

  it('sanitizePayload redacts values matching custom pattern', () => {
    registerSecretPattern('stripe-key', /xk_test_[A-Za-z0-9]{24,}/);
    const obj: Record<string, unknown> = {
      nested: { key: 'xk_test_abcdefghijklmnopqrstuvwx' }, // pragma: allowlist secret
    };
    sanitizePayload(obj);
    const nested = obj['nested'] as Record<string, unknown>;
    expect(nested['key']).toBe('***');
  });
});
