// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * configFromEnv tests for exporter resilience, SLO, PII, security, OTLP headers,
 * envNumber/envSecondsToMs helpers, parseModuleLevels, and requiredLogKeys.
 * Basic configFromEnv env var reads live in config.env.test.ts.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { _resetConfig, configFromEnv } from '../src/config';
import { _resetSamplingForTests } from '../src/sampling';
import { _resetBackpressureForTests } from '../src/backpressure';
import { _resetResilienceForTests } from '../src/resilience';
import { ConfigurationError } from '../src/exceptions';

afterEach(() => {
  _resetConfig();
  _resetSamplingForTests();
  _resetBackpressureForTests();
  _resetResilienceForTests();
});

function withEnv(vars: Record<string, string>, fn: () => void): void {
  for (const [k, v] of Object.entries(vars)) process.env[k] = v;
  try {
    fn();
  } finally {
    for (const k of Object.keys(vars)) delete process.env[k];
  }
}

describe('configFromEnv — exporter resilience (logs)', () => {
  it('exporterLogsRetries defaults to 0', () => {
    expect(configFromEnv().exporterLogsRetries).toBe(0);
  });
  it('exporterLogsRetries reads env var', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_RETRIES: '3' }, () => {
      expect(configFromEnv().exporterLogsRetries).toBe(3);
    });
  });
  it('exporterLogsRetries falls back on NaN', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_RETRIES: 'x' }, () => {
      expect(configFromEnv().exporterLogsRetries).toBe(0);
    });
  });
  it('exporterLogsBackoffMs defaults to 0', () => {
    expect(configFromEnv().exporterLogsBackoffMs).toBe(0);
  });
  it('exporterLogsBackoffMs converts seconds to ms', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS: '2.5' }, () => {
      expect(configFromEnv().exporterLogsBackoffMs).toBe(2500);
    });
  });
  it('exporterLogsBackoffMs falls back on NaN', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS: 'bad' }, () => {
      expect(configFromEnv().exporterLogsBackoffMs).toBe(0);
    });
  });
  it('exporterLogsTimeoutMs defaults to 10000', () => {
    expect(configFromEnv().exporterLogsTimeoutMs).toBe(10000);
  });
  it('exporterLogsTimeoutMs converts seconds to ms', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS: '30' }, () => {
      expect(configFromEnv().exporterLogsTimeoutMs).toBe(30000);
    });
  });
  it('exporterLogsTimeoutMs falls back on NaN', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS: 'bad' }, () => {
      expect(configFromEnv().exporterLogsTimeoutMs).toBe(10000);
    });
  });
  it('exporterLogsFailOpen defaults to true', () => {
    expect(configFromEnv().exporterLogsFailOpen).toBe(true);
  });
  it('exporterLogsFailOpen=false when env is "false"', () => {
    withEnv({ PROVIDE_EXPORTER_LOGS_FAIL_OPEN: 'false' }, () => {
      expect(configFromEnv().exporterLogsFailOpen).toBe(false);
    });
  });
});

describe('configFromEnv — exporter resilience (traces)', () => {
  it('exporterTracesRetries defaults to 0', () => {
    expect(configFromEnv().exporterTracesRetries).toBe(0);
  });
  it('exporterTracesRetries reads env var', () => {
    withEnv({ PROVIDE_EXPORTER_TRACES_RETRIES: '5' }, () => {
      expect(configFromEnv().exporterTracesRetries).toBe(5);
    });
  });
  it('exporterTracesBackoffMs defaults to 0', () => {
    expect(configFromEnv().exporterTracesBackoffMs).toBe(0);
  });
  it('exporterTracesBackoffMs converts seconds to ms', () => {
    withEnv({ PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS: '1.5' }, () => {
      expect(configFromEnv().exporterTracesBackoffMs).toBe(1500);
    });
  });
  it('exporterTracesTimeoutMs defaults to 10000', () => {
    expect(configFromEnv().exporterTracesTimeoutMs).toBe(10000);
  });
  it('exporterTracesTimeoutMs converts seconds to ms', () => {
    withEnv({ PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS: '20' }, () => {
      expect(configFromEnv().exporterTracesTimeoutMs).toBe(20000);
    });
  });
  it('exporterTracesFailOpen defaults to true', () => {
    expect(configFromEnv().exporterTracesFailOpen).toBe(true);
  });
  it('exporterTracesFailOpen=false when env is "false"', () => {
    withEnv({ PROVIDE_EXPORTER_TRACES_FAIL_OPEN: 'false' }, () => {
      expect(configFromEnv().exporterTracesFailOpen).toBe(false);
    });
  });
});

