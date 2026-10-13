// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** The standalone Prometheus listener: the shared web config cases, requests and lifecycle. */

import { connect, createServer as createTcpServer, type AddressInfo } from 'node:net';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import bcrypt from 'bcryptjs';
import { stringify } from 'yaml';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { must } from './support/must.js';
import {
  _listenerServerForTests,
  isLoopback,
  listenerAddress,
  READ_TIMEOUT_MS,
  stopListener,
  syncListener,
} from '../src/prom-listener.js';
import { _resetPullForTests, markPullReady, REASONS } from '../src/prom-pull.js';
import { CONTENT_TYPE_TEXT } from '../src/prom-render.js';
import {
  basic,
  fetchListener,
  PASSWORD,
  settings,
  startListener,
} from './support/listener-client.js';
import { fillPathPlaceholders, Pki } from './support/pki.js';
import { promFixtures } from './support/prometheus-fixtures.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
let pki: Pki;
let hashed: string;

beforeAll(async () => {
  pki = await Pki.create();
  hashed = bcrypt.hashSync(PASSWORD, 4);
}, 30_000);

function ready(): void {
  markPullReady(
    { collect: async () => ({ resourceMetrics: undefined }) },
    { strategy: 'UnderscoreEscapingWithSuffixes', scopeLabels: false, targetInfo: true },
  );
}

/** Write a web config with the fixture placeholders filled in; returns its path. */
function writeConfig(config: unknown, dir = mkdtempSync(join(tmpdir(), 'web-'))): string {
  const text = fillPathPlaceholders(stringify(config), {
    cert: pki.certFile,
    key: pki.keyFile,
    ca: pki.caFile,
    missing: join(dir, 'missing.pem'),
  }).replace(/bcrypt_of_e2e_test_only_password/g, `'${hashed}'`);
  const path = join(dir, 'web.yml');
  writeFileSync(path, text);
  return path;
}

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(async () => {
  await stopListener();
  _resetPullForTests();
  vi.restoreAllMocks();
});

afterAll(async () => {
  await stopListener();
});

describe('listener_web_config fixtures', () => {
  for (const c of promFixtures['listener_web_config'] as any[]) {
    it(
      c['id'] as string,
      async () => {
        ready();
        let path = '';
        if (c['web_config_path']) {
          path = (c['web_config_path'] as string).replace(
            '{missing}',
            join(pki.dir, 'missing.yml'),
          );
        } else if (c['web_config'] !== null) {
          path = writeConfig(c['web_config']);
        }
        const reports = await startListener({ prometheusWebConfig: path });
        expect(listenerAddress() !== undefined).toBe(c['listener']);
        if (c['error']) {
          expect(reports).toHaveLength(1);
          expect(must(reports[0]).startsWith('prometheus listener: ')).toBe(true);
          return;
        }
        expect(reports).toEqual([]);
        const scheme = c['scheme'] as 'http' | 'https';
        const tls = scheme === 'https' ? { ca: pki.caFile } : {};
        const client = c['client_cert_required']
          ? { cert: pki.clientCert, key: pki.clientKey }
          : {};
        if (c['client_cert_required']) {
          await expect(fetchListener(scheme, tls)).rejects.toThrow();
        }
        if (c['auth']) {
          expect((await fetchListener(scheme, { ...tls, ...client })).status).toBe(401);
        }
        const headers: Record<string, string> = c['auth']
          ? { authorization: basic('e2e', PASSWORD) }
          : {};
        expect((await fetchListener(scheme, { ...tls, ...client, headers })).status).toBe(200);
        expect(console.warn).toHaveBeenCalledTimes(c['warning'] ? 1 : 0);
      },
      30_000,
    );
  }
});

