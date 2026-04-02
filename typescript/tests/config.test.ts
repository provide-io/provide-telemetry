// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import { _resetConfig, getConfig, setupTelemetry, version } from '../src/config';
import { _resetSamplingForTests } from '../src/sampling';
import { _resetBackpressureForTests } from '../src/backpressure';
import { _resetResilienceForTests } from '../src/resilience';

afterEach(() => {
  _resetConfig();
  _resetSamplingForTests();
  _resetBackpressureForTests();
  _resetResilienceForTests();
});

describe('getConfig defaults', () => {
  it('returns default service name', () => {
    expect(getConfig().serviceName).toBe('provide-service');
  });

  it('returns default log level', () => {
    expect(getConfig().logLevel).toBe('info');
  });

  it('captureToWindow defaults to true', () => {
    expect(getConfig().captureToWindow).toBe(true);
  });

  it('otelEnabled defaults to true', () => {
    expect(getConfig().otelEnabled).toBe(true);
  });
});

describe('setupTelemetry', () => {
  it('overrides service name', () => {
    setupTelemetry({ serviceName: 'my-app' });
    expect(getConfig().serviceName).toBe('my-app');
  });

  it('overrides multiple fields', () => {
    setupTelemetry({ serviceName: 'svc', logLevel: 'debug', environment: 'staging' });
    const cfg = getConfig();
    expect(cfg.serviceName).toBe('svc');
    expect(cfg.logLevel).toBe('debug');
    expect(cfg.environment).toBe('staging');
  });

  it('preserves unset fields as defaults', () => {
    setupTelemetry({ serviceName: 'x' });
    expect(getConfig().otelEnabled).toBe(true);
    expect(getConfig().captureToWindow).toBe(true);
  });
});

