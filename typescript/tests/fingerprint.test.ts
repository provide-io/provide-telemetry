// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { computeErrorFingerprint } from '../src/fingerprint';

describe('computeErrorFingerprint', () => {
  it('produces a 12-char hex string', () => {
    const fp = computeErrorFingerprint('TypeError');
    expect(fp).toHaveLength(12);
    expect(fp).toMatch(/^[0-9a-f]{12}$/);
  });

  it('is deterministic', () => {
    const a = computeErrorFingerprint('ValueError');
    const b = computeErrorFingerprint('ValueError');
    expect(a).toBe(b);
  });

  it('differs by error name', () => {
    const a = computeErrorFingerprint('TypeError');
    const b = computeErrorFingerprint('RangeError');
    expect(a).not.toBe(b);
  });

  it('includes stack frames in fingerprint', () => {
    const stack = `Error: boom
    at myFunction (src/app.js:10:5)
    at handler (src/routes.js:20:10)
    at process (src/server.js:30:15)`;
    const withStack = computeErrorFingerprint('Error', stack);
    const without = computeErrorFingerprint('Error');
    expect(withStack).not.toBe(without);
  });

  it('same stack produces same fingerprint', () => {
    const stack = `Error: test
    at foo (bar.js:1:1)`;
    const a = computeErrorFingerprint('Error', stack);
    const b = computeErrorFingerprint('Error', stack);
    expect(a).toBe(b);
  });

  it('ignores line numbers (deploy-stable)', () => {
    const stack1 = `Error: test
    at myFunc (app.js:10:5)`;
    const stack2 = `Error: test
    at myFunc (app.js:99:99)`;
    expect(computeErrorFingerprint('Error', stack1)).toBe(computeErrorFingerprint('Error', stack2));
  });

  it('handles empty stack', () => {
    const fp = computeErrorFingerprint('Error', '');
    expect(fp).toHaveLength(12);
  });

  it('handles undefined stack', () => {
    const fp = computeErrorFingerprint('Error', undefined);
    expect(fp).toHaveLength(12);
  });

  it('handles V8 stack without function name', () => {
    const stack = `Error: test
    at /app/src/index.js:10:5`;
    const fp = computeErrorFingerprint('Error', stack);
    expect(fp).toHaveLength(12);
    expect(fp).not.toBe(computeErrorFingerprint('Error'));
  });

  it('handles stack with Windows paths', () => {
    const stack = `Error: test
    at myFunc (C:\\Users\\dev\\app.js:10:5)`;
    const fp = computeErrorFingerprint('Error', stack);
    expect(fp).toHaveLength(12);
  });

  it('parses SpiderMonkey/Firefox stack format', () => {
    const stack = `myFunc@http://example.com/app.js:10:5
handler@http://example.com/routes.js:20:10`;
    const fp = computeErrorFingerprint('Error', stack);
    expect(fp).toHaveLength(12);
    // Different from no-stack since frames are included
    expect(fp).not.toBe(computeErrorFingerprint('Error'));
  });

  it('handles stack line with no matching groups', () => {
    // A line that partially matches but has edge-case empty groups
    const stack = 'at :1:1';
    const fp = computeErrorFingerprint('Error', stack);
    expect(fp).toHaveLength(12);
  });

  it('handles stack with bare filename no path', () => {
    const stack = 'at myFunc (script.js:1:1)';
    const fp = computeErrorFingerprint('Error', stack);
    expect(fp).toHaveLength(12);
    expect(fp).not.toBe(computeErrorFingerprint('Error'));
  });
});
