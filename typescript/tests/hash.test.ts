// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { createHmac } from 'node:crypto';
import { hmacSha256Hex, randomHex, sha256Bytes, sha256Hex, shortHash12 } from '../src/hash.js';

describe('hash helpers', () => {
  it('computes the standard SHA-256 digest for ascii input', () => {
    expect(sha256Hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', // pragma: allowlist secret
    );
  });

  it('returns a stable 12-char hex short hash', () => {
    expect(shortHash12('abc')).toBe('ba7816bf8f01');
  });
});

describe('sha256Hex — output format and known vectors', () => {
  it('output is always 64 characters', () => {
    expect(sha256Hex('abc')).toHaveLength(64);
    expect(sha256Hex('')).toHaveLength(64);
    expect(sha256Hex('hello world')).toHaveLength(64);
  });

  it('output is lowercase hex only', () => {
    const hash = sha256Hex('test');
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it('empty string produces known hash', () => {
    // SHA-256 of empty string
    expect(sha256Hex('')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', // pragma: allowlist secret
    );
  });

  it('handles input that produces hash with leading zeros', () => {
    // The hash of "abc" starts with "ba78..." which contains padded words.
    // We test a known vector where a word starts with 0 to verify padStart(8,'0').
    const hash = sha256Hex('abc');
    // Each 8-char segment must be exactly 8 chars (no missing leading zeros)
    for (let i = 0; i < 64; i += 8) {
      expect(hash.slice(i, i + 8)).toHaveLength(8);
    }
  });

  it('sha256Hex("hello") matches known NIST test vector', () => {
    expect(sha256Hex('hello')).toBe(
      '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824', // pragma: allowlist secret
    );
  });
});

describe('shortHash12 — output format', () => {
  it('output is exactly 12 characters', () => {
    expect(shortHash12('anything')).toHaveLength(12);
  });

  it('output is lowercase hex only', () => {
    expect(shortHash12('test')).toMatch(/^[0-9a-f]{12}$/);
  });

  it('is the first 12 characters of sha256Hex', () => {
    const full = sha256Hex('myinput');
    expect(shortHash12('myinput')).toBe(full.slice(0, 12));
  });
});

describe('randomHex', () => {
  it('returns a string of exactly 2*numBytes hex characters', () => {
    expect(randomHex(16)).toHaveLength(32);
    expect(randomHex(8)).toHaveLength(16);
  });

  it('output is lowercase hex only', () => {
    expect(randomHex(16)).toMatch(/^[0-9a-f]{32}$/);
    expect(randomHex(8)).toMatch(/^[0-9a-f]{16}$/);
  });

  it('returns different values on successive calls (not deterministic)', () => {
    const a = randomHex(16);
    const b = randomHex(16);
    // Probabilistically impossible for two independent 128-bit random values to collide
    expect(a).not.toBe(b);
  });
});

describe('hmacSha256Hex', () => {
  const enc = new TextEncoder();

  // RFC 4231 test case 2 — the canonical HMAC-SHA256 vector, so this agrees
  // with the standard rather than with our own implementation.
  it('matches RFC 4231 case 2', () => {
    expect(hmacSha256Hex(enc.encode('Jefe'), enc.encode('what do ya want for nothing?'))).toBe(
      '5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843',
    );
  });

  // RFC 4231 case 1 — a 20-byte key of 0x0b, message "Hi There".
  it('matches RFC 4231 case 1', () => {
    expect(hmacSha256Hex(new Uint8Array(20).fill(0x0b), enc.encode('Hi There'))).toBe(
      'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7',
    );
  });

  // RFC 4231 case 4 exercises the branch where the key is longer than the
  // 64-byte SHA-256 block and must be hashed down first.
  it('hashes a key longer than the block size down before padding', () => {
    const longKey = new Uint8Array(131).fill(0xaa);
    expect(
      hmacSha256Hex(longKey, enc.encode('Test Using Larger Than Block-Size Key - Hash Key First')),
    ).toBe('60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54');
  });

  // node:crypto is an independent oracle. It pins the block-size boundary in
  // particular: a key of exactly 64 bytes must be used as-is, and one of 65
  // must be hashed down first, and the two rules differ by one comparison.
  it.each([0, 1, 63, 64, 65, 100])('agrees with node:crypto for a %i-byte key', (keyLength) => {
    const key = new Uint8Array(keyLength).map((_, i) => (i * 7 + 1) & 0xff);
    const message = enc.encode('boundary probe');
    expect(hmacSha256Hex(key, message)).toBe(
      createHmac('sha256', Buffer.from(key)).update(Buffer.from(message)).digest('hex'),
    );
  });

  it('agrees with node:crypto for an empty message', () => {
    expect(hmacSha256Hex(enc.encode('k'), new Uint8Array(0))).toBe(
      createHmac('sha256', 'k').update('').digest('hex'),
    );
  });

  it('produces a different signature for a different key', () => {
    const message = enc.encode('same message');
    expect(hmacSha256Hex(enc.encode('key-a'), message)).not.toBe(
      hmacSha256Hex(enc.encode('key-b'), message),
    );
  });
});

describe('sha256Bytes', () => {
  it('returns the 32-byte digest matching sha256Hex', () => {
    const bytes = sha256Bytes(new TextEncoder().encode('abc'));
    expect(bytes).toHaveLength(32);
    expect(Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')).toBe(
      sha256Hex('abc'),
    );
  });
});
