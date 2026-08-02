// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * flushSignals — the per-signal drain the facade reports from.
 *
 * The three signals export to three potentially different endpoints, so an
 * unreachable logs collector says nothing about traces and metrics. Reporting
 * one aggregate boolean on all three makes a caller re-emit or alert on records
 * that were already delivered.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSignals, flushTelemetry } from '../src/shutdown.js';
import { _resetRuntimeForTests, _storeRegisteredProviders } from '../src/runtime.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';

beforeEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  setupTelemetry({ serviceName: 'flush-signals' });
});

afterEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
});

const ok = () => ({ forceFlush: () => Promise.resolve() });
const hangs = () => ({ forceFlush: () => new Promise<void>(() => {}) });

describe('flushSignals', () => {
  it('reports each tagged signal separately', async () => {
    _storeRegisteredProviders([hangs(), ok(), ok()], ['logs', 'traces', 'metrics']);

    await expect(flushSignals(20)).resolves.toEqual({
      logs: false,
      traces: true,
      metrics: true,
    });
  });

  it('omits signals with no provider of ours behind them', async () => {
    _storeRegisteredProviders([ok()], ['traces']);

    const drained = await flushSignals(50);
    expect(Object.prototype.hasOwnProperty.call(drained, 'traces')).toBe(true);
    expect(Object.prototype.hasOwnProperty.call(drained, 'logs')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(drained, 'metrics')).toBe(false);
  });

  it('omits everything when providers were registered untagged', async () => {
    // Untagged providers are still drained by flushTelemetry; they just cannot
    // be attributed to a signal.
    _storeRegisteredProviders([ok()]);

    await expect(flushSignals(50)).resolves.toEqual({});
    await expect(flushTelemetry(50)).resolves.toBe(true);
  });

  it('resolves to an empty record with nothing installed', async () => {
    await expect(flushSignals(50)).resolves.toEqual({});
  });

  it('falls back to the configured deadline when none is passed', async () => {
    setupTelemetry({ serviceName: 'flush-signals', exporterLogsShutdownTimeoutMs: 20 });
    _storeRegisteredProviders([hangs()], ['logs']);

    await expect(flushSignals()).resolves.toEqual({ logs: false });
  });

  it('ignores a signal tag with no provider behind it', async () => {
    // Defensive: the two arrays are positional, and a caller that hands over
    // more tags than providers must not produce an undefined provider entry.
    _storeRegisteredProviders([ok()], ['logs', 'traces']);

    await expect(flushSignals(50)).resolves.toEqual({ logs: true });
  });

  it('starts every drain before awaiting the first', async () => {
    // A sequential implementation would spend the deadline on the first
    // provider and report the second as timed out too.
    const started: string[] = [];
    _storeRegisteredProviders(
      [
        {
          forceFlush: () => {
            started.push('logs');
            return new Promise<void>(() => {});
          },
        },
        {
          forceFlush: () => {
            started.push('traces');
            return Promise.resolve();
          },
        },
      ],
      ['logs', 'traces'],
    );

    const drained = await flushSignals(20);
    expect(started).toEqual(['logs', 'traces']);
    expect(drained.traces).toBe(true);
    expect(drained.logs).toBe(false);
  });
});
