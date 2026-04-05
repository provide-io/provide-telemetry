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

  it('preserves = in header values (split on first = only)', () => {
    process.env['OTEL_EXPORTER_OTLP_HEADERS'] = 'Authorization=Bearer=token';
    try {
      const cfg = configFromEnv();
      expect(cfg.otlpHeaders).toEqual({ Authorization: 'Bearer=token' });
    } finally {
      delete process.env['OTEL_EXPORTER_OTLP_HEADERS'];
    }
  });

  it('filters out empty keys from header parsing', () => {
    process.env['OTEL_EXPORTER_OTLP_HEADERS'] = '=value,x-key=ok';
    try {
      const cfg = configFromEnv();
      expect(cfg.otlpHeaders).toEqual({ 'x-key': 'ok' });
      expect('' in (cfg.otlpHeaders ?? {})).toBe(false);
    } finally {
      delete process.env['OTEL_EXPORTER_OTLP_HEADERS'];
    }
  });

  it('URL-decodes OTLP header keys and values from env', () => {
    process.env['OTEL_EXPORTER_OTLP_HEADERS'] =
      'Authorization=Bearer%20token%3D123,X-Custom%20Key=value%20with%20spaces';
    try {
      const cfg = configFromEnv();
      expect(cfg.otlpHeaders).toEqual({
        Authorization: 'Bearer token=123',
        'X-Custom Key': 'value with spaces',
      });
    } finally {
      delete process.env['OTEL_EXPORTER_OTLP_HEADERS'];
    }
  });

  it('skips malformed OTLP header pairs from env', () => {
    process.env['OTEL_EXPORTER_OTLP_HEADERS'] = 'badpair,x-key=ok';
    try {
      const cfg = configFromEnv();
      expect(cfg.otlpHeaders).toEqual({ 'x-key': 'ok' });
      expect(cfg.otlpHeaders).not.toHaveProperty('badpair');
    } finally {
      delete process.env['OTEL_EXPORTER_OTLP_HEADERS'];
    }
  });

  it('skips invalid URL-encoded OTLP header pairs from env', () => {
    process.env['OTEL_EXPORTER_OTLP_HEADERS'] = 'bad=%ZZ,x-key=ok';
    try {
      const cfg = configFromEnv();
      expect(cfg.otlpHeaders).toEqual({ 'x-key': 'ok' });
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

// ─── applyConfigPolicies integration tests ─────────────────────────────

describe('setupTelemetry applies sampling policies', () => {
  it('applies custom samplingLogsRate', () => {
    setupTelemetry({ samplingLogsRate: 0.5 });
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.5);
  });

  it('applies custom samplingTracesRate', () => {
    setupTelemetry({ samplingTracesRate: 0.3 });
    expect(getSamplingPolicy('traces').defaultRate).toBe(0.3);
  });

  it('applies custom samplingMetricsRate', () => {
    setupTelemetry({ samplingMetricsRate: 0.8 });
    expect(getSamplingPolicy('metrics').defaultRate).toBe(0.8);
  });

  it('applies default sampling rates (1.0) when no overrides', () => {
    setupTelemetry();
    expect(getSamplingPolicy('logs').defaultRate).toBe(1.0);
    expect(getSamplingPolicy('traces').defaultRate).toBe(1.0);
    expect(getSamplingPolicy('metrics').defaultRate).toBe(1.0);
  });
});

describe('setupTelemetry applies backpressure policies', () => {
  it('applies custom backpressureTracesMaxsize', () => {
    setupTelemetry({ backpressureTracesMaxsize: 64 });
    expect(getQueuePolicy().maxTraces).toBe(64);
  });

  it('applies custom backpressureLogsMaxsize', () => {
    setupTelemetry({ backpressureLogsMaxsize: 100 });
    expect(getQueuePolicy().maxLogs).toBe(100);
  });

  it('applies custom backpressureMetricsMaxsize', () => {
    setupTelemetry({ backpressureMetricsMaxsize: 200 });
    expect(getQueuePolicy().maxMetrics).toBe(200);
  });

  it('applies default backpressure (0 = unbounded) when no overrides', () => {
    setupTelemetry();
    const policy = getQueuePolicy();
    expect(policy.maxLogs).toBe(0);
    expect(policy.maxTraces).toBe(0);
    expect(policy.maxMetrics).toBe(0);
  });
});

describe('setupTelemetry applies exporter resilience policies', () => {
  it('applies custom exporterLogsRetries', () => {
    setupTelemetry({ exporterLogsRetries: 3 });
    expect(getExporterPolicy('logs').retries).toBe(3);
  });

  it('applies custom exporterLogsBackoffMs', () => {
    setupTelemetry({ exporterLogsBackoffMs: 500 });
    expect(getExporterPolicy('logs').backoffMs).toBe(500);
  });

  it('applies custom exporterLogsTimeoutMs', () => {
    setupTelemetry({ exporterLogsTimeoutMs: 5000 });
    expect(getExporterPolicy('logs').timeoutMs).toBe(5000);
  });

  it('applies custom exporterLogsFailOpen', () => {
    setupTelemetry({ exporterLogsFailOpen: false });
    expect(getExporterPolicy('logs').failOpen).toBe(false);
  });

  it('applies custom exporterTracesRetries', () => {
    setupTelemetry({ exporterTracesRetries: 5 });
    expect(getExporterPolicy('traces').retries).toBe(5);
  });

  it('applies custom exporterTracesBackoffMs', () => {
    setupTelemetry({ exporterTracesBackoffMs: 1000 });
    expect(getExporterPolicy('traces').backoffMs).toBe(1000);
  });

  it('applies custom exporterTracesTimeoutMs', () => {
    setupTelemetry({ exporterTracesTimeoutMs: 20000 });
    expect(getExporterPolicy('traces').timeoutMs).toBe(20000);
  });

  it('applies custom exporterTracesFailOpen', () => {
    setupTelemetry({ exporterTracesFailOpen: false });
    expect(getExporterPolicy('traces').failOpen).toBe(false);
  });

  it('applies custom exporterMetricsRetries', () => {
    setupTelemetry({ exporterMetricsRetries: 2 });
    expect(getExporterPolicy('metrics').retries).toBe(2);
  });

  it('applies custom exporterMetricsBackoffMs', () => {
    setupTelemetry({ exporterMetricsBackoffMs: 750 });
    expect(getExporterPolicy('metrics').backoffMs).toBe(750);
  });

  it('applies custom exporterMetricsTimeoutMs', () => {
    setupTelemetry({ exporterMetricsTimeoutMs: 15000 });
    expect(getExporterPolicy('metrics').timeoutMs).toBe(15000);
  });

  it('applies custom exporterMetricsFailOpen', () => {
    setupTelemetry({ exporterMetricsFailOpen: false });
    expect(getExporterPolicy('metrics').failOpen).toBe(false);
  });

  it('applies default exporter policies when no overrides', () => {
    setupTelemetry();
    for (const signal of ['logs', 'traces', 'metrics']) {
      const policy = getExporterPolicy(signal);
      expect(policy.retries).toBe(0);
      expect(policy.backoffMs).toBe(0);
      expect(policy.timeoutMs).toBe(10000);
      expect(policy.failOpen).toBe(true);
    }
  });
});

describe('applyConfigPolicies standalone', () => {
  it('can be called directly with a full config', () => {
    const cfg = { ...configFromEnv(), samplingLogsRate: 0.1, backpressureLogsMaxsize: 42 };
    applyConfigPolicies(cfg);
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.1);
    expect(getQueuePolicy().maxLogs).toBe(42);
  });
});

// ─── Mutation-killing tests ─────────────────────────────────────────────

describe('DEFAULTS — strictSchema and requiredLogKeys kill mutations', () => {
  it('strictSchema default is false (not true) via _resetConfig', () => {
    _resetConfig();
    expect(getConfig().strictSchema).toBe(false);
  });

  it('requiredLogKeys default is empty array (not populated) via _resetConfig', () => {
    _resetConfig();
    expect(getConfig().requiredLogKeys).toEqual([]);
    expect(getConfig().requiredLogKeys).toHaveLength(0);
  });
});

describe('envNumber — undefined env var returns fallback', () => {
  it('traceSampleRate returns fallback (1.0) when env var is not set', () => {
    // PROVIDE_TRACE_SAMPLE_RATE is not set, so envNumber should return fallback
    delete process.env['PROVIDE_TRACE_SAMPLE_RATE'];
    const cfg = configFromEnv();
    expect(cfg.traceSampleRate).toBe(1.0);
  });

  it('backpressureLogsMaxsize returns fallback (0) when env var is not set', () => {
    delete process.env['PROVIDE_BACKPRESSURE_LOGS_MAXSIZE'];
    const cfg = configFromEnv();
    expect(cfg.backpressureLogsMaxsize).toBe(0);
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
      // "mod:DEBUG" has no '=' so it should be skipped
      expect(levels).toEqual({ mod2: 'WARN' });
    });
  });

  it('trims keys and values around the = sign', () => {
    withEnv({ PROVIDE_LOG_MODULE_LEVELS: ' mymod = INFO , other = DEBUG ' }, () => {
      const levels = configFromEnv().logModuleLevels;
      expect(levels['mymod']).toBe('INFO');
      expect(levels['other']).toBe('DEBUG');
      // Ensure no untrimmed keys exist
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
      // After trim, the middle entry is empty string, filtered by Boolean
      expect(keys).toEqual(['event', 'action']);
    });
  });
});

describe('setupTelemetry — emergency fallback', () => {
  it('does not throw when applyConfigPolicies fails with Error', async () => {
    const samplingModule = await import('../src/sampling');
    vi.spyOn(samplingModule, 'setSamplingPolicy').mockImplementation(() => {
      throw new Error('policy explosion');
    });
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(() => setupTelemetry()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('policy explosion'));
    warnSpy.mockRestore();
    vi.restoreAllMocks();
  });

  it('does not throw when applyConfigPolicies fails with non-Error', async () => {
    const samplingModule = await import('../src/sampling');
    vi.spyOn(samplingModule, 'setSamplingPolicy').mockImplementation(() => {
      // eslint-disable-next-line no-throw-literal
      throw 'string-failure';
    });
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(() => setupTelemetry()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('string-failure'));
    warnSpy.mockRestore();
    vi.restoreAllMocks();
  });
});
