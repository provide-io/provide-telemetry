// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  _incrementHealth,
  _recordExportLatency,
  _registerCircuitStateFn,
  _resetHealthForTests,
  _setLastExportError,
  getHealthSnapshot,
  setSetupError,
} from '../src/health';

afterEach(() => _resetHealthForTests());

describe('getHealthSnapshot', () => {
  it('returns zeroed snapshot initially', () => {
    const s = getHealthSnapshot();
    expect(s.logsEmitted).toBe(0);
    expect(s.exportFailures).toBe(0);
    expect(s.lastExportError).toBeNull();
    expect(s.exportLatencyMs).toBe(0);
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
    _incrementHealth('exportFailures', 5);
    expect(getHealthSnapshot().exportFailures).toBe(5);
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
      'exportFailures',
      'exportRetries',
      'asyncBlockingRisk',
      'exemplarUnsupported',
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
  it('sets exportLatencyMs', () => {
    _recordExportLatency(42.5);
    expect(getHealthSnapshot().exportLatencyMs).toBe(42.5);
  });
});

describe('_setLastExportError', () => {
  it('sets a string error message', () => {
    _setLastExportError('connection refused');
    expect(getHealthSnapshot().lastExportError).toBe('connection refused');
  });

  it('clears the error with null', () => {
    _setLastExportError('err');
    _setLastExportError(null);
    expect(getHealthSnapshot().lastExportError).toBeNull();
  });
});

describe('_resetHealthForTests', () => {
  it('resets all state to zero', () => {
    _incrementHealth('logsEmitted', 10);
    _setLastExportError('oops');
    _recordExportLatency(100);
    _resetHealthForTests();
    const s = getHealthSnapshot();
    expect(s.logsEmitted).toBe(0);
    expect(s.lastExportError).toBeNull();
    expect(s.exportLatencyMs).toBe(0);
  });
});

describe('getHealthSnapshot — all fields present', () => {
  it('returns all expected fields with correct types', () => {
    const s = getHealthSnapshot();
    // Numeric counter fields
    expect(typeof s.logsEmitted).toBe('number');
    expect(typeof s.logsDropped).toBe('number');
    expect(typeof s.tracesEmitted).toBe('number');
    expect(typeof s.tracesDropped).toBe('number');
    expect(typeof s.metricsEmitted).toBe('number');
    expect(typeof s.metricsDropped).toBe('number');
    expect(typeof s.exportFailures).toBe('number');
    expect(typeof s.exportRetries).toBe('number');
    expect(typeof s.asyncBlockingRisk).toBe('number');
    expect(typeof s.exemplarUnsupported).toBe('number');
    expect(typeof s.exportLatencyMs).toBe('number');
    // Circuit state fields
    expect(typeof s.circuitStateLogs).toBe('string');
    expect(typeof s.circuitStateTraces).toBe('string');
    expect(typeof s.circuitStateMetrics).toBe('string');
    expect(typeof s.circuitOpenCountLogs).toBe('number');
    expect(typeof s.circuitOpenCountTraces).toBe('number');
    expect(typeof s.circuitOpenCountMetrics).toBe('number');
    expect(typeof s.circuitCooldownRemainingLogs).toBe('number');
    expect(typeof s.circuitCooldownRemainingTraces).toBe('number');
    expect(typeof s.circuitCooldownRemainingMetrics).toBe('number');
  });

  it('default circuit state is "closed" with zero counts', () => {
    const s = getHealthSnapshot();
    expect(s.circuitStateLogs).toBe('closed');
    expect(s.circuitStateTraces).toBe('closed');
    expect(s.circuitStateMetrics).toBe('closed');
    expect(s.circuitOpenCountLogs).toBe(0);
    expect(s.circuitOpenCountTraces).toBe(0);
    expect(s.circuitOpenCountMetrics).toBe(0);
    expect(s.circuitCooldownRemainingLogs).toBe(0);
    expect(s.circuitCooldownRemainingTraces).toBe(0);
    expect(s.circuitCooldownRemainingMetrics).toBe(0);
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
    expect(s.circuitCooldownRemainingLogs).toBe(5000);
    expect(s.circuitStateTraces).toBe('half-open');
    expect(s.circuitOpenCountTraces).toBe(1);
    expect(s.circuitCooldownRemainingTraces).toBe(2000);
    expect(s.circuitStateMetrics).toBe('probing');
    expect(s.circuitOpenCountMetrics).toBe(2);
    expect(s.circuitCooldownRemainingMetrics).toBe(1000);
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
    _incrementHealth('exportFailures', 4);
    _incrementHealth('exportRetries', 6);
    _incrementHealth('asyncBlockingRisk', 8);
    _incrementHealth('exemplarUnsupported', 9);
    _recordExportLatency(42);
    _setLastExportError('timeout');

    const s = getHealthSnapshot();
    expect(s.logsEmitted).toBe(10);
    expect(s.logsDropped).toBe(2);
    expect(s.tracesEmitted).toBe(5);
    expect(s.tracesDropped).toBe(1);
    expect(s.metricsEmitted).toBe(7);
    expect(s.metricsDropped).toBe(3);
    expect(s.exportFailures).toBe(4);
    expect(s.exportRetries).toBe(6);
    expect(s.asyncBlockingRisk).toBe(8);
    expect(s.exemplarUnsupported).toBe(9);
    expect(s.exportLatencyMs).toBe(42);
    expect(s.lastExportError).toBe('timeout');
  });
});
