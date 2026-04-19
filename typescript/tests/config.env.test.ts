// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
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

describe('configFromEnv', () => {
  it('returns defaults when no env vars set', () => {
    const cfg = configFromEnv();
    expect(cfg.serviceName).toBe('provide-service');
    expect(cfg.environment).toBe('dev');
  });

  it('reads PROVIDE_TELEMETRY_SERVICE_NAME', () => {
    process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] = 'test-service';
    try {
      const cfg = configFromEnv();
      expect(cfg.serviceName).toBe('test-service');
    } finally {
      delete process.env['PROVIDE_TELEMETRY_SERVICE_NAME'];
    }
  });

  it('reads PROVIDE_LOG_LEVEL', () => {
    process.env['PROVIDE_LOG_LEVEL'] = 'DEBUG';
    try {
      const cfg = configFromEnv();
      expect(cfg.logLevel).toBe('debug');
    } finally {
      delete process.env['PROVIDE_LOG_LEVEL'];
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
    vi.stubGlobal('process', undefined);
    try {
      const cfg = configFromEnv();
      expect(cfg.serviceName).toBe('provide-service');
      expect(cfg.logLevel).toBe('info');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('nodeEnv returns undefined when process.env access throws', () => {
    vi.stubGlobal('process', {
      get env() {
        throw new Error('env access denied');
      },
    });
    try {
      const cfg = configFromEnv();
      expect(cfg.serviceName).toBe('provide-service');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('configFromEnv — default values', () => {
  it('version defaults to 0.0.0', () => {
    expect(configFromEnv().version).toBe('0.0.0');
  });

  it('consoleOutput defaults to true', () => {
    expect(configFromEnv().consoleOutput).toBe(true);
  });

  it('sanitizeFields defaults to empty array', () => {
    expect(configFromEnv().sanitizeFields).toEqual([]);
  });

  it('otelEnabled defaults to true', () => {
    expect(configFromEnv().otelEnabled).toBe(true);
  });

  it('tracingEnabled defaults to true', () => {
    expect(configFromEnv().tracingEnabled).toBe(true);
  });
});

describe('configFromEnv — env var reads', () => {
  it('reads PROVIDE_ENV', () => {
    withEnv({ PROVIDE_ENV: 'production' }, () => {
      expect(configFromEnv().environment).toBe('production');
    });
  });

  it('PROVIDE_TELEMETRY_ENV takes priority over PROVIDE_ENV', () => {
    withEnv({ PROVIDE_TELEMETRY_ENV: 'staging', PROVIDE_ENV: 'production' }, () => {
      expect(configFromEnv().environment).toBe('staging');
    });
  });

  it('reads PROVIDE_VERSION', () => {
    withEnv({ PROVIDE_VERSION: 'v2.3.4' }, () => {
      expect(configFromEnv().version).toBe('v2.3.4');
    });
  });

  it('PROVIDE_TELEMETRY_VERSION takes priority over PROVIDE_VERSION', () => {
    withEnv({ PROVIDE_TELEMETRY_VERSION: 'v5.0.0', PROVIDE_VERSION: 'v2.3.4' }, () => {
      expect(configFromEnv().version).toBe('v5.0.0');
    });
  });

  it('PROVIDE_VERSION overrides default (not AND-short-circuited)', () => {
    withEnv({ PROVIDE_VERSION: 'v9.0.0' }, () => {
      expect(configFromEnv().version).toBe('v9.0.0');
    });
  });

  it('strictSchema defaults to false', () => {
    expect(configFromEnv().strictSchema).toBe(false);
  });

  it('PROVIDE_TELEMETRY_STRICT_SCHEMA=true enables strictSchema', () => {
    withEnv({ PROVIDE_TELEMETRY_STRICT_SCHEMA: 'true' }, () => {
      expect(configFromEnv().strictSchema).toBe(true);
    });
  });

  it('PROVIDE_TELEMETRY_STRICT_EVENT_NAME=true enables strictEventName without forcing strictSchema', () => {
    withEnv(
      { PROVIDE_TELEMETRY_STRICT_SCHEMA: 'false', PROVIDE_TELEMETRY_STRICT_EVENT_NAME: 'true' },
      () => {
        const cfg = configFromEnv();
        expect(cfg.strictSchema).toBe(false);
        expect(cfg.strictEventName).toBe(true);
      },
    );
  });

  it('requiredLogKeys defaults to empty array', () => {
    expect(configFromEnv().requiredLogKeys).toEqual([]);
  });

  it('PROVIDE_TELEMETRY_REQUIRED_KEYS parses comma-separated keys', () => {
    withEnv({ PROVIDE_TELEMETRY_REQUIRED_KEYS: 'event, user_id , action' }, () => {
      expect(configFromEnv().requiredLogKeys).toEqual(['event', 'user_id', 'action']);
    });
  });

  it('reads PROVIDE_LOG_FORMAT=json', () => {
    withEnv({ PROVIDE_LOG_FORMAT: 'json' }, () => {
      expect(configFromEnv().logFormat).toBe('json');
    });
  });

  it('reads PROVIDE_LOG_FORMAT=pretty', () => {
    withEnv({ PROVIDE_LOG_FORMAT: 'pretty' }, () => {
      expect(configFromEnv().logFormat).toBe('pretty');
    });
  });

  it('reads PROVIDE_LOG_FORMAT=console', () => {
    withEnv({ PROVIDE_LOG_FORMAT: 'console' }, () => {
      expect(configFromEnv().logFormat).toBe('console');
    });
  });

  it('invalid PROVIDE_LOG_FORMAT falls back to console default', () => {
    withEnv({ PROVIDE_LOG_FORMAT: 'xml' }, () => {
      expect(configFromEnv().logFormat).toBe('console');
    });
  });

  it('empty PROVIDE_LOG_FORMAT falls back to console default', () => {
    withEnv({ PROVIDE_LOG_FORMAT: '' }, () => {
      expect(configFromEnv().logFormat).toBe('console');
    });
  });

  it('reads PROVIDE_TRACE_ENABLED=true', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'true' }, () => {
      expect(configFromEnv().tracingEnabled).toBe(true);
    });
  });

  it('PROVIDE_TRACE_ENABLED=false disables tracing without disabling OTEL registration', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'false' }, () => {
      const cfg = configFromEnv();
      expect(cfg.tracingEnabled).toBe(false);
      expect(cfg.otelEnabled).toBe(true);
    });
  });

  it('boolean env aliases are parsed consistently', () => {
    withEnv(
      {
        PROVIDE_TRACE_ENABLED: 'yes',
        PROVIDE_METRICS_ENABLED: 'off',
        PROVIDE_LOG_INCLUDE_TIMESTAMP: ' ',
      },
      () => {
        const cfg = configFromEnv();
        expect(cfg.tracingEnabled).toBe(true);
        expect(cfg.metricsEnabled).toBe(false);
        expect(cfg.logIncludeTimestamp).toBe(true);
      },
    );
  });

  it('covers all accepted boolean env aliases', () => {
    for (const truthy of ['1', 'true', 'yes', 'on']) {
      withEnv({ PROVIDE_TRACE_ENABLED: truthy }, () => {
        expect(configFromEnv().tracingEnabled).toBe(true);
      });
    }
    for (const falsy of ['0', 'false', 'no', 'off']) {
      withEnv({ PROVIDE_METRICS_ENABLED: falsy }, () => {
        expect(configFromEnv().metricsEnabled).toBe(false);
      });
    }
  });

  it('invalid boolean env values throw ConfigurationError', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'invalid-boolean' }, () => {
      expect(() => configFromEnv()).toThrow(ConfigurationError);
    });
  });

  it('reads OTEL_EXPORTER_OTLP_ENDPOINT', () => {
    withEnv({ OTEL_EXPORTER_OTLP_ENDPOINT: 'http://collector:4318' }, () => {
      expect(configFromEnv().otlpEndpoint).toBe('http://collector:4318');
    });
  });
});

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

// Exporter resilience, SLO, PII, security, OTLP headers, envNumber/envSecondsToMs,
// parseModuleLevels, and requiredLogKeys tests live in config.resilience.test.ts
