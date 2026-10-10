// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * The Prometheus modules' module-level tables, checked on a fresh load.
 *
 * Other test files load these modules once, at import. Some suites reload the
 * whole graph inside a test, which makes Stryker treat module-level constants
 * as covered per test, and then only a test that itself reloads the module can
 * see a mutated constant. Each test here re-imports inside its own body and
 * checks a table (status reasons, health families, web config keys, bcrypt
 * format, fixed responses) through behaviour.
 */

import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import bcrypt from 'bcryptjs';
import { stringify } from 'yaml';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Pki } from './support/pki.js';
import { promFixtures, snapshotFrom } from './support/prometheus-fixtures.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
let pki: Pki;
beforeAll(async () => {
  pki = await Pki.create();
}, 30_000);

const stops: (() => Promise<void>)[] = [];
afterEach(async () => {
  for (const stop of stops.splice(0)) await stop();
  vi.restoreAllMocks();
});

async function freshPull(): Promise<typeof import('../src/prom-pull.js')> {
  vi.resetModules();
  return import('../src/prom-pull.js');
}

describe('prom-pull, freshly loaded', () => {
  it('statuses and their 503 reasons', async () => {
    const pull = await freshPull();
    expect(pull.getPullStatus()).toBe('not_set_up');
    expect([
      pull.NOT_SET_UP,
      pull.READY,
      pull.SHUT_DOWN,
      pull.METRICS_DISABLED,
      pull.HOST_PROVIDER,
      pull.NOT_SELECTED,
      pull.OTEL_MISSING,
      pull.OTEL_DISABLED,
      pull.SETUP_FAILED,
    ]).toEqual([
      'not_set_up',
      'ready',
      'shut_down',
      'metrics_disabled',
      'host_provider',
      'not_selected',
      'otel_missing',
      'otel_disabled',
      'setup_failed',
    ]);
    expect(pull.REASONS).toEqual({
      not_set_up: 'provide-telemetry: metrics are not set up yet',
      shut_down: 'provide-telemetry: telemetry has been shut down',
      metrics_disabled: 'provide-telemetry: metrics are disabled (PROVIDE_METRICS_ENABLED=false)',
      host_provider:
        'provide-telemetry: the host application owns the MeterProvider; serve its registry instead',
      not_selected:
        'provide-telemetry: the Prometheus reader is not enabled (add prometheus to OTEL_METRICS_EXPORTER)',
      otel_missing:
        'provide-telemetry: the OpenTelemetry SDK is not installed (install @opentelemetry/sdk-metrics)',
      otel_disabled: 'provide-telemetry: OpenTelemetry is disabled (otelEnabled: false)',
      setup_failed: 'provide-telemetry: the metrics provider failed to start',
    });
    expect(pull.COLLECTION_FAILED).toBe('provide-telemetry: metrics collection failed');
    expect(pull.PLAIN_TEXT).toEqual(['content-type', 'text/plain; charset=utf-8']);
    expect(await pull.responseFor('GET', undefined)).toEqual({
      status: 503,
      headers: [['content-type', 'text/plain; charset=utf-8']],
      body: 'provide-telemetry: metrics are not set up yet\n',
    });
  });

  it('the health families match the fixture, with -1 for an unknown circuit state', async () => {
    const pull = await freshPull();
    const full = (promFixtures['health_metrics'] as any[])[0]['snapshot'] as Record<
      string,
      unknown
    >;
    const families = pull.healthFamilies(snapshotFrom(full));
    const got = families.flatMap((f) =>
      f.samples.map(([suffix, labels, value]) => ({ metric: f.name + suffix, labels, value })),
    );
    const key = (x: unknown): string => JSON.stringify(x);
    expect(got.map(key).sort()).toEqual(
      ((promFixtures['health_metrics'] as any[])[0]['expected_samples'] as unknown[])
        .map(key)
        .sort(),
    );
    const kinds = Object.fromEntries(families.map((f) => [f.name, f.kind]));
    expect(kinds).toEqual({
      provide_telemetry_emitted_total: 'counter',
      provide_telemetry_dropped_total: 'counter',
      provide_telemetry_export_failures_total: 'counter',
      provide_telemetry_export_retries_total: 'counter',
      provide_telemetry_export_latency_milliseconds: 'gauge',
      provide_telemetry_async_blocking_risk_total: 'counter',
      provide_telemetry_circuit_state: 'gauge',
      provide_telemetry_circuit_open_total: 'counter',
      provide_telemetry_setup_error: 'gauge',
      provide_telemetry_receipt_failures_total: 'counter',
    });
    expect([...pull.HEALTH_METRIC_NAMES]).toEqual(Object.keys(kinds));
    const odd = pull.healthFamilies(snapshotFrom({ ...full, circuit_state_logs: 'weird' }));
    expect(odd[6]?.samples[0]).toEqual(['', { signal: 'logs' }, -1]);
  });
});

