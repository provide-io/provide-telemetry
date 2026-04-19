// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Pure-ESM Node load test for propagation.ts. Complements the CJS path
// (covered by propagation.module-scope-await.test.ts and the parity probes
// run via tsx). The CJS branch in propagation.ts uses synchronous require();
// the ESM branch uses fire-and-forget `await import('node:async_hooks')`
// because top-level await is forbidden by esbuild's CJS output.
//
// This test exercises the ESM branch by spawning Node with a .mts fixture
// (Node loads .mts as ESM, where `require` is undefined) and asserting
// AsyncLocalStorage initialises and isolates context as expected.

import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

const FIXTURE = resolve(__dirname, 'fixtures/propagation-esm-probe.mts');

describe('propagation.ts pure-ESM Node load', () => {
  it('async-import init reaches ALS-active state and isolates context', () => {
    const stdout = execFileSync('node', ['--import', 'tsx', FIXTURE], {
      encoding: 'utf8',
      timeout: 10000,
    }).trim();
    // Probe protocol: "fallback=<bool> als=<working|broken|nofn> bind=<ok|err>"
    expect(stdout).toBe('fallback=false als=working bind=ok');
  });
});
