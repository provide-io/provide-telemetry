// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * shutdownTelemetry spends one budget, not one per phase.
 *
 * `timeoutMs` is what a caller has left of its termination grace period. Giving
 * the forceFlush and the shutdown that follows it the full deadline each lets a
 * flush that lands just inside the budget be followed by a shutdown that gets
 * the whole budget again — so the caller waits almost twice what it asked for
 * and is killed with records still queued.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { shutdownTelemetry } from '../src/shutdown.js';
import { _resetRuntimeForTests, _storeRegisteredProviders } from '../src/runtime.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';

beforeEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  setupTelemetry({ serviceName: 'shutdown-budget' });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetRuntimeForTests();
  _resetConfig();
});

const after = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const never = () => new Promise<void>(() => {});

describe('shutdownTelemetry budget', () => {
  it('does not restart the deadline for the shutdown phase', async () => {
    // A flush that eats most of the budget, then a shutdown that never
    // resolves. Per-phase deadlines would total ~500ms; one budget caps it at
    // ~300ms. The two outcomes are 200ms apart and the bound sits between them,
    // so coverage instrumentation and a loaded machine cannot flip the verdict.
    const provider = { forceFlush: () => after(200), shutdown: never };
    _storeRegisteredProviders([provider]);

    const startedAt = Date.now();
    await shutdownTelemetry(300);
    const elapsed = Date.now() - startedAt;

    expect(elapsed).toBeLessThan(420);
    // Above the flush alone, so the assertion still fails if the shutdown phase
    // were skipped outright rather than bounded.
    expect(elapsed).toBeGreaterThanOrEqual(200);
  });

  it('still gives the shutdown phase what the flush left unspent', async () => {
    // A fast flush must not cost the shutdown its share of the budget.
    const provider = { forceFlush: () => after(5), shutdown: () => after(40) };
    let stopped = false;
    const tracked = {
      forceFlush: provider.forceFlush,
      shutdown: async () => {
        await provider.shutdown();
        stopped = true;
      },
    };
    _storeRegisteredProviders([tracked]);

    await shutdownTelemetry(200);

    expect(stopped).toBe(true);
  });

  it('abandons a flush that spends the whole budget', async () => {
    const provider = { forceFlush: never, shutdown: never };
    _storeRegisteredProviders([provider]);

    const startedAt = Date.now();
    await shutdownTelemetry(100);

    // Generous: what is being asserted is that it returns at all rather than
    // waiting on two never-resolving promises, not the precise wall time.
    expect(Date.now() - startedAt).toBeLessThan(400);
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('forceFlush exceeded 100ms deadline'),
    );
  });
});