describe('prom-render, freshly loaded', () => {
  it('content types, target_info, and which names and labels are quoted', async () => {
    vi.resetModules();
    const r = await import('../src/prom-render.js');
    expect(r.CONTENT_TYPE_TEXT).toBe(
      'text/plain; version=0.0.4; charset=utf-8; escaping=underscores',
    );
    expect(r.CONTENT_TYPE_UTF8).toBe(
      'text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8',
    );
    const out = r.render(
      r.familiesFrom(
        { resource: { attributes: { 'service.name': 'svc' } }, scopeMetrics: [] },
        { strategy: 'NoTranslation', scopeLabels: false, targetInfo: true, utf8: true },
      ),
    );
    expect(out).toBe(
      '# HELP target_info Target metadata\n# TYPE target_info gauge\ntarget_info{"service.name"="svc"} 1\n',
    );
    const line = (name: string, label: string): string => {
      const fam = r.family(name, 'gauge');
      fam.samples.push(['', { [label]: 'v' }, 1]);
      return r.render([fam]).split('\n')[1] as string;
    };
    expect(line('abc', 'xyz')).toBe('abc{xyz="v"} 1');
    expect(line('_a:b9', '_k9')).toBe('_a:b9{_k9="v"} 1');
    expect(line('a.b', 'k')).toBe('{"a.b",k="v"} 1');
    expect(line('9a', 'k')).toBe('{"9a",k="v"} 1');
    expect(line('ab.', 'k')).toBe('{"ab.",k="v"} 1');
    expect(line('a', 'k.l')).toBe('a{"k.l"="v"} 1');
    expect(line('a', '9k')).toBe('a{"9k"="v"} 1');
    expect(line('a', 'kl.')).toBe('a{"kl."="v"} 1');
    expect(line('a', '.kl')).toBe('a{".kl"="v"} 1');
    expect(line('.ab', 'k')).toBe('{".ab",k="v"} 1');
  });
});

