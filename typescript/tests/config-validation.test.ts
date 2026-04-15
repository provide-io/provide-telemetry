// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Boundary and validation tests for config.ts env helpers.
 * Split from config.test.ts to stay under 500 LOC per file.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { _resetConfig, configFromEnv, parseOtlpHeaders } from '../src/config';
import { _resetSamplingForTests } from '../src/sampling';
import { _resetBackpressureForTests } from '../src/backpressure';
import { _resetResilienceForTests } from '../src/resilience';
import { ConfigurationError } from '../src/exceptions';

function withEnv(vars: Record<string, string>, fn: () => void): void {
  const saved: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(vars)) {
    saved[k] = process.env[k];
    process.env[k] = v;
  }
  try {
    fn();
  } finally {
    for (const k of Object.keys(vars)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
}

afterEach(() => {
  _resetConfig();
  _resetSamplingForTests();
  _resetBackpressureForTests();
  _resetResilienceForTests();
});

describe('envFloatInRange — boundary conditions', () => {
  it('value at min (0.0) passes', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: '0.0' }, () => {
      const cfg = configFromEnv();
      expect(cfg.traceSampleRate).toBe(0.0);
    });
  });

  it('value at max (1.0) passes', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: '1.0' }, () => {
      const cfg = configFromEnv();
      expect(cfg.traceSampleRate).toBe(1.0);
    });
  });

  it('value below min (-0.001) throws ConfigurationError', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: '-0.001' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('value above max (1.001) throws ConfigurationError', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: '1.001' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('error message contains the field name', () => {
    withEnv({ PROVIDE_SAMPLING_LOGS_RATE: '2.0' }, () => {
      expect(() => configFromEnv()).toThrow(/PROVIDE_SAMPLING_LOGS_RATE/);
    });
  });

  it('error message contains the range bounds', () => {
    withEnv({ PROVIDE_SAMPLING_TRACES_RATE: '-1' }, () => {
      expect(() => configFromEnv()).toThrow(/\[0, 1\]/);
    });
  });

  it('NaN value falls back to default (envNumber returns fallback for NaN)', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: 'abc' }, () => {
      const cfg = configFromEnv();
      // envNumber('abc') -> NaN -> fallback (1.0), which is in range
      expect(cfg.traceSampleRate).toBe(1.0);
    });
  });

  it('Infinity value throws ConfigurationError', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: 'Infinity' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });
});

describe('envNonNegativeInt — boundary conditions', () => {
  it('value 0 passes', () => {
    withEnv({ PROVIDE_BACKPRESSURE_LOGS_MAXSIZE: '0' }, () => {
      const cfg = configFromEnv();
      expect(cfg.backpressureLogsMaxsize).toBe(0);
    });
  });

  it('value -1 throws ConfigurationError', () => {
    withEnv({ PROVIDE_BACKPRESSURE_LOGS_MAXSIZE: '-1' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('positive integer passes', () => {
    withEnv({ PROVIDE_BACKPRESSURE_LOGS_MAXSIZE: '100' }, () => {
      const cfg = configFromEnv();
      expect(cfg.backpressureLogsMaxsize).toBe(100);
    });
  });

  it('non-integer value (1.5) throws ConfigurationError', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_RETRIES: '1.5' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('error message contains the field name for non-negative int', () => {
    withEnv({ PROVIDE_BACKPRESSURE_TRACES_MAXSIZE: '-5' }, () => {
      expect(() => configFromEnv()).toThrow(/PROVIDE_BACKPRESSURE_TRACES_MAXSIZE/);
    });
  });

  it('error message says "non-negative integer"', () => {
    withEnv({ PROVIDE_BACKPRESSURE_METRICS_MAXSIZE: '-1' }, () => {
      expect(() => configFromEnv()).toThrow(/non-negative integer/);
    });
  });
});

describe('envNonNegativeMsFromSeconds — boundary conditions', () => {
  it('value 0 (seconds) passes and converts to 0ms', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS: '0' }, () => {
      const cfg = configFromEnv();
      expect(cfg.exporterLogsBackoffMs).toBe(0);
    });
  });

  it('positive value (5 seconds) converts to 5000ms', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS: '5' }, () => {
      const cfg = configFromEnv();
      expect(cfg.exporterLogsTimeoutMs).toBe(5000);
    });
  });

  it('negative value (-1 second) throws ConfigurationError', () => {
    withEnv({ PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS: '-1' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('error message contains the field name for negative timeout', () => {
    withEnv({ PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS: '-0.5' }, () => {
      expect(() => configFromEnv()).toThrow(/PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS/);
    });
  });
});

describe('parseOtlpHeaders — trim and boundary mutation killing', () => {
  it('empty string returns empty record (kills ConditionalExpression→false on line 480)', () => {
    expect(parseOtlpHeaders('')).toEqual({});
  });

  it('key at idx=1 is accepted (kills EqualityOperator idx<1 → idx<=1)', () => {
    // "k=v" has '=' at index 1, so idx=1 which must pass (not be skipped)
    expect(parseOtlpHeaders('k=v')).toEqual({ k: 'v' });
  });

  it('key at idx=0 (empty key) is skipped (idx<1 catches idx=0)', () => {
    expect(parseOtlpHeaders('=value')).toEqual({});
  });

  it('trims whitespace from key (kills MethodExpression .trim() on key)', () => {
    expect(parseOtlpHeaders(' key =value')).toEqual({ key: 'value' });
  });

  it('trims whitespace from value (kills MethodExpression .trim() on value)', () => {
    expect(parseOtlpHeaders('key= value ')).toEqual({ key: 'value' });
  });

  it('skips pairs with invalid URL encoding', () => {
    expect(parseOtlpHeaders('%ZZ=val,good=ok')).toEqual({ good: 'ok' });
  });
});

describe('envBool — edge cases for mutation killing', () => {
  it('"on" maps to true', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'on' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('"off" maps to false', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'off' }, () => {
      expect(configFromEnv().otelEnabled).toBe(false);
    });
  });

  it('"yes" maps to true', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'yes' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('"no" maps to false', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'no' }, () => {
      expect(configFromEnv().otelEnabled).toBe(false);
    });
  });

  it('empty string returns fallback', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: '' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('whitespace-only string returns fallback', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: '   ' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('invalid boolean string throws with field name in message', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'maybe' }, () => {
      expect(() => configFromEnv()).toThrow(/PROVIDE_TRACE_ENABLED/);
    });
  });

  it('invalid boolean string throws ConfigurationError', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'nah' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('whitespace-padded "true" is accepted (kills MethodExpression raw.trim())', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: '  true  ' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('whitespace-padded "false" is accepted', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: '  false  ' }, () => {
      expect(configFromEnv().otelEnabled).toBe(false);
    });
  });
});