describe('configFromEnv', () => {
  it('returns defaults when no env vars set', () => {
    const cfg = configFromEnv();
    expect(cfg.serviceName).toBe('undef-service');
    expect(cfg.environment).toBe('development');
  });

  it('reads UNDEF_TELEMETRY_SERVICE_NAME', () => {
    process.env['UNDEF_TELEMETRY_SERVICE_NAME'] = 'test-service';
    try {
      const cfg = configFromEnv();
      expect(cfg.serviceName).toBe('test-service');
    } finally {
      delete process.env['UNDEF_TELEMETRY_SERVICE_NAME'];
    }
  });

  it('reads UNDEF_LOG_LEVEL', () => {
    process.env['UNDEF_LOG_LEVEL'] = 'DEBUG';
    try {
      const cfg = configFromEnv();
      expect(cfg.logLevel).toBe('debug');
    } finally {
      delete process.env['UNDEF_LOG_LEVEL'];
    }
  });

  it('parses OTEL_EXPORTER_OTLP_HEADERS', () => {
    process.env['OTEL_EXPORTER_OTLP_HEADERS'] = 'x-api-key=abc,x-tenant=test';
    try {
      const cfg = configFromEnv();
      expect(cfg.otlpHeaders).toEqual({ 'x-api-key': 'abc', 'x-tenant': 'test' });
    } finally {
      delete process.env['OTEL_EXPORTER_OTLP_HEADERS'];
    }
  });

  it('nodeEnv returns undefined when process is undefined (browser-like environment)', () => {
    // Simulate a browser environment where process is not defined
    vi.stubGlobal('process', undefined);
    try {
      const cfg = configFromEnv();
      // All env-derived fields fall back to defaults when process is unavailable
      expect(cfg.serviceName).toBe('undef-service');
      expect(cfg.logLevel).toBe('info');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('nodeEnv returns undefined when process.env access throws', () => {
    // Simulate an environment where accessing process.env[key] throws
    vi.stubGlobal('process', {
      get env() {
        throw new Error('env access denied');
      },
    });
    try {
      const cfg = configFromEnv();
      // All env-derived fields fall back to defaults when process.env throws
      expect(cfg.serviceName).toBe('undef-service');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('configFromEnv — default values', () => {
  it('version defaults to unknown', () => {
    expect(configFromEnv().version).toBe('unknown');
  });

  it('consoleOutput defaults to false', () => {
    expect(configFromEnv().consoleOutput).toBe(false);
  });

  it('sanitizeFields defaults to empty array', () => {
    expect(configFromEnv().sanitizeFields).toEqual([]);
  });

  it('otelEnabled defaults to false', () => {
    expect(configFromEnv().otelEnabled).toBe(false);
  });
});

describe('configFromEnv — env var reads', () => {
  function withEnv(vars: Record<string, string>, fn: () => void): void {
    for (const [k, v] of Object.entries(vars)) process.env[k] = v;
    try {
      fn();
    } finally {
      for (const k of Object.keys(vars)) delete process.env[k];
    }
  }

  it('reads UNDEF_ENV', () => {
    withEnv({ UNDEF_ENV: 'production' }, () => {
      expect(configFromEnv().environment).toBe('production');
    });
  });

  it('reads UNDEF_VERSION', () => {
    withEnv({ UNDEF_VERSION: 'v2.3.4' }, () => {
      expect(configFromEnv().version).toBe('v2.3.4');
    });
  });

  it('UNDEF_VERSION overrides default (not AND-short-circuited)', () => {
    withEnv({ UNDEF_VERSION: 'v9.0.0' }, () => {
      expect(configFromEnv().version).toBe('v9.0.0');
    });
  });

  it('reads UNDEF_LOG_FORMAT=json', () => {
    withEnv({ UNDEF_LOG_FORMAT: 'json' }, () => {
      expect(configFromEnv().logFormat).toBe('json');
    });
  });

  it('reads UNDEF_LOG_FORMAT=pretty', () => {
    withEnv({ UNDEF_LOG_FORMAT: 'pretty' }, () => {
      expect(configFromEnv().logFormat).toBe('pretty');
    });
  });

  it('invalid UNDEF_LOG_FORMAT falls back to json default', () => {
    withEnv({ UNDEF_LOG_FORMAT: 'xml' }, () => {
      expect(configFromEnv().logFormat).toBe('json');
    });
  });

  it('empty UNDEF_LOG_FORMAT falls back to json default', () => {
    withEnv({ UNDEF_LOG_FORMAT: '' }, () => {
      expect(configFromEnv().logFormat).toBe('json');
    });
  });

  it('reads UNDEF_TRACE_ENABLED=true', () => {
    withEnv({ UNDEF_TRACE_ENABLED: 'true' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('UNDEF_TRACE_ENABLED=false does not enable otel', () => {
    withEnv({ UNDEF_TRACE_ENABLED: 'false' }, () => {
      expect(configFromEnv().otelEnabled).toBe(false);
    });
  });

  it('reads OTEL_EXPORTER_OTLP_ENDPOINT', () => {
    withEnv({ OTEL_EXPORTER_OTLP_ENDPOINT: 'http://collector:4318' }, () => {
      expect(configFromEnv().otlpEndpoint).toBe('http://collector:4318');
    });
  });
});

describe('_resetConfig', () => {
  it('restores service name to default after setupTelemetry', () => {
    setupTelemetry({ serviceName: 'custom-svc' });
    expect(getConfig().serviceName).toBe('custom-svc');
    _resetConfig();
    expect(getConfig().serviceName).toBe('provide-service');
  });

  it('restores logLevel to default', () => {
    setupTelemetry({ logLevel: 'error' });
    _resetConfig();
    expect(getConfig().logLevel).toBe('info');
  });
});

describe('version constant', () => {
  it('exports version as 0.4.0', () => {
    expect(version).toBe('0.4.0');
  });
});

describe('config — DEFAULTS.consoleOutput is true (kills BooleanLiteral mutation)', () => {
  it('consoleOutput defaults to true when not set', () => {
    _resetConfig();
    setupTelemetry({ serviceName: 'svc' });
    expect(getConfig().consoleOutput).toBe(true);
  });

  it('consoleOutput can be set to false', () => {
    _resetConfig();
    setupTelemetry({ serviceName: 'svc', consoleOutput: false });
    expect(getConfig().consoleOutput).toBe(false);
  });

  it('consoleOutput is true in DEFAULTS — getConfig() after reset returns true without setupTelemetry', () => {
    _resetConfig();
    expect(getConfig().consoleOutput).toBe(true);
  });
});

// ─── New field tests ────────────────────────────────────────────────────

function withEnv(vars: Record<string, string>, fn: () => void): void {
  for (const [k, v] of Object.entries(vars)) process.env[k] = v;
  try {
    fn();
  } finally {
    for (const k of Object.keys(vars)) delete process.env[k];
  }
}

describe('configFromEnv — logging extras', () => {
  it('logIncludeTimestamp defaults to true', () => {
    expect(configFromEnv().logIncludeTimestamp).toBe(true);
  });
  it('logIncludeTimestamp=false when env is "false"', () => {
    withEnv({ PROVIDE_LOG_INCLUDE_TIMESTAMP: 'false' }, () => {
      expect(configFromEnv().logIncludeTimestamp).toBe(false);
    });
  });
  it('logIncludeCaller defaults to true', () => {
    expect(configFromEnv().logIncludeCaller).toBe(true);
  });
  it('logIncludeCaller=false when env is "false"', () => {
    withEnv({ PROVIDE_LOG_INCLUDE_CALLER: 'false' }, () => {
      expect(configFromEnv().logIncludeCaller).toBe(false);
    });
  });
  it('logSanitize defaults to true', () => {
    expect(configFromEnv().logSanitize).toBe(true);
  });
  it('logSanitize=false when env is "false"', () => {
    withEnv({ PROVIDE_LOG_SANITIZE: 'false' }, () => {
      expect(configFromEnv().logSanitize).toBe(false);
    });
  });
  it('logCodeAttributes defaults to false', () => {
    expect(configFromEnv().logCodeAttributes).toBe(false);
  });
  it('logCodeAttributes=true when env is "true"', () => {
    withEnv({ PROVIDE_LOG_CODE_ATTRIBUTES: 'true' }, () => {
      expect(configFromEnv().logCodeAttributes).toBe(true);
    });
  });
  it('logModuleLevels defaults to empty object', () => {
    expect(configFromEnv().logModuleLevels).toEqual({});
  });
  it('logModuleLevels parses comma-separated module=level pairs', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: 'provide.server=DEBUG, asyncio=WARNING' }, () => {
      expect(configFromEnv().logModuleLevels).toEqual({
        'provide.server': 'DEBUG',
        asyncio: 'WARNING',
      });
    });
  });
  it('logModuleLevels ignores malformed entries', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: 'badentry,good=INFO' }, () => {
      expect(configFromEnv().logModuleLevels).toEqual({ good: 'INFO' });
    });
  });
  it('logModuleLevels ignores entries with empty mod or level', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: '=DEBUG,mod=,ok=WARN' }, () => {
      expect(configFromEnv().logModuleLevels).toEqual({ ok: 'WARN' });
    });
  });
});

describe('configFromEnv — tracing extras', () => {
  it('traceSampleRate defaults to 1.0', () => {
    expect(configFromEnv().traceSampleRate).toBe(1.0);
  });
  it('traceSampleRate reads env var', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: '0.5' }, () => {
      expect(configFromEnv().traceSampleRate).toBe(0.5);
    });
  });
  it('traceSampleRate falls back to default on NaN', () => {
    withEnv({ PROVIDE_TRACE_SAMPLE_RATE: 'abc' }, () => {
      expect(configFromEnv().traceSampleRate).toBe(1.0);
    });
  });
});

