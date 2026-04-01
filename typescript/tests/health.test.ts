// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  _incrementHealth,
  _recordExportLatency,
  _resetHealthForTests,
  _setLastExportError,
  getHealthSnapshot,
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
