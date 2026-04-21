// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for pretty.ts.
 *
 * Addresses survivor L80:37 — StringLiteral mutant on `obj['message']`
 * where the string literal `'message'` was being replaced with `""`.
 * When the event key is absent, the renderer must fall back to the
 * `message` property, not to `obj['']`.
 */

import { describe, expect, it } from 'vitest';
import { formatPretty } from '../src/pretty';

describe('formatPretty — event falls back to obj["message"] specifically', () => {
  it('uses obj.message when event is absent (kills StringLiteral "" mutant)', () => {
    // If the literal 'message' is replaced with '', the fallback becomes obj[''] === undefined,
    // so the rendered line would not contain the message text.
    const line = formatPretty({ level: 30, message: 'hello-from-message-key' }, false);
    expect(line).toContain('hello-from-message-key');
  });

  it('empty-string key lookup returns undefined (guards against accidental "" literal)', () => {
    // Belt and braces: if the literal were '' the fallback would look up obj[''],
    // which is never set by callers — ensure the renderer *does* find 'message'.
    const obj: Record<string, unknown> = { level: 30, message: 'REAL' };
    // Sanity check the runtime behaviour we rely on.
    expect(obj['']).toBeUndefined();
    const line = formatPretty(obj, false);
    expect(line).toContain('REAL');
  });
});