describe('configFromEnv — metrics', () => {
  it('metricsEnabled defaults to true', () => {
    expect(configFromEnv().metricsEnabled).toBe(true);
  });
  it('metricsEnabled=false when env is "false"', () => {
    withEnv({ PROVIDE_METRICS_ENABLED: 'false' }, () => {
      expect(configFromEnv().metricsEnabled).toBe(false);
    });
  });
});

describe('configFromEnv — per-signal sampling', () => {
  it('samplingLogsRate defaults to 1.0', () => {
    expect(configFromEnv().samplingLogsRate).toBe(1.0);
  });
  it('samplingLogsRate reads env var', () => {
    withEnv({ PROVIDE_SAMPLING_LOGS_RATE: '0.25' }, () => {
      expect(configFromEnv().samplingLogsRate).toBe(0.25);
    });
  });
  it('samplingLogsRate falls back on NaN', () => {
    withEnv({ PROVIDE_SAMPLING_LOGS_RATE: 'bad' }, () => {
      expect(configFromEnv().samplingLogsRate).toBe(1.0);
    });
  });
  it('samplingTracesRate defaults to 1.0', () => {
    expect(configFromEnv().samplingTracesRate).toBe(1.0);
  });
  it('samplingTracesRate reads env var', () => {
    withEnv({ PROVIDE_SAMPLING_TRACES_RATE: '0.1' }, () => {
      expect(configFromEnv().samplingTracesRate).toBe(0.1);
    });
  });
  it('samplingMetricsRate defaults to 1.0', () => {
    expect(configFromEnv().samplingMetricsRate).toBe(1.0);
  });
  it('samplingMetricsRate reads env var', () => {
    withEnv({ PROVIDE_SAMPLING_METRICS_RATE: '0.75' }, () => {
      expect(configFromEnv().samplingMetricsRate).toBe(0.75);
    });
  });
});

