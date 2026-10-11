// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/** Prometheus metrics config: the shared cases in spec/prometheus_fixtures.yaml plus edges. */

import { afterEach, describe, expect, it } from 'vitest';
import { configFromEnv, DEFAULTS, getConfig, setupTelemetry, _resetConfig } from '../src/config.js';
import {
  envStr,
  otlpMetricsReaderEnabled,
  parseMetricsExporters,
  parsePort,
  prometheusListenerEnabled,
  prometheusReaderEnabled,
  validateExporters,
  validatePath,
  validatePort,
} from '../src/config-prometheus.js';
import { ConfigurationError } from '../src/exceptions.js';
import type { TelemetryConfig } from '../src/config.js';
import { promFixtures, withEnv } from './support/prometheus-fixtures.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
type Case = Record<string, any>;

function readers(cfg: TelemetryConfig): string[] {
  const out: string[] = [];
  if (otlpMetricsReaderEnabled(cfg)) out.push('otlp');
  if (prometheusReaderEnabled(cfg)) out.push('prometheus');
  return out;
}

afterEach(() => {
  _resetConfig();
});

describe('exporter_selection fixtures', () => {
  for (const c of promFixtures['exporter_selection'] as Case[]) {
    it(c['id'] as string, () => {
      withEnv(c['env'] as Record<string, string>, () => {
        if (c['error']) {
          expect(() => configFromEnv()).toThrow(ConfigurationError);
          return;
        }
        const cfg = configFromEnv();
        expect(readers(cfg)).toEqual(c['exporters']);
        expect(prometheusListenerEnabled(cfg)).toBe(c['listener']);
      });
    });
  }
});

const SINGLE: [string, string, keyof TelemetryConfig, string][] = [
  ['listener_path', 'PROVIDE_METRICS_PROMETHEUS_PATH', 'prometheusPath', 'path'],
  ['listener_port', 'OTEL_EXPORTER_PROMETHEUS_PORT', 'prometheusPort', 'port'],
  [
    'translation_strategy',
    'PROVIDE_METRICS_PROMETHEUS_TRANSLATION',
    'prometheusTranslation',
    'strategy',
  ],
];

for (const [section, envKey, field, wantKey] of SINGLE) {
  describe(`${section} fixtures`, () => {
    for (const c of promFixtures[section] as Case[]) {
      it(c['id'] as string, () => {
        const env: Record<string, string> =
          c['value'] === null ? {} : { [envKey]: c['value'] as string };
        withEnv(env, () => {
          if (c['error']) {
            expect(() => configFromEnv()).toThrow(ConfigurationError);
            return;
          }
          expect(configFromEnv()[field]).toBe(c[wantKey]);
        });
      });
    }
  });
}

describe('Prometheus env parsing', () => {
  it('reads every key, trimming and lowercasing LISTEN', () => {
    const cfg = withEnv(
      {
        OTEL_METRICS_EXPORTER: 'prometheus',
        OTEL_EXPORTER_PROMETHEUS_HOST: ' 0.0.0.0 ',
        OTEL_EXPORTER_PROMETHEUS_PORT: ' 9100 ',
        PROVIDE_METRICS_PROMETHEUS_LISTEN: ' AUTO ',
        PROVIDE_METRICS_PROMETHEUS_PATH: '/m',
        PROVIDE_METRICS_PROMETHEUS_TRANSLATION: 'NoTranslation',
        PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS: 'true',
        PROVIDE_METRICS_PROMETHEUS_TARGET_INFO: 'false',
        PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG: ' /etc/web.yml ',
        PROVIDE_METRICS_HEALTH_OTLP: 'true',
      },
      () => configFromEnv(),
    );
    expect(cfg.metricsExporters).toEqual(['prometheus']);
    expect(cfg.prometheusHost).toBe('0.0.0.0');
    expect(cfg.prometheusPort).toBe(9100);
    expect(cfg.prometheusListen).toBe('auto');
    expect(cfg.prometheusPath).toBe('/m');
    expect(cfg.prometheusTranslation).toBe('NoTranslation');
    expect(cfg.prometheusScopeLabels).toBe(true);
    expect(cfg.prometheusTargetInfo).toBe(false);
    expect(cfg.prometheusWebConfig).toBe('/etc/web.yml');
    expect(cfg.metricsHealthOtlp).toBe(true);
  });

  it('defaults match the spec', () => {
    const cfg = withEnv({}, () => configFromEnv());
    expect(cfg.metricsExporters).toEqual(['otlp']);
    expect(cfg.prometheusHost).toBe('127.0.0.1');
    expect(cfg.prometheusPort).toBe(9464);
    expect(cfg.prometheusListen).toBe('false');
    expect(cfg.prometheusPath).toBe('/metrics');
    expect(cfg.prometheusTranslation).toBe('UnderscoreEscapingWithSuffixes');
    expect(cfg.prometheusScopeLabels).toBe(false);
    expect(cfg.prometheusTargetInfo).toBe(true);
    expect(cfg.prometheusWebConfig).toBe('');
    expect(cfg.metricsHealthOtlp).toBe(false);
    expect(DEFAULTS.metricsExporters).toEqual(['otlp']);
  });

  it('a blank host means the default host', () => {
    expect(
      withEnv({ OTEL_EXPORTER_PROMETHEUS_HOST: '  ' }, () => configFromEnv()).prometheusHost,
    ).toBe('127.0.0.1');
  });

  it('rejects an invalid boolean for the switches', () => {
    for (const key of [
      'PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS',
      'PROVIDE_METRICS_PROMETHEUS_TARGET_INFO',
      'PROVIDE_METRICS_HEALTH_OTLP',
    ]) {
      expect(() => withEnv({ [key]: 'maybe' }, () => configFromEnv())).toThrow(key);
    }
  });

  it('names the variable in each error', () => {
    expect(() => parseMetricsExporters('otlp,statsd')).toThrow(
      'OTEL_METRICS_EXPORTER: unknown exporter "statsd"',
    );
    expect(() => parseMetricsExporters('none,otlp')).toThrow(
      'OTEL_METRICS_EXPORTER: none cannot be combined with other exporters',
    );
    expect(() => parsePort('http')).toThrow(
      'OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got "http"',
    );
    expect(() => parsePort('70000')).toThrow(
      'OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got 70000',
    );
    expect(() => validatePath('x')).toThrow(
      'PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got "x"',
    );
    expect(() =>
      withEnv({ PROVIDE_METRICS_PROMETHEUS_LISTEN: 'yes' }, () => configFromEnv()),
    ).toThrow('PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got "yes"');
    expect(() =>
      withEnv({ PROVIDE_METRICS_PROMETHEUS_TRANSLATION: 'Legacy' }, () => configFromEnv()),
    ).toThrow('PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy "Legacy"');
  });

  it('parses ports at the edges and with a sign', () => {
    expect(parsePort(undefined)).toBe(9464);
    expect(parsePort('65535')).toBe(65535);
    expect(parsePort('+80')).toBe(80);
    expect(() => parsePort('8.5')).toThrow(ConfigurationError);
    expect(() => parsePort('1e3')).toThrow(ConfigurationError);
    expect(() => parsePort(' 12 34 ')).toThrow(ConfigurationError);
    expect(() => validatePort(1.5)).toThrow(ConfigurationError);
    expect(() => validatePort(-1)).toThrow(ConfigurationError);
    expect(() => validatePort(65536)).toThrow(ConfigurationError);
    expect(() => validatePort(0)).not.toThrow();
    expect(() => validatePort(65535)).not.toThrow();
  });

  it('parses exporters from undefined, blanks and mixed case', () => {
    expect(parseMetricsExporters(undefined)).toEqual(['otlp']);
    expect(parseMetricsExporters(' , ')).toEqual(['otlp']);
    expect(parseMetricsExporters('NONE')).toEqual([]);
    expect(parseMetricsExporters('none,none')).toEqual([]);
  });

  it('validates path characters one at a time', () => {
    expect(() => validatePath('/a?b')).toThrow(ConfigurationError);
    expect(() => validatePath('/a#b')).toThrow(ConfigurationError);
    expect(() => validatePath('/a/b')).not.toThrow();
  });

  it('envStr trims and falls back', () => {
    expect(envStr(undefined, 'd')).toBe('d');
    expect(envStr('  ', 'd')).toBe('d');
    expect(envStr(' v ', 'd')).toBe('v');
  });
});

