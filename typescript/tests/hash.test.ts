// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { sha256Hex, shortHash12 } from '../src/hash';

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