describe('configFromEnv — exporter resilience (metrics)', () => {
  it('exporterMetricsRetries defaults to 0', () => {
    expect(configFromEnv().exporterMetricsRetries).toBe(0);
  });
  it('exporterMetricsRetries reads env var', () => {
    withEnv({ PROVIDE_EXPORTER_METRICS_RETRIES: '2' }, () => {
      expect(configFromEnv().exporterMetricsRetries).toBe(2);
    });
  });
  it('exporterMetricsBackoffMs defaults to 0', () => {
    expect(configFromEnv().exporterMetricsBackoffMs).toBe(0);
  });
  it('exporterMetricsBackoffMs converts seconds to ms', () => {
    withEnv({ PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS: '3' }, () => {
      expect(configFromEnv().exporterMetricsBackoffMs).toBe(3000);
    });
  });
  it('exporterMetricsTimeoutMs defaults to 10000', () => {
    expect(configFromEnv().exporterMetricsTimeoutMs).toBe(10000);
  });
  it('exporterMetricsTimeoutMs converts seconds to ms', () => {
    withEnv({ PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS: '15' }, () => {
      expect(configFromEnv().exporterMetricsTimeoutMs).toBe(15000);
    });
  });
  it('exporterMetricsFailOpen defaults to true', () => {
    expect(configFromEnv().exporterMetricsFailOpen).toBe(true);
  });
  it('exporterMetricsFailOpen=false when env is "false"', () => {
    withEnv({ PROVIDE_EXPORTER_METRICS_FAIL_OPEN: 'false' }, () => {
      expect(configFromEnv().exporterMetricsFailOpen).toBe(false);
    });
  });
});

describe('configFromEnv — SLO', () => {
  it('sloEnableRedMetrics defaults to false', () => {
    expect(configFromEnv().sloEnableRedMetrics).toBe(false);
  });
  it('sloEnableRedMetrics=true when env is "true"', () => {
    withEnv({ PROVIDE_SLO_ENABLE_RED_METRICS: 'true' }, () => {
      expect(configFromEnv().sloEnableRedMetrics).toBe(true);
    });
  });
  it('sloEnableUseMetrics defaults to false', () => {
    expect(configFromEnv().sloEnableUseMetrics).toBe(false);
  });
  it('sloEnableUseMetrics=true when env is "true"', () => {
    withEnv({ PROVIDE_SLO_ENABLE_USE_METRICS: 'true' }, () => {
      expect(configFromEnv().sloEnableUseMetrics).toBe(true);
    });
  });
});

describe('configFromEnv — PII', () => {
  it('piiMaxDepth defaults to 8', () => {
    expect(configFromEnv().piiMaxDepth).toBe(8);
  });
  it('piiMaxDepth reads PROVIDE_LOG_PII_MAX_DEPTH env var (kills StringLiteral on env var name)', () => {
    withEnv({ PROVIDE_LOG_PII_MAX_DEPTH: '4' }, () => {
      expect(configFromEnv().piiMaxDepth).toBe(4);
    });
  });
  it('piiMaxDepth falls back on NaN', () => {
    withEnv({ PROVIDE_LOG_PII_MAX_DEPTH: 'bad' }, () => {
      expect(configFromEnv().piiMaxDepth).toBe(8);
    });
  });
});

describe('configFromEnv — security', () => {
  it('securityMaxAttrValueLength defaults to 1024', () => {
    expect(configFromEnv().securityMaxAttrValueLength).toBe(1024);
  });
  it('securityMaxAttrValueLength reads env var', () => {
    withEnv({ PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH: '2048' }, () => {
      expect(configFromEnv().securityMaxAttrValueLength).toBe(2048);
    });
  });
  it('securityMaxAttrValueLength falls back on NaN', () => {
    withEnv({ PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH: 'bad' }, () => {
      expect(configFromEnv().securityMaxAttrValueLength).toBe(1024);
    });
  });
  it('securityMaxAttrCount defaults to 64', () => {
    expect(configFromEnv().securityMaxAttrCount).toBe(64);
  });
  it('securityMaxAttrCount reads env var', () => {
    withEnv({ PROVIDE_SECURITY_MAX_ATTR_COUNT: '128' }, () => {
      expect(configFromEnv().securityMaxAttrCount).toBe(128);
    });
  });
  it('securityMaxAttrCount falls back on NaN', () => {
    withEnv({ PROVIDE_SECURITY_MAX_ATTR_COUNT: 'bad' }, () => {
      expect(configFromEnv().securityMaxAttrCount).toBe(64);
    });
  });
});

