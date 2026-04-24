// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * setupTelemetryAsync — hard "safe or throws" variant of setupTelemetry for
 * ESM entry points. Contract:
 *   1. Returns a Promise<void> that resolves only after propagation init has
 *      settled and ALS is confirmed available.
 *   2. Rejects with ConfigurationError when ALS is force-disabled (simulates
 *      the workers / unbundled-browser path where `node:async_hooks` is
 *      unreachable).
 *   3. After it resolves, concurrent `bindPropagationContext` calls from
 *      independent async tasks do NOT leak context into each other — the
 *      same per-task isolation guarantee callers rely on in production.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { _resetConfig, setupTelemetryAsync } from '../src/config';
import { ConfigurationError } from '../src/exceptions';
import { _resetHealthForTests } from '../src/health';
import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  bindPropagationContext,
  clearPropagationContext,
  getActivePropagationContext,
  isFallbackMode,
  isPropagationInitDone,
  type PropagationALS,
} from '../src/propagation';
import { _resetRuntimeForTests } from '../src/runtime';

beforeEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  _resetPropagationForTests();
  _resetHealthForTests();
});

afterEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  _resetPropagationForTests();
  _resetHealthForTests();
});

describe('setupTelemetryAsync', () => {
  it('returns a Promise<void> that resolves after init', async () => {
    const p = setupTelemetryAsync({ serviceName: 'async-svc' });
    expect(p).toBeInstanceOf(Promise);
    await expect(p).resolves.toBeUndefined();
    // After resolve, init is settled and ALS is live.
    expect(isPropagationInitDone()).toBe(true);
    expect(isFallbackMode()).toBe(false);
  });

  it('rejects with ConfigurationError when ALS is force-disabled', async () => {
    const saved: PropagationALS | null = _disablePropagationALSForTest();
    try {
      // ALS is null → fallback mode → setupTelemetryAsync must throw.
      await expect(setupTelemetryAsync({ serviceName: 'fail-svc' })).rejects.toBeInstanceOf(
        ConfigurationError,
      );
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('reject message explains the ALS unavailability', async () => {
    const saved = _disablePropagationALSForTest();
    try {
      await expect(setupTelemetryAsync({ serviceName: 'fail-svc' })).rejects.toThrow(
        /AsyncLocalStorage unavailable/,
      );
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('applies overrides before the ALS check (config is set even on resolve)', async () => {
    await setupTelemetryAsync({ serviceName: 'applied-async', logLevel: 'debug' });
    // Dynamic import so we read the state after the awaited setup.
    const { getConfig } = await import('../src/config');
    expect(getConfig().serviceName).toBe('applied-async');
    expect(getConfig().logLevel).toBe('debug');
  });

  it('preserves per-task isolation for bindPropagationContext calls interleaved around setup', async () => {
    // Race a "setup" task against two "request" tasks that each bind their
    // own propagation context. With ALS live (post-await), the per-task
    // isolation guarantee must hold — neither request sees the other's
    // traceId, and neither sees anything bound by the setup task.
    type Active = ReturnType<typeof getActivePropagationContext>;
    const spawn = (id: string, delayMs: number): Promise<Active> =>
      new Promise<Active>((resolve) => {
        setTimeout(async () => {
          bindPropagationContext({ traceId: id });
          // Yield to let other tasks interleave.
          await Promise.resolve();
          await Promise.resolve();
          const active = getActivePropagationContext();
          clearPropagationContext();
          resolve(active);
        }, delayMs);
      });

    const setupPromise = setupTelemetryAsync({ serviceName: 'racing-svc' });
    const [a, b] = await Promise.all([spawn('task-A', 0), spawn('task-B', 0), setupPromise]);
    expect(a.traceId).toBe('task-A');
    expect(b.traceId).toBe('task-B');
  });
});