describe('requests', () => {
  it('serves only the configured path, ignoring the query string', async () => {
    ready();
    await startListener({ prometheusPath: '/internal/metrics' });
    expect((await fetchListener('http', { path: '/internal/metrics' })).status).toBe(200);
    expect((await fetchListener('http', { path: '/internal/metrics?debug=1' })).status).toBe(200);
    expect((await fetchListener('http', { path: '/internal/metrics#x' })).status).toBe(200);
    expect((await fetchListener('http', { path: '/metrics' })).status).toBe(404);
    expect((await fetchListener('http', { path: '/internal/metrics/x' })).status).toBe(404);
    expect((await fetchListener('http', { path: '/x/internal/metrics' })).status).toBe(404);
    expect(
      (await fetchListener('http', { path: '/internal/metrics', method: 'HEAD' })).status,
    ).toBe(200);
    for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) {
      expect((await fetchListener('http', { path: '/internal/metrics', method })).status).toBe(405);
    }
  });

  it('exact error and success responses', async () => {
    ready();
    await startListener();
    const notFound = await fetchListener('http', { path: '/nope' });
    expect([notFound.status, notFound.body]).toEqual([404, 'not found\n']);
    expect(notFound.headers['content-type']).toBe('text/plain; charset=utf-8');
    expect(notFound.headers['content-length']).toBe('10');
    const post = await fetchListener('http', { method: 'POST' });
    expect([post.status, post.headers['allow'], post.body]).toEqual([
      405,
      'GET, HEAD',
      'method not allowed\n',
    ]);
    const ok = await fetchListener('http', { headers: { accept: 'text/plain;version=0.0.4' } });
    expect(ok.status).toBe(200);
    expect(ok.headers['content-type']).toBe(CONTENT_TYPE_TEXT);
    expect(ok.headers['content-length']).toBe(String(Buffer.byteLength(ok.body)));
    expect(ok.body).toContain('provide_telemetry_setup_error');
    const utf8 = await fetchListener('http', {
      headers: { accept: 'text/plain;escaping=allow-utf-8' },
    });
    expect(utf8.headers['content-type']).toContain('escaping=allow-utf-8');
    const head = await fetchListener('http', { method: 'HEAD' });
    expect([head.status, head.body, head.headers['content-length']]).toEqual([200, '', '0']);
  });

  it('exact 401 response', async () => {
    ready();
    await startListener({
      prometheusWebConfig: writeConfig({
        basic_auth_users: { e2e: 'bcrypt_of_e2e_test_only_password' },
      }),
    });
    const denied = await fetchListener('http');
    expect([denied.status, denied.headers['www-authenticate'], denied.body]).toEqual([
      401,
      'Basic',
      'unauthorized\n',
    ]);
    expect(denied.headers['content-type']).toBe('text/plain; charset=utf-8');
    // 404 comes before auth, as in Python: the path is not a secret.
    expect((await fetchListener('http', { path: '/nope' })).status).toBe(404);
    const wrong = await fetchListener('http', { headers: { authorization: basic('e2e', 'nope') } });
    expect(wrong.status).toBe(401);
  });

  it('not ready is served as 503', async () => {
    await startListener();
    const res = await fetchListener('http');
    expect([res.status, res.body]).toEqual([503, `${REASONS.not_set_up}\n`]);
  });

  it('a failed TLS handshake does not stop the listener', async () => {
    ready();
    await startListener({
      prometheusWebConfig: writeConfig({
        tls_server_config: { cert_file: '{cert}', key_file: '{key}' },
      }),
    });
    const port = must(listenerAddress()).port;
    await new Promise<void>((done) => {
      const raw = connect(port, '127.0.0.1', () => raw.write('GET /metrics HTTP/1.1\r\n\r\n'));
      raw.on('error', () => done());
      raw.on('close', () => done());
      raw.resume();
    });
    expect((await fetchListener('https', { ca: pki.caFile })).status).toBe(200);
    await expect(fetchListener('http')).rejects.toThrow();
  });

  it('applies read timeouts', async () => {
    await startListener();
    const server = must(_listenerServerForTests());
    expect(READ_TIMEOUT_MS).toBe(10_000);
    expect(server.headersTimeout).toBe(READ_TIMEOUT_MS);
    expect(server.requestTimeout).toBe(READ_TIMEOUT_MS);
    expect(server.timeout).toBe(READ_TIMEOUT_MS);
  });

  it('applies the TLS handshake timeout', async () => {
    await startListener({
      prometheusWebConfig: writeConfig({
        tls_server_config: { cert_file: '{cert}', key_file: '{key}' },
      }),
    });
    // Node keeps it under a private symbol; reading it is the only way to see it.
    const server = _listenerServerForTests() as unknown as Record<symbol, unknown>;
    const key = Object.getOwnPropertySymbols(server).find(
      (s) => String(s) === 'Symbol(handshake-timeout)',
    );
    expect(key && server[key]).toBe(READ_TIMEOUT_MS);
  });
});