describe('configFromEnv — per-signal OTLP headers from env vars', () => {
  function withEnvVars(vars: Record<string, string>, fn: () => void): void {
    for (const [k, v] of Object.entries(vars)) process.env[k] = v;
    try {
      fn();
    } finally {
      for (const k of Object.keys(vars)) delete process.env[k];
    }
  }

  it('parses OTEL_EXPORTER_OTLP_LOGS_HEADERS into otlpLogsHeaders', () => {
    withEnvVars({ OTEL_EXPORTER_OTLP_LOGS_HEADERS: 'x-logs-key=logs-val' }, () => {
      const cfg = configFromEnv();
      expect(cfg.otlpLogsHeaders).toEqual({ 'x-logs-key': 'logs-val' });
    });
  });

  it('parses OTEL_EXPORTER_OTLP_TRACES_HEADERS into otlpTracesHeaders', () => {
    withEnvVars({ OTEL_EXPORTER_OTLP_TRACES_HEADERS: 'x-traces-key=traces-val' }, () => {
      const cfg = configFromEnv();
      expect(cfg.otlpTracesHeaders).toEqual({ 'x-traces-key': 'traces-val' });
    });
  });

  it('parses OTEL_EXPORTER_OTLP_METRICS_HEADERS into otlpMetricsHeaders', () => {
    withEnvVars({ OTEL_EXPORTER_OTLP_METRICS_HEADERS: 'x-metrics-key=metrics-val' }, () => {
      const cfg = configFromEnv();
      expect(cfg.otlpMetricsHeaders).toEqual({ 'x-metrics-key': 'metrics-val' });
    });
  });
});

describe('envNumber — undefined env var returns fallback', () => {
  it('traceSampleRate returns fallback (1.0) when env var is not set', () => {
    delete process.env['PROVIDE_TRACE_SAMPLE_RATE'];
    const cfg = configFromEnv();
    expect(cfg.traceSampleRate).toBe(1.0);
  });

  it('backpressureLogsMaxsize returns fallback (0) when env var is not set', () => {
    delete process.env['PROVIDE_BACKPRESSURE_LOGS_MAXSIZE'];
    const cfg = configFromEnv();
    expect(cfg.backpressureLogsMaxsize).toBe(0);
  });

  it('rejects out-of-range sampling rates', () => {
    process.env['PROVIDE_SAMPLING_LOGS_RATE'] = '1.5';
    try {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    } finally {
      delete process.env['PROVIDE_SAMPLING_LOGS_RATE'];
    }
  });

  it('rejects negative queue sizes', () => {
    process.env['PROVIDE_BACKPRESSURE_LOGS_MAXSIZE'] = '-1';
    try {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    } finally {
      delete process.env['PROVIDE_BACKPRESSURE_LOGS_MAXSIZE'];
    }
  });

  it('rejects non-integer retry counts', () => {
    process.env['PROVIDE_EXPORTER_LOGS_RETRIES'] = '1.5';
    try {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    } finally {
      delete process.env['PROVIDE_EXPORTER_LOGS_RETRIES'];
    }
  });
});

describe('envSecondsToMs — undefined env var returns fallbackMs', () => {
  it('exporterLogsBackoffMs returns fallbackMs (0) when env var is not set', () => {
    delete process.env['PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS'];
    const cfg = configFromEnv();
    expect(cfg.exporterLogsBackoffMs).toBe(0);
  });

  it('exporterLogsTimeoutMs returns fallbackMs (10000) when env var is not set', () => {
    delete process.env['PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS'];
    const cfg = configFromEnv();
    expect(cfg.exporterLogsTimeoutMs).toBe(10000);
  });

  it('rejects negative timeout values', () => {
    process.env['PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS'] = '-1';
    try {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    } finally {
      delete process.env['PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS'];
    }
  });
});

describe('parseModuleLevels — whitespace and delimiter handling', () => {
  it('trims whitespace around comma-separated pairs', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: '  mod1=DEBUG  ,  mod2=WARN  ' }, () => {
      expect(configFromEnv().logModuleLevels).toEqual({
        mod1: 'DEBUG',
        mod2: 'WARN',
      });
    });
  });

  it('skips entries missing = delimiter', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: 'noequalssign,ok=INFO' }, () => {
      const levels = configFromEnv().logModuleLevels;
      expect(levels).toEqual({ ok: 'INFO' });
      expect('noequalssign' in levels).toBe(false);
    });
  });

  it('uses = as delimiter not : or other chars', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: 'mod:DEBUG,mod2=WARN' }, () => {
      const levels = configFromEnv().logModuleLevels;
      expect(levels).toEqual({ mod2: 'WARN' });
    });
  });

  it('trims keys and values around the = sign', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: ' mymod = INFO , other = DEBUG ' }, () => {
      const levels = configFromEnv().logModuleLevels;
      expect(levels['mymod']).toBe('INFO');
      expect(levels['other']).toBe('DEBUG');
      expect(' mymod ' in levels).toBe(false);
      expect(' INFO ' in Object.values(levels)).toBe(false);
    });
  });
});

describe('requiredLogKeys — filter(Boolean) kills empty-string entries', () => {
  it('filters out empty strings from trailing commas', () => {
    withEnv({ PROVIDE_TELEMETRY_REQUIRED_KEYS: 'event,action,' }, () => {
      const keys = configFromEnv().requiredLogKeys;
      expect(keys).toEqual(['event', 'action']);
      expect(keys).toHaveLength(2);
    });
  });

  it('filters out whitespace-only entries', () => {
    withEnv({ PROVIDE_TELEMETRY_REQUIRED_KEYS: 'event, ,action' }, () => {
      const keys = configFromEnv().requiredLogKeys;
      expect(keys).toEqual(['event', 'action']);
    });
  });
});
