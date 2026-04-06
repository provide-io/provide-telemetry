// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  _incrementHealth,
  _recordExportLatency,
  _registerCircuitStateFn,
  _resetHealthForTests,
  getHealthSnapshot,
  setSetupError,
} from '../src/health';

afterEach(() => _resetHealthForTests());

describe('getHealthSnapshot', () => {
  it('returns zeroed snapshot initially', () => {
    const s = getHealthSnapshot();
    expect(s.logsEmitted).toBe(0);
    expect(s.exportFailuresLogs).toBe(0);
    expect(s.exportLatencyMsLogs).toBe(0);
  });

  it('returns a copy (mutations do not affect internal state)', () => {
    const s = getHealthSnapshot();
    s.logsEmitted = 999;
    expect(getHealthSnapshot().logsEmitted).toBe(0);
  });
});

describe('_incrementHealth', () => {
  it('increments numeric fields by 1 by default', () => {
    _incrementHealth('logsEmitted');
    expect(getHealthSnapshot().logsEmitted).toBe(1);
  });

  it('increments by a custom amount', () => {
    _incrementHealth('exportFailuresLogs', 5);
    expect(getHealthSnapshot().exportFailuresLogs).toBe(5);
  });

  it('accumulates multiple increments', () => {
    _incrementHealth('logsDropped');
    _incrementHealth('logsDropped');
    _incrementHealth('logsDropped', 3);
    expect(getHealthSnapshot().logsDropped).toBe(5);
  });

  it('increments all numeric fields', () => {
    const fields = [
      'logsEmitted',
      'logsDropped',
      'tracesEmitted',
      'tracesDropped',
      'metricsEmitted',
      'metricsDropped',
      'exportFailuresLogs',
      'exportFailuresTraces',
      'exportFailuresMetrics',
      'retriesLogs',
      'retriesTraces',
      'retriesMetrics',
      'exportLatencyMsLogs',
      'exportLatencyMsTraces',
      'exportLatencyMsMetrics',
      'asyncBlockingRiskLogs',
      'asyncBlockingRiskTraces',
      'asyncBlockingRiskMetrics',
    ] as const;
    for (const f of fields) {
      _incrementHealth(f, 2);
    }
    const s = getHealthSnapshot();
    for (const f of fields) {
      expect(s[f]).toBe(2);
    }
  });
});

describe('_recordExportLatency', () => {
  it('sets per-signal exportLatencyMs', () => {
    _recordExportLatency('logs', 42.5);
    expect(getHealthSnapshot().exportLatencyMsLogs).toBe(42.5);
    expect(getHealthSnapshot().exportLatencyMsTraces).toBe(0);
  });

  it('sets traces latency independently', () => {
    _recordExportLatency('traces', 10);
    _recordExportLatency('metrics', 20);
    expect(getHealthSnapshot().exportLatencyMsTraces).toBe(10);
    expect(getHealthSnapshot().exportLatencyMsMetrics).toBe(20);
    expect(getHealthSnapshot().exportLatencyMsLogs).toBe(0);
  });
});

describe('_resetHealthForTests', () => {
  it('resets all state to zero', () => {
    _incrementHealth('logsEmitted', 10);
    _recordExportLatency('logs', 100);
    _resetHealthForTests();
    const s = getHealthSnapshot();
    expect(s.logsEmitted).toBe(0);
    expect(s.exportLatencyMsLogs).toBe(0);
  });
});

describe('getHealthSnapshot — all 25 fields present', () => {
  it('returns all expected fields with correct types', () => {
    const s = getHealthSnapshot();
    // Per-signal counter fields (logs)
    expect(typeof s.logsEmitted).toBe('number');
    expect(typeof s.logsDropped).toBe('number');
    expect(typeof s.exportFailuresLogs).toBe('number');
    expect(typeof s.retriesLogs).toBe('number');
    expect(typeof s.exportLatencyMsLogs).toBe('number');
    expect(typeof s.asyncBlockingRiskLogs).toBe('number');
    expect(typeof s.circuitStateLogs).toBe('string');
    expect(typeof s.circuitOpenCountLogs).toBe('number');
    // Per-signal counter fields (traces)
    expect(typeof s.tracesEmitted).toBe('number');
    expect(typeof s.tracesDropped).toBe('number');
    expect(typeof s.exportFailuresTraces).toBe('number');
    expect(typeof s.retriesTraces).toBe('number');
    expect(typeof s.exportLatencyMsTraces).toBe('number');
    expect(typeof s.asyncBlockingRiskTraces).toBe('number');
    expect(typeof s.circuitStateTraces).toBe('string');
    expect(typeof s.circuitOpenCountTraces).toBe('number');
    // Per-signal counter fields (metrics)
    expect(typeof s.metricsEmitted).toBe('number');
    expect(typeof s.metricsDropped).toBe('number');
    expect(typeof s.exportFailuresMetrics).toBe('number');
    expect(typeof s.retriesMetrics).toBe('number');
    expect(typeof s.exportLatencyMsMetrics).toBe('number');
    expect(typeof s.asyncBlockingRiskMetrics).toBe('number');
    expect(typeof s.circuitStateMetrics).toBe('string');
    expect(typeof s.circuitOpenCountMetrics).toBe('number');
    // Global
    // setupError is string | null — check it exists
    expect('setupError' in s).toBe(true);
  });

  it('has exactly 25 fields', () => {
    const s = getHealthSnapshot();
    expect(Object.keys(s).length).toBe(25);
  });

  it('default circuit state is "closed" with zero counts', () => {
    const s = getHealthSnapshot();
    expect(s.circuitStateLogs).toBe('closed');
    expect(s.circuitStateTraces).toBe('closed');
    expect(s.circuitStateMetrics).toBe('closed');
    expect(s.circuitOpenCountLogs).toBe(0);
    expect(s.circuitOpenCountTraces).toBe(0);
    expect(s.circuitOpenCountMetrics).toBe(0);
  });
});