describe('lifecycle', () => {
  it('keeps a matching listener, restarts on a changed key, stops when disabled', async () => {
    await startListener();
    const first = _listenerServerForTests();
    await startListener();
    expect(_listenerServerForTests()).toBe(first);
    for (const change of [
      { prometheusPath: '/other' },
      { prometheusHost: 'localhost' },
      { prometheusWebConfig: writeConfig(null) },
    ]) {
      const before = _listenerServerForTests();
      await startListener(change);
      expect(_listenerServerForTests()).not.toBe(before);
      expect(_listenerServerForTests()).toBeDefined();
      expect(must(before).listening).toBe(false);
    }
    await syncListener(settings(), false, () => {});
    expect(listenerAddress()).toBeUndefined();
    expect(_listenerServerForTests()).toBeUndefined();
    await stopListener(); // stopping twice is a no-op
  });

  it('a changed port restarts it on that port', async () => {
    await startListener();
    const probe = createTcpServer();
    await new Promise<void>((done) => probe.listen(0, '127.0.0.1', () => done()));
    const free = (probe.address() as AddressInfo).port;
    await new Promise<void>((done) => probe.close(() => done()));
    await startListener({ prometheusPort: free });
    expect(listenerAddress()).toEqual({ host: '127.0.0.1', port: free });
  });

  it('stop drops open keep-alive connections', async () => {
    ready();
    await startListener();
    const port = must(listenerAddress()).port;
    const closed = new Promise<void>((done) => {
      const raw = connect(port, '127.0.0.1', () =>
        raw.write('GET /metrics HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n'),
      );
      raw.resume();
      raw.on('close', () => done());
    });
    await new Promise((r) => setTimeout(r, 50));
    await stopListener();
    await closed;
  });

  it('a bind failure is reported and logged, never thrown', async () => {
    const busy = createTcpServer();
    await new Promise<void>((done) => busy.listen(0, '127.0.0.1', () => done()));
    const port = (busy.address() as AddressInfo).port;
    try {
      const reports = await startListener({ prometheusPort: port });
      expect(listenerAddress()).toBeUndefined();
      expect(reports).toHaveLength(1);
      expect(reports[0]).toMatch(/^prometheus listener: listen EADDRINUSE/);
      expect(console.warn).toHaveBeenCalledWith(
        `[provide/telemetry] metrics.prometheus_listener.failed: ${must(reports[0])}`,
      );
      // The next sync retries rather than remembering the failure.
      await new Promise<void>((done) => busy.close(() => done()));
      expect(await startListener({ prometheusPort: port })).toEqual([]);
      expect(must(listenerAddress()).port).toBe(port);
    } finally {
      busy.close();
    }
  });

  it('listens on IPv6 loopback', async () => {
    const reports = await startListener({ prometheusHost: '::1' });
    if (reports.length > 0) return; // no IPv6 on this host
    expect(must(listenerAddress()).host).toBe('::1');
    expect(console.warn).not.toHaveBeenCalled();
  });

  it('warns once when bound to a non-loopback host', async () => {
    await startListener({ prometheusHost: '0.0.0.0' });
    expect(console.warn).toHaveBeenCalledTimes(1);
    expect(console.warn).toHaveBeenCalledWith(
      '[provide/telemetry] metrics.prometheus_listener.exposed: host=0.0.0.0',
    );
  });

  it('warns when basic auth travels without TLS', async () => {
    await startListener({
      prometheusWebConfig: writeConfig({
        basic_auth_users: { e2e: 'bcrypt_of_e2e_test_only_password' },
      }),
    });
    expect(console.warn).toHaveBeenCalledWith(
      '[provide/telemetry] metrics.prometheus_listener.cleartext_auth',
    );
  });

  it('serializes concurrent syncs', async () => {
    const results = await Promise.all([
      startListener(),
      startListener(),
      stopListener(),
      startListener(),
    ]);
    expect(results[0]).toEqual([]);
    expect(listenerAddress()).toBeDefined();
  });

  it('listenerAddress is undefined when stopped', () => {
    expect(listenerAddress()).toBeUndefined();
  });

  it.each([
    ['localhost', true],
    ['127.0.0.1', true],
    ['127.10.0.1', true],
    ['::1', true],
    ['0:0:0:0:0:0:0:1', true],
    ['0.0.0.0', false],
    ['::', false],
    ['10.0.0.1', false],
    ['example.com', false],
    ['1.127.0.0', false],
  ])('isLoopback(%s) is %s', (host, loopback) => {
    expect(isLoopback(host)).toBe(loopback);
  });
});
