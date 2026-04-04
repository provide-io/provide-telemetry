// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stable error fingerprinting — generates a 12-char hex hash from
 * exception type + top 3 stack frames (file:function, no line numbers).
 *
 * Cross-language compatible: same error in Python and TypeScript produces
 * the same fingerprint when the call path is equivalent.
 */

import { shortHash12 } from './hash';

/**
 * Parse an Error stack trace into normalized frames: `basename:function`.
 * Returns at most 3 frames (most recent).
 */
function extractFrames(stack: string | undefined): string[] {
  if (!stack) return [];
  const frames: string[] = [];
  // V8: "at functionName (filename:line:col)" or "at filename:line:col"
  const v8Re = /at\s+(?:(.+?)\s+\()?(.*?):\d+:\d+\)?/g;
  // SpiderMonkey/JSC: "functionName@filename:line:col"
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
  return shortHash12(parts.join(':'));
}