describe('Prometheus config validation in setupTelemetry', () => {
  it('rejects an exporter built in code that the env parser would refuse', () => {
    expect(() => validateExporters(['statsd'])).toThrow(
      'metricsExporters: unknown exporter "statsd"',
    );
    expect(() => validateExporters(['none'])).toThrow(ConfigurationError);
    expect(() => validateExporters(['otlp', 'prometheus'])).not.toThrow();
    expect(() => withEnv({}, () => setupTelemetry({ metricsExporters: ['statsd'] }))).toThrow(
      ConfigurationError,
    );
  });

  it.each([
    [{ prometheusListen: 'sometimes' }],
    [{ prometheusPort: 70000 }],
    [{ prometheusPath: 'metrics' }],
    [{ prometheusTranslation: 'Legacy' }],
  ] as Partial<TelemetryConfig>[][])('rejects %o', (override) => {
    expect(() => withEnv({}, () => setupTelemetry(override))).toThrow(ConfigurationError);
  });

  it('accepts a valid programmatic config', () => {
    withEnv({}, () =>
      setupTelemetry({
        metricsExporters: ['prometheus'],
        prometheusListen: 'true',
        prometheusPort: 0,
      }),
    );
    expect(getConfig().metricsExporters).toEqual(['prometheus']);
  });

  it('_resetConfig gives a fresh exporter list', () => {
    getConfig().metricsExporters.push('prometheus');
    _resetConfig();
    expect(getConfig().metricsExporters).toEqual(['otlp']);
  });
});

describe('derived switches', () => {
  const base = { ...DEFAULTS, metricsExporters: ['otlp'] };

  it('listener: true starts, auto follows the exporter, false never', () => {
    expect(prometheusListenerEnabled({ ...base, prometheusListen: 'true' })).toBe(true);
    expect(prometheusListenerEnabled({ ...base, prometheusListen: 'auto' })).toBe(false);
    expect(
      prometheusListenerEnabled({
        ...base,
        prometheusListen: 'auto',
        metricsExporters: ['prometheus'],
      }),
    ).toBe(true);
    expect(
      prometheusListenerEnabled({
        ...base,
        prometheusListen: 'false',
        metricsExporters: ['prometheus'],
      }),
    ).toBe(false);
    expect(
      prometheusListenerEnabled({ ...base, prometheusListen: 'true', metricsEnabled: false }),
    ).toBe(false);
  });

  it('reader and otlp switch off with metrics', () => {
    const off = { ...base, metricsEnabled: false, metricsExporters: ['otlp', 'prometheus'] };
    expect(prometheusReaderEnabled(off)).toBe(false);
    expect(otlpMetricsReaderEnabled(off)).toBe(false);
    expect(prometheusReaderEnabled({ ...base, metricsExporters: ['prometheus'] })).toBe(true);
    expect(otlpMetricsReaderEnabled({ ...base, metricsExporters: [] })).toBe(false);
  });
});
