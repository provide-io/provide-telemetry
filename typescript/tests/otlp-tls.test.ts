// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** push_security: an OTLP TLS file that cannot be read or loaded keeps that exporter unbuilt. */

import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { getConfig, setupTelemetry, type TelemetryConfig } from '../src/config.js';
import { getHealthSnapshot, setSetupError } from '../src/health.js';
import { registerOtelProviders } from '../src/otel.js';
import {
  beginTlsChecks,
  SEPARATOR,
  takeTlsProblems,
  tlsReady,
  unreadableTls,
} from '../src/otlp-tls.js';
import { getPullStatus, READY } from '../src/prom-pull.js';
import { _getProvidersBySignal } from '../src/provider-registry.js';
import { shutdownTelemetry } from '../src/shutdown.js';
import { resetTelemetryState } from '../src/testing.js';
import { must } from './support/must.js';
import { Pki } from './support/pki.js';
import { withEnv } from './support/prometheus-fixtures.js';

let pki: Pki;
let other: Pki;
let dir: string;
let missing: string;
let garbage: string;
let empty: string;

beforeAll(async () => {
  pki = await Pki.create();
  other = await Pki.create();
  dir = mkdtempSync(join(tmpdir(), 'otlp-tls-'));
  missing = join(dir, 'missing.pem');
  garbage = join(dir, 'garbage.pem');
  writeFileSync(
    garbage,
    '-----BEGIN CERTIFICATE-----\nnot base64 at all\n-----END CERTIFICATE-----\n',
  );
  empty = join(dir, 'empty.pem');
  writeFileSync(empty, 'no certificates here\n');
}, 30_000);

/** unreadableTls over a plain variable map. */
function check(signal: string, vars: Record<string, string>): Promise<string | undefined> {
  return unreadableTls(signal, (name) => vars[name]);
}

describe('unreadableTls', () => {
  it('nothing configured is fine', async () => {
    expect(await check('metrics', {})).toBeUndefined();
    expect(await check('metrics', { OTEL_EXPORTER_OTLP_CERTIFICATE: '' })).toBeUndefined();
  });

  it('good files are fine, shared or per signal', async () => {
    expect(
      await check('traces', {
        OTEL_EXPORTER_OTLP_CERTIFICATE: pki.caFile,
        OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE: pki.clientCert,
        OTEL_EXPORTER_OTLP_CLIENT_KEY: pki.clientKey,
      }),
    ).toBeUndefined();
    expect(
      await check('logs', { OTEL_EXPORTER_OTLP_LOGS_CERTIFICATE: pki.caFile }),
    ).toBeUndefined();
  });

  it.each(['CERTIFICATE', 'CLIENT_CERTIFICATE', 'CLIENT_KEY'])(
    'a missing %s names the variable',
    async (kind) => {
      for (const name of [`OTEL_EXPORTER_OTLP_${kind}`, `OTEL_EXPORTER_OTLP_METRICS_${kind}`]) {
        expect(await check('metrics', { [name]: missing })).toBe(`${name}=${missing}: ENOENT`);
      }
    },
  );

  it('the per-signal variable wins over a bad shared one, and only for its signal', async () => {
    const env = {
      OTEL_EXPORTER_OTLP_CERTIFICATE: missing,
      OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE: pki.caFile,
    };
    expect(await check('traces', env)).toBeUndefined();
    expect(await check('logs', env)).toBe(`OTEL_EXPORTER_OTLP_CERTIFICATE=${missing}: ENOENT`);
  });

  it('reports the CA, then the client certificate, then the key', async () => {
    const all = {
      OTEL_EXPORTER_OTLP_CERTIFICATE: missing,
      OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE: missing,
      OTEL_EXPORTER_OTLP_CLIENT_KEY: missing,
    };
    expect(await check('logs', all)).toMatch(/^OTEL_EXPORTER_OTLP_CERTIFICATE=/);
    expect(await check('logs', { ...all, OTEL_EXPORTER_OTLP_CERTIFICATE: pki.caFile })).toMatch(
      /^OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=/,
    );
    expect(
      await check('logs', {
        ...all,
        OTEL_EXPORTER_OTLP_CERTIFICATE: pki.caFile,
        OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE: pki.clientCert,
      }),
    ).toMatch(/^OTEL_EXPORTER_OTLP_CLIENT_KEY=/);
  });

  it('a CA file with no PEM certificates, or a malformed one, is unloadable', async () => {
    for (const ca of [empty, garbage, pki.keyFile]) {
      expect(await check('metrics', { OTEL_EXPORTER_OTLP_CERTIFICATE: ca })).toBe(
        `OTEL_EXPORTER_OTLP_CERTIFICATE=${ca}: no PEM certificates`,
      );
    }
    const bundle = join(dir, 'bundle.pem');
    writeFileSync(bundle, `${readFileSync(pki.caFile, 'utf8')}\n${readFileSync(garbage, 'utf8')}`);
    expect(await check('metrics', { OTEL_EXPORTER_OTLP_CERTIFICATE: bundle })).toMatch(
      /no PEM certificates$/,
    );
  });

  it('a client certificate and key that do not pair are unloadable; either alone is not checked', async () => {
    const env = {
      OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE: pki.clientCert,
      OTEL_EXPORTER_OTLP_CLIENT_KEY: other.clientKey,
    };
    const problem = must(await check('metrics', env));
    expect(
      problem.startsWith(
        `OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE=${pki.clientCert}, OTEL_EXPORTER_OTLP_CLIENT_KEY=${other.clientKey}: `,
      ),
    ).toBe(true);
    expect(problem.length).toBeGreaterThan(problem.indexOf(': ') + 2);
    expect(
      await check('metrics', { OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE: pki.clientCert }),
    ).toBeUndefined();
    expect(
      await check('metrics', { OTEL_EXPORTER_OTLP_CLIENT_KEY: other.clientKey }),
    ).toBeUndefined();
  });

  it('reads the process environment by default', async () => {
    await withEnv({ OTEL_EXPORTER_OTLP_CERTIFICATE: missing }, async () => {
      expect(await unreadableTls('metrics')).toBe(
        `OTEL_EXPORTER_OTLP_CERTIFICATE=${missing}: ENOENT`,
      );
    });
  });
});

