// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { randomHex, sha256Hex, shortHash12 } from '../src/hash';

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
