// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** metricsHandler() mounted on a real node:http server, and the Node-only entry point's surface. */

import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterEach, describe, expect, it } from 'vitest';
import { must } from './support/must.js';
import * as entry from '../src/prometheus.js';
import { metricsHandler, renderPrometheus } from '../src/prometheus.js';
import * as pull from '../src/prom-pull.js';
import { _resetPullForTests, markPullReady, REASONS } from '../src/prom-pull.js';
import { CONTENT_TYPE_TEXT, CONTENT_TYPE_UTF8 } from '../src/prom-render.js';
import { promFixtures } from './support/prometheus-fixtures.js';

let server: Server | undefined;

async function serve(): Promise<string> {
  server = createServer(metricsHandler());
  await new Promise<void>((done) => must(server).listen(0, '127.0.0.1', () => done()));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}/anything`;
}

function ready(): void {
  markPullReady(
    { collect: async () => ({ resourceMetrics: undefined }) },
    { strategy: 'UnderscoreEscapingWithSuffixes', scopeLabels: false, targetInfo: true },
  );
}

afterEach(async () => {
  _resetPullForTests();
  if (server) await new Promise<void>((done) => must(server).close(() => done()));
  server = undefined;
});

describe('metricsHandler', () => {
  it('exports exactly the Tier 2 surface', () => {
    expect(Object.keys(entry).sort()).toEqual(['metricsHandler', 'renderPrometheus']);
    expect(renderPrometheus).toBe(pull.renderPrometheus);
  });

  it('serves 503 with the reason before setup', async () => {
    const res = await fetch(await serve());
    expect(res.status).toBe(503);
    expect(res.headers.get('content-type')).toBe('text/plain; charset=utf-8');
    expect(await res.text()).toBe(`${REASONS.not_set_up}\n`);
  });

  it('serves at whatever path it is mounted on, and negotiates UTF-8', async () => {
    ready();
    const url = await serve();
    const plain = await fetch(url);
    expect(plain.status).toBe(200);
    expect(plain.headers.get('content-type')).toBe(CONTENT_TYPE_TEXT);
    const body = await plain.text();
    expect(body).toContain('provide_telemetry_receipt_failures_total 0\n');
    expect(plain.headers.get('content-length')).toBe(String(Buffer.byteLength(body)));
    const utf8 = await fetch(url, { headers: { accept: 'text/plain;escaping=allow-utf-8' } });
    expect(utf8.headers.get('content-type')).toBe(CONTENT_TYPE_UTF8);
  });

  it('answers HEAD without a body and other methods with 405', async () => {
    ready();
    const url = await serve();
    const head = await fetch(url, { method: 'HEAD' });
    expect([head.status, head.headers.get('content-length')]).toEqual([200, '0']);
    const post = await fetch(url, { method: 'POST' });
    expect([post.status, post.headers.get('allow'), await post.text()]).toEqual([
      405,
      'GET, HEAD',
      'method not allowed\n',
    ]);
  });

  it('runs the handler_status cases over HTTP', async () => {
    const url = await serve();
    for (const c of promFixtures['handler_status'] as Record<string, string | number>[]) {
      if (c['state'] === 'ready') ready();
      else pull.setPullStatus(c['state'] as Parameters<typeof pull.setPullStatus>[0]);
      const res = await fetch(url, { method: (c['method'] as string | undefined) ?? 'GET' });
      expect(res.status, String(c['id'])).toBe(c['status']);
      if (c['content_type_prefix']) {
        expect(
          must(res.headers.get('content-type')).startsWith(c['content_type_prefix'] as string),
        ).toBe(true);
      }
      await res.arrayBuffer();
    }
  });
});
