// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatPretty, supportsColor } from '../src/pretty';

describe('formatPretty', () => {
  it('includes timestamp, level, and event', () => {
    const line = formatPretty({ time: 1700000000000, level: 30, event: 'app.start.ok' }, false);
    expect(line).toContain('[info  ]');
    expect(line).toContain('app.start.ok');
    expect(line).toContain('2023-'); // ISO timestamp
  });

  it('includes key=value pairs sorted alphabetically', () => {
    const line = formatPretty({ level: 30, event: 'test', zebra: 1, alpha: 2 }, false);
    const alphaIdx = line.indexOf('alpha=');
    const zebraIdx = line.indexOf('zebra=');
    expect(alphaIdx).toBeLessThan(zebraIdx);
  });

  it('skips internal keys (level, time, msg, v, pid, hostname)', () => {
    const line = formatPretty(
      {
        level: 30,
        time: 123,
        msg: 'hi',
        event: 'test',
        v: 1,
        pid: 99,
        hostname: 'box',
        user: 'alice',
      },
      false,
    );
    expect(line).not.toContain('pid=');
    expect(line).not.toContain('hostname=');
    expect(line).not.toContain('"v"');
    expect(line).toContain('user=');
  });

  it('adds ANSI colors when enabled', () => {
    const line = formatPretty({ level: 50, event: 'error.test' }, true);
    expect(line).toContain('\x1b[31m'); // red for error
    expect(line).toContain('\x1b[0m'); // reset
  });

  it('no ANSI codes when colors disabled', () => {
    const line = formatPretty({ level: 50, event: 'error.test' }, false);
    expect(line).not.toContain('\x1b[');
  });

  it('handles missing event — falls back to msg', () => {
    const line = formatPretty({ level: 30, msg: 'fallback message' }, false);
    expect(line).toContain('fallback message');
  });

  it('handles missing event and msg — empty string', () => {
    const line = formatPretty({ level: 30 }, false);
    expect(line).toContain('[info  ]');
  });

  it('handles missing time', () => {
    const line = formatPretty({ level: 30, event: 'no-time' }, false);
    expect(line).toContain('[info  ]');
    expect(line).toContain('no-time');
  });

  it('handles unknown level number without colors', () => {
    const line = formatPretty({ level: 99, event: 'custom' }, false);
    expect(line).toContain('[log   ]');
  });

  it('handles unknown level number with colors (no color code)', () => {
    const line = formatPretty({ level: 99, event: 'custom' }, true);
    expect(line).toContain('[log   ');
    expect(line).toContain('\x1b[0m'); // reset still present
  });

  it('dims keys in color mode', () => {
    const line = formatPretty({ level: 30, event: 'test', user: 'alice' }, true);
    expect(line).toContain('\x1b[2m'); // dim
  });

  it('formats non-string time as string', () => {
    const line = formatPretty({ level: 30, event: 'test', time: 'custom-timestamp' }, false);
    expect(line).toContain('custom-timestamp');
  });

  it('colors timestamp when colors enabled and time is numeric', () => {
    const line = formatPretty({ level: 30, event: 'test', time: 1700000000000 }, true);
    expect(line).toContain('\x1b[2m'); // dim for timestamp
    expect(line).toContain('2023-');
  });

  it('colors timestamp when colors enabled and time is string', () => {
    const line = formatPretty({ level: 30, event: 'test', time: 'my-ts' }, true);
    expect(line).toContain('\x1b[2m' + 'my-ts' + '\x1b[0m');
  });

  it('renders all level colors correctly', () => {
    for (const [num, name] of [
      [10, 'trace'],
      [20, 'debug'],
      [30, 'info'],
      [40, 'warn'],
      [50, 'error'],
      [60, 'fatal'],
    ] as const) {
      const line = formatPretty({ level: num, event: 'test' }, true);
      expect(line).toContain(name);
    }
  });

  it('renders level without color when colors disabled', () => {
    const line = formatPretty({ level: 50, event: 'test' }, false);
    expect(line).toContain('[error ');
    expect(line).not.toContain('\x1b[');
  });
});

describe('supportsColor', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('returns false when FORCE_COLOR not set and no TTY', () => {
    // happy-dom environment has no process.stdout.isTTY
    expect(supportsColor()).toBe(false);
  });

  it('returns true when FORCE_COLOR=1', () => {
    vi.stubEnv('FORCE_COLOR', '1');
    expect(supportsColor()).toBe(true);
  });

  it('returns true when FORCE_COLOR=true', () => {
    vi.stubEnv('FORCE_COLOR', 'true');
    expect(supportsColor()).toBe(true);
  });

  it('returns false when NO_COLOR is set', () => {
    vi.stubEnv('NO_COLOR', '');
    expect(supportsColor()).toBe(false);
  });

  it('returns false when FORCE_COLOR is not 1 or true', () => {
    vi.stubEnv('FORCE_COLOR', '0');
    expect(supportsColor()).toBe(false);
  });

  it('returns true when stdout.isTTY is true', () => {
    const orig = process.stdout.isTTY;
    try {
      Object.defineProperty(process.stdout, 'isTTY', { value: true, configurable: true });
      expect(supportsColor()).toBe(true);
    } finally {
      Object.defineProperty(process.stdout, 'isTTY', { value: orig, configurable: true });
    }
  });
});