describe('getHealthSnapshot — custom circuit state function', () => {
  afterEach(() => {
    // Restore default circuit state function
    _registerCircuitStateFn(() => ({ state: 'closed', openCount: 0, cooldownRemainingMs: 0 }));
  });

  it('reflects registered circuit state function for each signal', () => {
    _registerCircuitStateFn((signal: string) => {
      if (signal === 'logs') return { state: 'open', openCount: 3, cooldownRemainingMs: 5000 };
      if (signal === 'traces')
        return { state: 'half-open', openCount: 1, cooldownRemainingMs: 2000 };
      if (signal === 'metrics')
        return { state: 'probing', openCount: 2, cooldownRemainingMs: 1000 };
      return { state: 'unknown', openCount: 99, cooldownRemainingMs: 99 };
    });
    const s = getHealthSnapshot();
    expect(s.circuitStateLogs).toBe('open');
    expect(s.circuitOpenCountLogs).toBe(3);
    expect(s.circuitStateTraces).toBe('half-open');
    expect(s.circuitOpenCountTraces).toBe(1);
    expect(s.circuitStateMetrics).toBe('probing');
    expect(s.circuitOpenCountMetrics).toBe(2);
  });
});

describe('getHealthSnapshot — setupError field', () => {
  it('setupError is null by default', () => {
    expect(getHealthSnapshot().setupError).toBeNull();
  });

  it('setupError reflects setSetupError value', () => {
    setSetupError('something went wrong');
    const s = getHealthSnapshot();
    expect(s.setupError).toBe('something went wrong');
  });

  it('setupError can be cleared to null', () => {
    setSetupError('err');
    setSetupError(null);
    expect(getHealthSnapshot().setupError).toBeNull();
  });
});

describe('getHealthSnapshot — counter values reflect increments', () => {
  it('each counter field reflects its incremented value', () => {
    _incrementHealth('logsEmitted', 10);
    _incrementHealth('logsDropped', 2);
    _incrementHealth('tracesEmitted', 5);
    _incrementHealth('tracesDropped', 1);
    _incrementHealth('metricsEmitted', 7);
    _incrementHealth('metricsDropped', 3);
    _incrementHealth('exportFailuresLogs', 4);
    _incrementHealth('exportFailuresTraces', 11);
    _incrementHealth('exportFailuresMetrics', 12);
    _incrementHealth('retriesLogs', 6);
    _incrementHealth('retriesTraces', 13);
    _incrementHealth('retriesMetrics', 14);
    _incrementHealth('asyncBlockingRiskLogs', 8);
    _incrementHealth('asyncBlockingRiskTraces', 15);
    _incrementHealth('asyncBlockingRiskMetrics', 16);
    _recordExportLatency('logs', 42);
    _recordExportLatency('traces', 43);
    _recordExportLatency('metrics', 44);

    const s = getHealthSnapshot();
    expect(s.logsEmitted).toBe(10);
    expect(s.logsDropped).toBe(2);
    expect(s.tracesEmitted).toBe(5);
    expect(s.tracesDropped).toBe(1);
    expect(s.metricsEmitted).toBe(7);
    expect(s.metricsDropped).toBe(3);
    expect(s.exportFailuresLogs).toBe(4);
    expect(s.exportFailuresTraces).toBe(11);
    expect(s.exportFailuresMetrics).toBe(12);
    expect(s.retriesLogs).toBe(6);
    expect(s.retriesTraces).toBe(13);
    expect(s.retriesMetrics).toBe(14);
    expect(s.asyncBlockingRiskLogs).toBe(8);
    expect(s.asyncBlockingRiskTraces).toBe(15);
    expect(s.asyncBlockingRiskMetrics).toBe(16);
    expect(s.exportLatencyMsLogs).toBe(42);
    expect(s.exportLatencyMsTraces).toBe(43);
    expect(s.exportLatencyMsMetrics).toBe(44);
  });
});
