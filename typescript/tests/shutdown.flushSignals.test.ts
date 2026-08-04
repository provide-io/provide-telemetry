// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * flushSignals — the per-signal drain the facade reports from.
 *
 * The three signals export to three potentially different endpoints, so an
 * unreachable logs collector says nothing about traces and metrics. Reporting
 * one aggregate boolean on all three makes a caller re-emit or alert on records
 * that were already delivered. Each signal's outcome is a tri-state: `flushed`,
 * `timedOut` (abandoned at the deadline) or `failed` (exporter errored in time).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSignals, flushTelemetry } from '../src/shutdown.js';
import { _resetRuntimeForTests, _storeRegisteredProviders } from '../src/runtime.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';

beforeEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  setupTelemetry({ serviceName: 'flush-signals' });
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetRuntimeForTests();
  _resetConfig();
});

const ok = () => ({ forceFlush: () => Promise.resolve() });
const hangs = () => ({ forceFlush: () => new Promise<void>(() => {}) });
const broken = () => ({ forceFlush: () => Promise.reject(new Error('exporter down')) });

describe('flushSignals', () => {
  it('reports each tagged signal separately', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    _storeRegisteredProviders([hangs(), ok(), ok()], ['logs', 'traces', 'metrics']);

    await expect(flushSignals(20)).resolves.toEqual({
      logs: 'timedOut',
      traces: 'flushed',
      metrics: 'flushed',
    });
  });

  it('reports failed — not timedOut — for an exporter that rejected in time', async () => {
    // Go maps the same condition to Failed; a rejection must neither read as a
    // timeout nor reject the whole call and lose the other signals' outcomes.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    _storeRegisteredProviders([broken(), ok()], ['logs', 'traces']);

    await expect(flushSignals(50)).resolves.toEqual({
      logs: 'failed',
      traces: 'flushed',
    });
    expect(warn).toHaveBeenCalledWith(
      '[provide/telemetry] provider forceFlush failed: Error: exporter down',
    );
  });

  it('omits signals with no provider of ours behind them', async () => {
    _storeRegisteredProviders([ok()], ['traces']);

    const drained = await flushSignals(50);
    expect(Object.prototype.hasOwnProperty.call(drained, 'traces')).toBe(true);
    expect(Object.prototype.hasOwnProperty.call(drained, 'logs')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(drained, 'metrics')).toBe(false);
  });

  it('drains untagged providers under no key', async () => {
    // The docstring's promise: registering without signal tags degrades the
    // report, not the drain. The provider must be flushed exactly once.
    let flushes = 0;
    _storeRegisteredProviders([
      {
        forceFlush: () => {
          flushes += 1;
          return Promise.resolve();
        },
      },
    ]);

    await expect(flushSignals(50)).resolves.toEqual({});
    expect(flushes).toBe(1);
    await expect(flushTelemetry(50)).resolves.toBe(true);
  });

  it('drains the untagged remainder alongside tagged providers, each exactly once', async () => {
    // Identity partition: tagged providers must not be drained a second time as
    // "untagged", and the untagged one must not be skipped.
    const counts = [0, 0, 0];
    const counting = (i: number) => ({
      forceFlush: () => {
        counts[i] += 1;
        return Promise.resolve();
      },
    });
    _storeRegisteredProviders(
      [counting(0), counting(1), counting(2)],
      // Only the first two carry tags; the third is the untagged remainder.
      ['logs', 'traces'],
    );

    await expect(flushSignals(50)).resolves.toEqual({ logs: 'flushed', traces: 'flushed' });
    expect(counts).toEqual([1, 1, 1]);
  });

  it('warns when an untagged provider times out, so the outcome is not silent', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    _storeRegisteredProviders([hangs()]);

    await expect(flushSignals(20)).resolves.toEqual({});

    expect(warn).toHaveBeenCalledWith(expect.stringContaining('forceFlush exceeded 20ms deadline'));
  });

  it('resolves to an empty record with nothing installed', async () => {
    await expect(flushSignals(50)).resolves.toEqual({});
  });

  it('falls back to the configured deadline when none is passed', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({ serviceName: 'flush-signals', exporterLogsShutdownTimeoutMs: 20 });
    _storeRegisteredProviders([hangs()], ['logs']);

    await expect(flushSignals()).resolves.toEqual({ logs: 'timedOut' });
  });

  it('ignores a signal tag with no provider behind it', async () => {
    // Defensive: the two arrays are positional, and a caller that hands over
    // more tags than providers must not produce an undefined provider entry.
    _storeRegisteredProviders([ok()], ['logs', 'traces']);

    await expect(flushSignals(50)).resolves.toEqual({ logs: 'flushed' });
  });

  it('starts every drain before awaiting the first', async () => {
    // A sequential implementation would spend the deadline on the first
    // provider and report the second (and the untagged third) as timed out too.
    vi.spyOn(console, 'warn').mockImplementation(() => {});
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
        {
          forceFlush: () => {
            started.push('untagged');
            return Promise.resolve();
          },
        },
      ],
      ['logs', 'traces'],
    );

    const drained = await flushSignals(20);
    expect(started).toEqual(['logs', 'traces', 'untagged']);
    expect(drained.traces).toBe('flushed');
    expect(drained.logs).toBe('timedOut');
  });
});
