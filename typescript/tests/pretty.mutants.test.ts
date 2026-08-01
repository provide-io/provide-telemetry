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

import { describe, expect, it, vi } from 'vitest';
import { formatPretty } from '../src/pretty.js';

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

describe('formatPretty — cold-module lookup tables', () => {
  it('renders every level, named color, and reserved key from a fresh module', async () => {
    // Stryker's Vitest workers cache modules between mutant activations. Reloading
    // here makes mutations to module-level lookup tables observable.
    vi.resetModules();
    const pretty = await import('../src/pretty.js');

    const levels = [
      [10, 'trace', '\x1b[36m'],
      [20, 'debug', '\x1b[34m'],
      [30, 'info', '\x1b[32m'],
      [40, 'warn', '\x1b[33m'],
      [50, 'error', '\x1b[31m'],
      [60, 'fatal', '\x1b[31;1m'],
    ] as const;
    for (const [level, name, color] of levels) {
      expect(pretty.formatPretty({ level, event: 'probe' }, true)).toBe(
        `[${color}${name.padEnd(6)}\x1b[0m] probe`,
      );
    }

    const namedColors = [
      ['dim', '\x1b[2m'],
      ['bold', '\x1b[1m'],
      ['red', '\x1b[31m'],
      ['green', '\x1b[32m'],
      ['yellow', '\x1b[33m'],
      ['blue', '\x1b[34m'],
      ['cyan', '\x1b[36m'],
      ['white', '\x1b[37m'],
      ['none', ''],
      ['', ''],
    ] as const;
    for (const [colorName, code] of namedColors) {
      expect(
        pretty.formatPretty({ level: 30, event: 'probe', key: 'value' }, true, {
          keyColor: colorName,
          valueColor: colorName,
        }),
      ).toBe(
        `[\x1b[32minfo  \x1b[0m] probe ${code}key${code ? '\x1b[0m' : ''}=` +
          `${code}"value"${code ? '\x1b[0m' : ''}`,
      );
    }

    const reserved = {
      level: 30,
      time: 'now',
      message: 'message',
      msg: 'msg',
      event: 'event',
      v: 1,
      pid: 2,
      hostname: 'host',
      visible: true,
    };
    expect(pretty.formatPretty(reserved, false)).toBe('now [info  ] event visible=true');
    expect(
      pretty.formatPretty({ level: 30, event: 'probe', key: 'value' }, true, {
        keyColor: '  BoLd  ',
        valueColor: ' CyAn ',
      }),
    ).toContain('\x1b[1mkey\x1b[0m=\x1b[36m"value"\x1b[0m');
  });
});