describe('tlsReady and the recorded problems', () => {
  beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
    beginTlsChecks(
      () => null,
      () => {},
    );
  });

  it('records, logs and joins problems; clears only the error it set', async () => {
    const saved = process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
    process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = missing;
    try {
      beginTlsChecks(
        () => null,
        () => {},
      );
      expect(await tlsReady('logs')).toBe(false);
      expect(await tlsReady('traces')).toBe(false);
      const problem = `OTEL_EXPORTER_OTLP_CERTIFICATE=${missing}: ENOENT`;
      expect(console.warn).toHaveBeenCalledWith(
        `[provide/telemetry] otlp.tls_file_unreadable: signal=logs error=${problem}`,
      );
      const joined = takeTlsProblems();
      expect(joined).toBe(`${problem}${SEPARATOR}${problem}`);
      expect(SEPARATOR).toBe('; ');
      expect(takeTlsProblems()).toBeNull();
      // takeTlsProblems() remembers what it handed out last; here, nothing.
      const clear = vi.fn();
      beginTlsChecks(() => joined, clear);
      expect(clear).not.toHaveBeenCalled();
      expect(await tlsReady('logs')).toBe(false);
      const again = takeTlsProblems();
      beginTlsChecks(() => 'unrelated', clear);
      expect(clear).not.toHaveBeenCalled();
      expect(await tlsReady('logs')).toBe(false);
      takeTlsProblems();
      beginTlsChecks(() => again, clear);
      expect(clear).toHaveBeenCalledTimes(1);
      expect(takeTlsProblems()).toBeNull();
    } finally {
      if (saved === undefined) delete process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
      else process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = saved;
    }
    expect(await tlsReady('logs')).toBe(true);
  });
});

describe('registerOtelProviders with an unreadable TLS file', () => {
  const ENDPOINT = 'https://127.0.0.1:9';
  function setup(overrides: Partial<TelemetryConfig>): TelemetryConfig {
    withEnv({}, () =>
      setupTelemetry({ consoleOutput: false, otlpEndpoint: ENDPOINT, ...overrides }),
    );
    return getConfig();
  }

  beforeEach(() => {
    resetTelemetryState();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
  });
  afterEach(async () => {
    delete process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
    delete process.env['OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE'];
    await shutdownTelemetry();
    resetTelemetryState();
    vi.restoreAllMocks();
  });

  it('skips every OTLP exporter, keeps the pull reader, and names the file as setupError', async () => {
    const cfg = setup({ metricsExporters: ['otlp', 'prometheus'] });
    process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = missing;
    await registerOtelProviders(cfg);
    const problem = `OTEL_EXPORTER_OTLP_CERTIFICATE=${missing}: ENOENT`;
    expect(getHealthSnapshot().setupError).toBe([problem, problem, problem].join('; '));
    const bySignal = _getProvidersBySignal();
    expect(bySignal.traces).toBeUndefined();
    expect(bySignal.logs).toBeUndefined();
    const metricsProvider = must(bySignal.metrics) as unknown as {
      _sharedState: { metricCollectors: unknown[] };
    };
    expect(metricsProvider._sharedState.metricCollectors).toHaveLength(1);
    expect(getPullStatus()).toBe(READY);
  });

  it('a good per-signal override keeps that exporter', async () => {
    const cfg = setup({});
    process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = missing;
    process.env['OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE'] = pki.caFile;
    await registerOtelProviders(cfg);
    expect(_getProvidersBySignal().traces).toBeDefined();
    expect(_getProvidersBySignal().metrics).toBeUndefined();
    expect(getHealthSnapshot().setupError).toBe(
      [
        `OTEL_EXPORTER_OTLP_CERTIFICATE=${missing}: ENOENT`,
        `OTEL_EXPORTER_OTLP_CERTIFICATE=${missing}: ENOENT`,
      ].join('; '),
    );
  });

  it('a later good attempt clears the error; an unrelated error is left', async () => {
    process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = missing;
    await registerOtelProviders(setup({ tracingEnabled: false, otlpLogsEnabled: false }));
    expect(getHealthSnapshot().setupError).toMatch(/^OTEL_EXPORTER_OTLP_CERTIFICATE=/);
    delete process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
    await registerOtelProviders(setup({ tracingEnabled: false, otlpLogsEnabled: false }));
    expect(getHealthSnapshot().setupError).toBeNull();
    expect(_getProvidersBySignal().metrics).toBeDefined();
    setSetupError('unrelated');
    await registerOtelProviders(setup({ otelEnabled: false }));
    expect(getHealthSnapshot().setupError).toBe('unrelated');
  });
});
