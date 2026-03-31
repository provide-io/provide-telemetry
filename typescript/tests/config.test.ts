// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, configFromEnv, getConfig, setupTelemetry, version } from '../src/config';

afterEach(() => {
  _resetConfig();
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

  it('otelEnabled defaults to false', () => {
    expect(getConfig().otelEnabled).toBe(false);
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
    expect(getConfig().otelEnabled).toBe(false);
    expect(getConfig().captureToWindow).toBe(true);
  });
});

describe('configFromEnv', () => {
  it('returns defaults when no env vars set', () => {
    const cfg = configFromEnv();
    expect(cfg.serviceName).toBe('provide-service');
    expect(cfg.environment).toBe('development');
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

  it('nodeEnv returns undefined when process is undefined (browser-like environment)', () => {
    // Simulate a browser environment where process is not defined
    vi.stubGlobal('process', undefined);
    try {
      const cfg = configFromEnv();
      // All env-derived fields fall back to defaults when process is unavailable
      expect(cfg.serviceName).toBe('provide-service');
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
      expect(cfg.serviceName).toBe('provide-service');
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

  it('reads PROVIDE_ENV', () => {
    withEnv({ PROVIDE_ENV: 'production' }, () => {
      expect(configFromEnv().environment).toBe('production');
    });
  });

  it('reads PROVIDE_VERSION', () => {
    withEnv({ PROVIDE_VERSION: 'v2.3.4' }, () => {
      expect(configFromEnv().version).toBe('v2.3.4');
    });
  });

  it('PROVIDE_VERSION overrides default (not AND-short-circuited)', () => {
    withEnv({ PROVIDE_VERSION: 'v9.0.0' }, () => {
      expect(configFromEnv().version).toBe('v9.0.0');
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

  it('invalid PROVIDE_LOG_FORMAT falls back to json default', () => {
    withEnv({ PROVIDE_LOG_FORMAT: 'xml' }, () => {
      expect(configFromEnv().logFormat).toBe('json');
    });
  });

  it('empty PROVIDE_LOG_FORMAT falls back to json default', () => {
    withEnv({ PROVIDE_LOG_FORMAT: '' }, () => {
      expect(configFromEnv().logFormat).toBe('json');
    });
  });

  it('reads PROVIDE_TRACE_ENABLED=true', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'true' }, () => {
      expect(configFromEnv().otelEnabled).toBe(true);
    });
  });

  it('PROVIDE_TRACE_ENABLED=false does not enable otel', () => {
    withEnv({ PROVIDE_TRACE_ENABLED: 'false' }, () => {
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
  it('exports version as 0.4.1', () => {
    expect(version).toBe('0.4.2');
  });
});

describe('config — DEFAULTS.consoleOutput is false (kills BooleanLiteral mutation)', () => {
  it('consoleOutput defaults to false when not set', () => {
    _resetConfig();
    setupTelemetry({ serviceName: 'svc' });
    expect(getConfig().consoleOutput).toBe(false);
  });

  it('consoleOutput can be set to true', () => {
    _resetConfig();
    setupTelemetry({ serviceName: 'svc', consoleOutput: true });
    expect(getConfig().consoleOutput).toBe(true);
  });

  it('consoleOutput is false in DEFAULTS — getConfig() after reset returns false without setupTelemetry', () => {
    // This test reads DEFAULTS directly via _resetConfig() without calling setupTelemetry/configFromEnv.
    // Kills: BooleanLiteral mutation of DEFAULTS.consoleOutput false→true
    _resetConfig();
    expect(getConfig().consoleOutput).toBe(false);
  });
});
