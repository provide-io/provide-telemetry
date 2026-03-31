// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
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

describe('computeErrorFingerprint — exact value assertions (mutation kills)', () => {
  it('uses last 3 frames from a 4-frame stack, not all 4', () => {
    // frames from 4-line stack: ['a:func1', 'b:func2', 'c:func3', 'd:func4']
    // slice(-3) → ['b:func2', 'c:func3', 'd:func4']
    // parts = ['error', 'b:func2', 'c:func3', 'd:func4']
    const stack4 = `Error: boom
    at func1 (a.js:1:1)
    at func2 (b.js:1:1)
    at func3 (c.js:1:1)
    at func4 (d.js:1:1)`;

    // Expected: exact hash of the 3-frame version
    const expected = createHash('sha256')
      .update('error:b:func2:c:func3:d:func4')
      .digest('hex')
      .slice(0, 12);

    expect(computeErrorFingerprint('Error', stack4)).toBe(expected);
  });

  it('uses colon as separator between error name and frame parts', () => {
    // parts = ['typeerror', 'script:myfunc']
    // ':'.join → 'typeerror:script:myfunc'
    // ''.join → 'typeerrorscrip:myfunc' (different hash)
    const stack = 'at myFunc (script.js:1:1)';
    const expected = createHash('sha256')
      .update('typeerror:script:myfunc')
      .digest('hex')
      .slice(0, 12);
    expect(computeErrorFingerprint('TypeError', stack)).toBe(expected);
  });

  it('uses colon as separator inside each frame (basename:func)', () => {
    // frame format is "basename:func" — colon between basename and func
    // mutation might change to "basename.func" or "basename func"
    const stack = 'at handler (src/utils/helper.js:1:1)';
    // basename = 'helper', func = 'handler'
    const expected = createHash('sha256').update('error:helper:handler').digest('hex').slice(0, 12);
    expect(computeErrorFingerprint('Error', stack)).toBe(expected);
  });

  it('case-folds error name to lowercase', () => {
    // mutation: remove .toLowerCase() on errorName → 'TypeError' ≠ 'typeerror'
    // mutation: .toLowerCase() → .toUpperCase() would make all three hash to 'TYPEERROR' — exact anchor prevents this
    const expected = createHash('sha256').update('typeerror').digest('hex').slice(0, 12);
    expect(computeErrorFingerprint('TypeError')).toBe(expected);
    expect(computeErrorFingerprint('typeerror')).toBe(expected);
    expect(computeErrorFingerprint('TYPEERROR')).toBe(expected);
  });

  it('case-folds function names from V8 stack', () => {
    // mutation: remove .toLowerCase() on func
    const lowerStack = 'at myFunc (script.js:1:1)';
    const upperStack = 'at MYFUNC (script.js:1:1)';
    expect(computeErrorFingerprint('Error', lowerStack)).toBe(
      computeErrorFingerprint('Error', upperStack),
    );
  });

  it('case-folds file basenames from V8 stack', () => {
    // mutation: remove .toLowerCase() on basename
    const lowerStack = 'at handler (MyFile.js:1:1)';
    const upperStack = 'at handler (MYFILE.js:1:1)';
    expect(computeErrorFingerprint('Error', lowerStack)).toBe(
      computeErrorFingerprint('Error', upperStack),
    );
  });

  it('anonymous function (no name) produces empty func string, not "undefined"', () => {
    // stack line without function name: match[1] is undefined
    // `String(match[1] || '')` should produce '' not 'undefined'
    const stack = 'at /app/src/index.js:10:5';
    // parts = ['error', 'index:']  (empty func)
    const expected = createHash('sha256').update('error:index:').digest('hex').slice(0, 12);
    const withUndefined = createHash('sha256')
      .update('error:index:undefined')
      .digest('hex')
      .slice(0, 12);
    expect(computeErrorFingerprint('Error', stack)).toBe(expected);
    expect(computeErrorFingerprint('Error', stack)).not.toBe(withUndefined);
  });
});