describe('configFromEnv — per-signal backpressure', () => {
  it('backpressureLogsMaxsize defaults to 0', () => {
    expect(configFromEnv().backpressureLogsMaxsize).toBe(0);
  });
  it('backpressureLogsMaxsize reads env var', () => {
    withEnv({ PROVIDE_BACKPRESSURE_LOGS_MAXSIZE: '500' }, () => {
      expect(configFromEnv().backpressureLogsMaxsize).toBe(500);
    });
  });
  it('backpressureLogsMaxsize falls back on NaN', () => {
    withEnv({ PROVIDE_BACKPRESSURE_LOGS_MAXSIZE: 'nope' }, () => {
      expect(configFromEnv().backpressureLogsMaxsize).toBe(0);
    });
  });
  it('backpressureTracesMaxsize defaults to 0', () => {
    expect(configFromEnv().backpressureTracesMaxsize).toBe(0);
  });
  it('backpressureTracesMaxsize reads env var', () => {
    withEnv({ PROVIDE_BACKPRESSURE_TRACES_MAXSIZE: '1000' }, () => {
      expect(configFromEnv().backpressureTracesMaxsize).toBe(1000);
    });
  });
  it('backpressureMetricsMaxsize defaults to 0', () => {
    expect(configFromEnv().backpressureMetricsMaxsize).toBe(0);
  });
  it('backpressureMetricsMaxsize reads env var', () => {
    withEnv({ PROVIDE_BACKPRESSURE_METRICS_MAXSIZE: '2000' }, () => {
      expect(configFromEnv().backpressureMetricsMaxsize).toBe(2000);
    });
  });
});

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

describe('DEFAULTS — new boolean fields kill mutations', () => {
  it('logIncludeTimestamp default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().logIncludeTimestamp).toBe(true);
  });
  it('logIncludeCaller default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().logIncludeCaller).toBe(true);
  });
  it('logSanitize default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().logSanitize).toBe(true);
  });
  it('logCodeAttributes default is false (not true)', () => {
    _resetConfig();
    expect(getConfig().logCodeAttributes).toBe(false);
  });
  it('metricsEnabled default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().metricsEnabled).toBe(true);
  });
  it('exporterLogsFailOpen default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().exporterLogsFailOpen).toBe(true);
  });
  it('exporterTracesFailOpen default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().exporterTracesFailOpen).toBe(true);
  });
  it('exporterMetricsFailOpen default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().exporterMetricsFailOpen).toBe(true);
  });
  it('sloEnableRedMetrics default is false (not true)', () => {
    _resetConfig();
    expect(getConfig().sloEnableRedMetrics).toBe(false);
  });
  it('sloEnableUseMetrics default is false (not true)', () => {
    _resetConfig();
    expect(getConfig().sloEnableUseMetrics).toBe(false);
  });
  it('exporterLogsTimeoutMs default is 10000 (not 0)', () => {
    _resetConfig();
    expect(getConfig().exporterLogsTimeoutMs).toBe(10000);
  });
  it('exporterTracesTimeoutMs default is 10000 (not 0)', () => {
    _resetConfig();
    expect(getConfig().exporterTracesTimeoutMs).toBe(10000);
  });
  it('exporterMetricsTimeoutMs default is 10000 (not 0)', () => {
    _resetConfig();
    expect(getConfig().exporterMetricsTimeoutMs).toBe(10000);
  });
  it('securityMaxAttrValueLength default is 1024', () => {
    _resetConfig();
    expect(getConfig().securityMaxAttrValueLength).toBe(1024);
  });
  it('securityMaxAttrCount default is 64', () => {
    _resetConfig();
    expect(getConfig().securityMaxAttrCount).toBe(64);
  });
});
