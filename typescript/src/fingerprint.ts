// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stable error fingerprinting — generates a 12-char hex hash from
 * exception type + top 3 stack frames (file:function, no line numbers).
 *
 * Cross-language compatible: same error in Python and TypeScript produces
 * the same fingerprint when the call path is equivalent.
 */

import { createHash } from 'node:crypto';

/**
 * Parse an Error stack trace into normalized frames: `basename:function`.
 * Returns at most 3 frames (most recent).
 */
function extractFrames(stack: string | undefined): string[] {
  // Stryker disable next-line ConditionalExpression -- equivalent: falsy stack always yields no frames
  if (!stack) return [];
  const frames: string[] = [];
  // V8: "at functionName (filename:line:col)" or "at filename:line:col"
  // Stryker disable next-line Regex -- \s+ vs \s and trailing \d+ vs \d are equivalent for real stacks
  const v8Re = /at\s+(?:(.+?)\s+\()?(.*?):\d+:\d+\)?/g;
  // SpiderMonkey/JSC: "functionName@filename:line:col"
  // Stryker disable next-line Regex -- trailing \d+ vs \d is equivalent for file extraction
  const smRe = /(.+?)@(.*?):\d+:\d+/g;
  for (const re of [v8Re, smRe]) {
    let match: RegExpExecArray | null;
    while ((match = re.exec(stack)) !== null) {
      const func = String(match[1] || '').toLowerCase();
      const file = String(match[2] || '');
      const parts = file.split('/');
      const last = parts[parts.length - 1] || '';
      const winParts = last.split('\\');
      const leaf = winParts[winParts.length - 1] || '';
      const basename = leaf.replace(/\.[^.]+$/, '').toLowerCase();
      if (basename) {
        frames.push(`${basename}:${func}`);
      }
    }
  }
  return frames.slice(-3);
}

/**
 * Compute a stable 12-char hex fingerprint for an error.
 */
export function computeErrorFingerprint(errorName: string, stack?: string): string {
  const parts = [errorName.toLowerCase()];
  parts.push(...extractFrames(stack));
  return createHash('sha256').update(parts.join(':')).digest('hex').slice(0, 12);
}
