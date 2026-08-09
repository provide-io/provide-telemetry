// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Both directions of `asyncBlockingRisk*`.
 *
 * Node's drain path is Promise-based end to end, so the only blocking call it
 * can reach is the provider's own: `forceFlush()` and `shutdown()` run
 * synchronously until they hand back a Promise, and an OTLP exporter serializes
 * its whole pending batch there. The counter must move for a provider that
 * holds the loop through that prelude and stay put for one that does not —
 * a counter that always fires is as useless to an operator as one that never
 * does.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSignals, flushTelemetry, shutdownTelemetry } from '../src/shutdown.js';
import {
  _resetRuntimeForTests,
  _signalForProvider,
  _storeRegisteredProviders,
  type SignalName,
} from '../src/runtime.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';

beforeEach(() => {
  _resetConfig();
  _resetRuntimeForTests();
  _resetHealthForTests();
  setupTelemetry({ serviceName: 'async-blocking-risk' });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetRuntimeForTests();
  _resetHealthForTests();
  _resetConfig();
});

/**
 * Hold the event loop for `ms` and return an already-resolved Promise — the
 * shape of an exporter that encodes its batch before touching a socket. A busy
 * wait rather than a timer on purpose: a timer would yield, which is precisely
 * what this is not doing.
 */
function blockingFlush(ms: number): () => Promise<void> {
  return () => {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      /* deliberately holding the loop */
    }
    return Promise.resolve();
  };
}

/** The well-behaved counterpart: yields immediately, blocks nothing. */
const yieldingFlush = (): Promise<void> => Promise.resolve();

/** 3x the 50ms long-task threshold, so a loaded CI machine cannot undershoot. */
const LONG_BLOCK_MS = 150;

describe('asyncBlockingRisk on the drain path', () => {
  it('counts a provider whose forceFlush holds the event loop, against its own signal', async () => {
    const providers = [{ forceFlush: blockingFlush(LONG_BLOCK_MS) }, { forceFlush: yieldingFlush }];
    const signals: SignalName[] = ['traces', 'metrics'];
    _storeRegisteredProviders(providers, signals);

    await flushTelemetry(5_000);

    const health = getHealthSnapshot();
    expect(health.asyncBlockingRiskTraces).toBe(1);
    // The second provider drained on the same call and yielded immediately, so
    // the counter must distinguish them rather than charging the whole batch.
    expect(health.asyncBlockingRiskMetrics).toBe(0);
    // Nothing was registered for logs at all.
    expect(health.asyncBlockingRiskLogs).toBe(0);
  });

  it('counts nothing when every provider yields', async () => {
    _storeRegisteredProviders([{ forceFlush: yieldingFlush, shutdown: yieldingFlush }], ['logs']);

    await flushTelemetry(5_000);
    await shutdownTelemetry(5_000);

    const health = getHealthSnapshot();
    expect(health.asyncBlockingRiskLogs).toBe(0);
    expect(health.asyncBlockingRiskTraces).toBe(0);
    expect(health.asyncBlockingRiskMetrics).toBe(0);
  });

  it('counts the flush and the shutdown phases of a teardown separately', async () => {
    _storeRegisteredProviders(
      [{ forceFlush: blockingFlush(LONG_BLOCK_MS), shutdown: blockingFlush(LONG_BLOCK_MS) }],
      ['logs'],
    );

    await shutdownTelemetry(5_000);

    // Both phases hold the loop, and each one is a separate stall an operator
    // would see; collapsing them to one would understate the teardown's cost.
    expect(getHealthSnapshot().asyncBlockingRiskLogs).toBe(2);
  });

  it('counts a blocking drain reached through the per-signal flush', async () => {
    _storeRegisteredProviders([{ forceFlush: blockingFlush(LONG_BLOCK_MS) }], ['metrics']);

    await expect(flushSignals(5_000)).resolves.toEqual({ metrics: 'flushed' });

    expect(getHealthSnapshot().asyncBlockingRiskMetrics).toBe(1);
  });

  it('leaves an untagged provider uncounted rather than guessing its signal', async () => {
    // Registered without signals: shutdownTelemetry still drains it, but nothing
    // recorded which exporter it is, so no per-signal counter may claim it.
    _storeRegisteredProviders([{ forceFlush: blockingFlush(LONG_BLOCK_MS) }]);

    await flushTelemetry(5_000);

    const health = getHealthSnapshot();
    expect(health.asyncBlockingRiskLogs).toBe(0);
    expect(health.asyncBlockingRiskTraces).toBe(0);
    expect(health.asyncBlockingRiskMetrics).toBe(0);
  });

  it('counts a blocking drain whose forceFlush then rejects', async () => {
    // The failure path takes its own branch out of flushProviderOutcome; the
    // stall happened before the rejection and must still be recorded.
    const provider = {
      forceFlush: () => {
        const until = Date.now() + LONG_BLOCK_MS;
        while (Date.now() < until) {
          /* deliberately holding the loop */
        }
        return Promise.reject(new Error('exporter down'));
      },
    };
    _storeRegisteredProviders([provider], ['traces']);

    await expect(flushTelemetry(5_000)).resolves.toBe(false);

    expect(getHealthSnapshot().asyncBlockingRiskTraces).toBe(1);
  });

  it('counts a forceFlush that blocks and then throws synchronously', async () => {
    // A synchronously-throwing forceFlush unwinds through callProviderPhase's
    // finally, so the stall it already caused is recorded on the way out.
    const provider = {
      forceFlush: (): Promise<void> => {
        const until = Date.now() + LONG_BLOCK_MS;
        while (Date.now() < until) {
          /* deliberately holding the loop */
        }
        throw new Error('exporter exploded');
      },
    };
    _storeRegisteredProviders([provider], ['logs']);

    await expect(flushTelemetry(5_000)).resolves.toBe(false);

    expect(getHealthSnapshot().asyncBlockingRiskLogs).toBe(1);
  });
});

describe('_signalForProvider', () => {
  it('answers only for providers the registry was handed', () => {
    const registered = { forceFlush: yieldingFlush };
    const foreign = { forceFlush: yieldingFlush };
    _storeRegisteredProviders([registered], ['traces']);

    expect(_signalForProvider(registered)).toBe('traces');
    // A provider a host application installed on the OTel globals is not ours,
    // and must not inherit a tag by position.
    expect(_signalForProvider(foreign)).toBeUndefined();
  });
});
