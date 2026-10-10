// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/** HTTP(S) client helpers and settings for the listener tests. */

import { readFileSync } from 'node:fs';
import { request as httpRequest, type IncomingHttpHeaders } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { listenerAddress, syncListener, type ListenerSettings } from '../../src/prom-listener.js';

export const PASSWORD = 'e2e-test-only-password';

export interface Reply {
  status: number;
  headers: IncomingHttpHeaders;
  body: string;
}

export interface FetchOptions {
  method?: string;
  path?: string;
  headers?: Record<string, string>;
  /** PEM files: trust ca; present cert/key as the client certificate. */
  ca?: string;
  cert?: string;
  key?: string;
  maxVersion?: 'TLSv1.2' | 'TLSv1.3';
}

export function basic(user: string, password: string): string {
  return `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;
}

/** One request to the running listener; rejects when the connection fails. */
export function fetchListener(scheme: 'http' | 'https', opts: FetchOptions = {}): Promise<Reply> {
  const bound = listenerAddress();
  if (bound === undefined) throw new Error('listener is not running');
  const common = {
    host: '127.0.0.1',
    port: bound.port,
    method: opts.method ?? 'GET',
    path: opts.path ?? '/metrics',
    headers: opts.headers ?? {},
    agent: false as const,
  };
  return new Promise((done, fail) => {
    const onResponse = (res: import('node:http').IncomingMessage): void => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk: string) => (body += chunk));
      res.on('end', () => done({ status: res.statusCode as number, headers: res.headers, body }));
    };
    const req =
      scheme === 'http'
        ? httpRequest(common, onResponse)
        : httpsRequest(
            {
              ...common,
              ca: opts.ca ? readFileSync(opts.ca) : undefined,
              cert: opts.cert ? readFileSync(opts.cert) : undefined,
              key: opts.key ? readFileSync(opts.key) : undefined,
              maxVersion: opts.maxVersion,
              servername: 'localhost',
            },
            onResponse,
          );
    req.on('error', fail);
    req.end();
  });
}

export function settings(overrides: Partial<ListenerSettings> = {}): ListenerSettings {
  return {
    prometheusHost: '127.0.0.1',
    prometheusPort: 0,
    prometheusPath: '/metrics',
    prometheusWebConfig: '',
    ...overrides,
  };
}

/** Sync the listener on; returns what it reported. */
export async function startListener(overrides: Partial<ListenerSettings> = {}): Promise<string[]> {
  const reports: string[] = [];
  await syncListener(settings(overrides), true, (m) => reports.push(m));
  return reports;
}