describe('prom-listener, freshly loaded', () => {
  async function fresh(): Promise<typeof import('../src/prom-listener.js')> {
    vi.resetModules();
    const mod = await import('../src/prom-listener.js');
    stops.push(() => mod.stopListener());
    return mod;
  }

  function write(config: unknown): string {
    const path = join(mkdtempSync(join(tmpdir(), 'reload-')), 'web.yml');
    writeFileSync(
      path,
      stringify(config)
        .replace(/\{cert\}/g, pki.certFile)
        .replace(/\{key\}/g, pki.keyFile)
        .replace(/\{ca\}/g, pki.caFile),
    );
    return path;
  }

  it('constants', async () => {
    const mod = await fresh();
    expect(mod.READ_TIMEOUT_MS).toBe(10_000);
    expect(mod.INSTALL_HINT).toBe(
      'install the optional peer dependencies yaml and bcryptjs (npm install yaml bcryptjs) to use PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG',
    );
    expect(bcrypt.getRounds(mod.DUMMY_HASH)).toBe(10);
  });

  it('accepts exactly the supported keys and values', async () => {
    const mod = await fresh();
    const tls = { cert_file: '{cert}', key_file: '{key}' };
    await expect(mod.loadWebConfig(write({ http_server_config: {} }))).rejects.toThrow(
      'only basic_auth_users, tls_server_config are supported',
    );
    await expect(mod.loadWebConfig(write({ tls_server_config: { ...tls, x: 1 } }))).rejects.toThrow(
      'only cert_file, client_auth_type, client_ca_file, key_file, min_version are supported',
    );
    const all = await mod.loadWebConfig(
      write({
        basic_auth_users: { a: '$2b$10$' + 'a'.repeat(53) },
        tls_server_config: {
          ...tls,
          client_ca_file: '{ca}',
          client_auth_type: 'VerifyClientCertIfGiven',
          min_version: 'TLS13',
        },
      }),
    );
    expect(all.users.size).toBe(1);
    expect(all.tls?.options.minVersion).toBe('TLSv1.3');
    for (const [auth, request, reject] of [
      ['NoClientCert', false, false],
      ['RequireAndVerifyClientCert', true, true],
      ['VerifyClientCertIfGiven', true, false],
    ] as const) {
      const loaded = await mod.loadWebConfig(
        write({
          tls_server_config: {
            ...tls,
            client_ca_file: '{ca}',
            client_auth_type: auth,
            min_version: 'TLS12',
          },
        }),
      );
      expect([
        loaded.tls?.requestCert,
        loaded.tls?.rejectUnauthorized,
        loaded.tls?.options.minVersion,
      ]).toEqual([request, reject, 'TLSv1.2']);
    }
  });

  it('checks the bcrypt hash format', async () => {
    const mod = await fresh();
    const body = 'a'.repeat(53);
    for (const [hash, ok] of [
      [`$2a$04${'$'}${body}`, true],
      [`$2y$19$${body}`, true],
      [`$2b$31$${body}`, true],
      [`$2c$10$${body}`, false],
      [`$2a$03$${body}`, false],
      [`$2a$32$${body}`, false],
      [`$2a$a0$${body}`, false],
      [`$2a$1x$${body}`, false],
      [`$2a$3x$${body}`, false],
      [`$2a$10$${'a'.repeat(52)}`, false],
      [`$2a$10$${'!'.repeat(53)}`, false],
      [`x$2a$10$${body}`, false],
      [`$2a$10$${body}x`, false],
    ] as const) {
      const load = mod.loadWebConfig(write({ basic_auth_users: { u: hash } }));
      if (ok) await expect(load, hash).resolves.toBeDefined();
      else await expect(load, hash).rejects.toThrow('is not a bcrypt hash');
    }
  });

  it('answers 404 and 401 exactly', async () => {
    const mod = await fresh();
    const reports: string[] = [];
    await mod.syncListener(
      {
        prometheusHost: '127.0.0.1',
        prometheusPort: 0,
        prometheusPath: '/metrics',
        prometheusWebConfig: write({ basic_auth_users: { e2e: bcrypt.hashSync('pw', 4) } }),
      },
      true,
      (m) => reports.push(m),
    );
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(reports).toEqual([]);
    const port = mod.listenerAddress()?.port as number;
    const notFound = await fetch(`http://127.0.0.1:${port}/nope`);
    expect([notFound.status, notFound.headers.get('content-type'), await notFound.text()]).toEqual([
      404,
      'text/plain; charset=utf-8',
      'not found\n',
    ]);
    const denied = await fetch(`http://127.0.0.1:${port}/metrics`);
    expect([
      denied.status,
      denied.headers.get('www-authenticate'),
      denied.headers.get('content-type'),
      await denied.text(),
    ]).toEqual([401, 'Basic', 'text/plain; charset=utf-8', 'unauthorized\n']);
  });
});

describe('prom-setup and config, freshly loaded', () => {
  it('the real loader and the error prefix', async () => {
    vi.resetModules();
    const setup = await import('../src/prom-setup.js');
    const health = await import('../src/health.js');
    const { DEFAULTS } = await import('../src/config.js');
    expect(setup.LISTENER_ERROR_PREFIX).toBe('prometheus listener: ');
    await setup.syncPrometheusListener({
      ...DEFAULTS,
      metricsExporters: ['prometheus'],
      prometheusListen: 'true',
      prometheusPort: 0,
    });
    stops.push(() => setup.stopPrometheusListener());
    expect(setup.prometheusListenerAddress()?.host).toBe('127.0.0.1');
    health.setSetupError('prometheus listener: stale');
    await setup.syncPrometheusListener(DEFAULTS);
    expect(health.getHealthSnapshot().setupError).toBeNull();
  });

  it('the initial config exports with otlp', async () => {
    vi.resetModules();
    const config = await import('../src/config.js');
    expect(config.getConfig().metricsExporters).toEqual(['otlp']);
    expect(config.getConfig().metricsExporters).not.toBe(config.DEFAULTS.metricsExporters);
  });
});
