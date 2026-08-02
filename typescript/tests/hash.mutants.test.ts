// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for hash.ts.
 *
 * INITIAL_HASH and ROUND_CONSTANTS are module-level array literals — static
 * mutants (see pretty.mutants.test.ts). sha256Hex is a pure function with no
 * module state, so a fresh import + a well-known test vector is sufficient:
 * any mutation of either constant table produces a completely different
 * digest for "abc".
 */

import { describe, expect, it, vi } from 'vitest';

describe('hash.ts — SHA-256 constant tables, from a fresh module', () => {
  it('produces the standard SHA-256("abc") digest', async () => {
    vi.resetModules();
    const { sha256Hex } = await import('../src/hash.js');
    expect(sha256Hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', // pragma: allowlist secret
    );
  });

  it('produces the standard SHA-256("") digest for the empty string', async () => {
    vi.resetModules();
    const { sha256Hex } = await import('../src/hash.js');
    expect(sha256Hex('')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', // pragma: allowlist secret
    );
  });
});
