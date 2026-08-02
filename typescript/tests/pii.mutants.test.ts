// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for pii.ts.
 *
 * Two classes of survivor:
 *
 * 1. Module-level literals (DEFAULT_SANITIZE_FIELDS, REDACTED) are "static
 *    mutants" — evaluated once at import, before Stryker's per-mutant switch
 *    activates. Vitest workers cache the module between mutant runs, so the
 *    mutation is only observable if the module is freshly imported inside the
 *    mutant's own test run. `vi.resetModules()` + dynamic `import()` forces
 *    that (same pattern as pretty.mutants.test.ts).
 *
 * 2. `_applyDefaultSensitiveKeyRedaction`'s `val !== origVal || _pathHasRule(...)`
 *    guard (and the path-building it depends on) looked untestable because
 *    every custom-rule mode that reaches it (hash, drop, default redact)
 *    changes the value, making `val !== origVal` alone always true. `truncate`
 *    is the exception: with a limit above the value's length it is a no-op,
 *    so `val === origVal` even though a rule matched — which is the only way
 *    to isolate `_pathHasRule` (and the path-construction it depends on:
 *    the default `currentPath` param, the per-key spread, and the array
 *    wildcard spread) from the `val !== origVal` half of the guard.
 */

import { describe, expect, it, vi } from 'vitest';
import { registerPiiRule, resetPiiRulesForTests, sanitizePayload } from '../src/pii.js';

describe('pii.ts — module-level lookup tables (fresh import per assertion)', () => {
  it('redacts every DEFAULT_SANITIZE_FIELDS entry, from a fresh module', async () => {
    vi.resetModules();
    const pii = await import('../src/pii.js');
    pii.resetPiiRulesForTests();

    const fields = [
      'password',
      'passwd',
      'secret',
      'token',
      'api_key',
      'apikey',
      'auth',
      'authorization',
      'credential',
      'private_key',
      'ssn',
      'credit_card',
      'creditcard',
      'cvv',
      'pin',
      'account_number',
      'cookie',
    ];
    for (const field of fields) {
      const obj: Record<string, unknown> = { [field]: 'sensitive-value' };
      pii.sanitizePayload(obj);
      expect(obj[field], `field ${field} must be redacted`).toBe('***');
    }
  });

  it('redacts using the exact "***" marker, from a fresh module', async () => {
    vi.resetModules();
    const pii = await import('../src/pii.js');
    pii.resetPiiRulesForTests();

    const obj: Record<string, unknown> = { password: 'hunter2' };
    pii.sanitizePayload(obj);
    expect(obj.password).toBe('***');
  });
});

describe('pii.ts — path-based rule exemption for values a rule left unchanged', () => {
  it('keeps a blocked key whose rule matched but did not change the value (truncate no-op)', () => {
    // truncate with a limit above the value's length is a no-op: val === origVal
    // even though a rule targeted this exact path. This isolates _pathHasRule
    // (and the currentPath/childPath construction it depends on) from the
    // `val !== origVal` half of the guard — real code must still keep the
    // rule's result rather than falling through to default redaction.
    resetPiiRulesForTests();
    registerPiiRule({ path: 'password', mode: 'truncate', truncateTo: 100 });

    const obj: Record<string, unknown> = { password: 'short' };
    sanitizePayload(obj);

    expect(obj.password).toBe('short');

    resetPiiRulesForTests();
  });

  it('still redacts a blocked key with no matching rule at all', () => {
    // The companion case: no rule touches this key, so both val === origVal
    // AND _pathHasRule is false — default redaction must still apply. Without
    // this, a ConditionalExpression mutant forcing the guard to `true` would
    // leak every unruled sensitive field in plaintext.
    resetPiiRulesForTests();

    const obj: Record<string, unknown> = { password: 'plaintext-secret' };
    sanitizePayload(obj);

    expect(obj.password).toBe('***');
  });

  it('keeps a blocked key inside an array whose rule matched via a wildcard path', () => {
    // Exercises the array-recursion branch's `[...currentPath, '*']`: the
    // wildcard segment must reach the array item so a rule targeting the full
    // "data.items.*.password" path is found by _pathHasRule from within the
    // array element, not just from top-level keys.
    resetPiiRulesForTests();
    registerPiiRule({ path: 'data.items.*.password', mode: 'truncate', truncateTo: 100 });

    const obj: Record<string, unknown> = {
      data: { items: [{ password: 'short' }] },
    };
    sanitizePayload(obj);

    const items = (obj.data as Record<string, unknown>).items as Record<string, unknown>[];
    expect(items[0].password).toBe('short');

    resetPiiRulesForTests();
  });
});
