// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Pure-ESM Node load probe for propagation.ts.  The .mts extension forces
// Node to treat this script (and any TS files it imports through tsx) as
// ESM, so `require` is undefined and propagation.ts's CJS-first init falls
// through to the fire-and-forget `await import('node:async_hooks')` path.
//
// Stdout protocol consumed by tests/propagation.esm-load.test.ts:
//   "fallback=<bool> als=<working|broken|nofn> bind=<ok|err>"

import { setTimeout as sleep } from 'node:timers/promises';

import {
  bindPropagationContext,
  clearPropagationContext,
  getActivePropagationContext,
  isFallbackMode,
} from '../../src/propagation.ts';

// Give the fire-and-forget async import a few ticks to resolve.
await sleep(50);

const fallback = isFallbackMode();

let alsStatus: 'working' | 'broken' | 'nofn' = 'nofn';
let bindStatus: 'ok' | 'err' = 'err';
try {
  // 32-char trace id, 16-char span id — pragma: allowlist secret
  bindPropagationContext({
    traceparent: '00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01',
  });
  const active = getActivePropagationContext();
  alsStatus = active.traceparent === undefined ? 'broken' : 'working';
  clearPropagationContext();
  bindStatus = 'ok';
} catch {
  bindStatus = 'err';
}

process.stdout.write(`fallback=${fallback} als=${alsStatus} bind=${bindStatus}\n`);
