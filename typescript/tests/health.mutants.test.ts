// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * What a health snapshot reads as before anything has touched it.
 *
 * Every other health test calls `_resetHealthForTests()` first, which assigns
 * each counter individually — so it repairs an initialiser that never ran, and
 * an emptied `_state` object is indistinguishable from the real one. Likewise
 * the circuit-state fallback is invisible once resilience.ts has registered the
 * real callback, which importing almost anything does.
 *
 * A fresh module, read before either of those happens, is the only place the
 * declarations themselves are observable. See pretty.mutants.test.ts and
 * backpressure.mutants.test.ts for the same technique.
 */

import { describe, expect, it, vi } from 'vitest';

const COUNTERS = [
  'logsEmitted',
  'logsDropped',
  'exportFailuresLogs',
  'retriesLogs',
  'exportLatencyMsLogs',
  'asyncBlockingRiskLogs',
  'tracesEmitted',
  'tracesDropped',
  'exportFailuresTraces',
  'retriesTraces',
  'exportLatencyMsTraces',
  'asyncBlockingRiskTraces',
  'metricsEmitted',
  'metricsDropped',
  'exportFailuresMetrics',
  'retriesMetrics',
  'exportLatencyMsMetrics',
  'asyncBlockingRiskMetrics',
] as const;

describe('health snapshot before any reset', () => {
  it('starts every counter at a real zero, not undefined', async () => {
    vi.resetModules();
    const health = await import('../src/health.js');

    const snapshot = health.getHealthSnapshot() as unknown as Record<string, unknown>;

    for (const field of COUNTERS) {
      expect(snapshot[field], `${field} must start at 0`).toBe(0);
    }
  });

  it('reports a closed circuit per signal before resilience registers one', async () => {
    // Until _registerCircuitStateFn runs, the snapshot answers from the default
    // state. Losing it leaves the facade reporting an undefined circuit — or
    // throwing, if the fallback returns nothing at all.
    vi.resetModules();
    const health = await import('../src/health.js');

    const snapshot = health.getHealthSnapshot();

    expect(snapshot.circuitStateLogs).toBe('closed');
    expect(snapshot.circuitStateTraces).toBe('closed');
    expect(snapshot.circuitStateMetrics).toBe('closed');
    expect(snapshot.circuitOpenCountLogs).toBe(0);
    expect(snapshot.circuitOpenCountTraces).toBe(0);
    expect(snapshot.circuitOpenCountMetrics).toBe(0);
  });

  it('keeps the default state per signal rather than sharing one mutable object', async () => {
    vi.resetModules();
    const health = await import('../src/health.js');

    const first = health.getHealthSnapshot();
    health._incrementHealth('logsEmitted');
    const second = health.getHealthSnapshot();

    // The first snapshot is a value, not a live view of _state.
    expect(first.logsEmitted).toBe(0);
    expect(second.logsEmitted).toBe(1);
  });
});
