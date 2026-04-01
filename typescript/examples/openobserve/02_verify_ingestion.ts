// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * Verify that signals emitted by 01_emit_all_signals.ts were ingested by OpenObserve.
 *
 * Runs the emit script, then polls the OpenObserve search API until signals appear
 * (or a 30-second deadline is reached).
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. admin@provide.test
 *   OPENOBSERVE_PASSWORD e.g. Complexpass#123
 *
 * Optional:
 *   OPENOBSERVE_REQUIRED_SIGNALS  comma-separated: logs,metrics,traces (default: logs)
 *
 * Run:
 *   OPENOBSERVE_URL=http://localhost:5080/api/default \
 *   OPENOBSERVE_USER=admin@provide.test \
 *   OPENOBSERVE_PASSWORD=Complexpass#123 \
 *   npx tsx examples/openobserve/02_verify_ingestion.ts
 */

import { execSync } from 'node:child_process';
import * as https from 'node:https';
import * as http from 'node:http';
import { resolve } from 'node:path';

function requireEnv(name: string): string {
  const val = process.env[name];
  if (!val) throw new Error(`missing required env var: ${name}`);
  return val;
}

function authHeader(user: string, password: string): string {
  return `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;
}

function requestJson(url: string, auth: string, method = 'GET', body?: unknown): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const mod = parsed.protocol === 'https:' ? https : http;
    const payload = body !== undefined ? Buffer.from(JSON.stringify(body)) : undefined;
    const req = mod.request(
      {
        hostname: parsed.hostname,
        port: parsed.port ?? (parsed.protocol === 'https:' ? 443 : 80),
        path: parsed.pathname + (parsed.search ?? ''),
        method,
        headers: {
          Authorization: auth,
          ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': payload.length } : {}),
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () => {
          const raw = Buffer.concat(chunks).toString('utf8');
          if ((res.statusCode ?? 0) >= 400) {
            reject(new Error(`OpenObserve API returned ${res.statusCode}: ${raw}`));
          } else {
            try { resolve(JSON.parse(raw)); } catch { resolve(raw); }
          }
        });
      },
    );
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function searchHits(
  baseUrl: string, streamType: string, auth: string,
  startUs: number, endUs: number,
): Promise<Record<string, unknown>[]> {
  const sql = 'select * from "default" order by _timestamp desc limit 500';
  try {
    const res = await requestJson(
      `${baseUrl}/_search?type=${streamType}`, auth, 'POST',
      { query: { sql, start_time: startUs, end_time: endUs } },
    ) as Record<string, unknown>;
    const hits = res['hits'];
    if (!Array.isArray(hits)) return [];
    return hits.filter((h): h is Record<string, unknown> => typeof h === 'object' && h !== null);
  } catch (err) {
    if (String(err).includes('Search stream not found')) return [];
    throw err;
  }
}

async function streamNames(baseUrl: string, streamType: string, auth: string): Promise<Set<string>> {
  const res = await requestJson(`${baseUrl}/streams?type=${streamType}`, auth) as Record<string, unknown>;
  const list = res['list'];
  if (!Array.isArray(list)) return new Set();
  return new Set(list.map((item: unknown) => (item as Record<string, unknown>)['name'] as string));
}

function requiredSignalsFromEnv(): Set<string> {
  // Default: traces only. Logs are pino → stdout only (no OTLP log exporter in TS yet).
  const raw = process.env['OPENOBSERVE_REQUIRED_SIGNALS'] ?? 'traces';
  const requested = new Set(raw.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean));
  if (requested.size === 0) requested.add('traces');
  const valid = new Set(['logs', 'metrics', 'traces']);
  for (const s of requested) {
    if (!valid.has(s)) throw new Error(`invalid OPENOBSERVE_REQUIRED_SIGNALS entry: ${s}`);
  }
  return requested;
}

async function main(): Promise<void> {
  const baseUrl = requireEnv('OPENOBSERVE_URL').replace(/\/$/, '');
  const user = requireEnv('OPENOBSERVE_USER');
  const password = requireEnv('OPENOBSERVE_PASSWORD');
  const auth = authHeader(user, password);
  const runId = String(Date.now());
  process.env['PROVIDE_EXAMPLE_RUN_ID'] = runId;

  const startUs = Date.now() * 1000 - 2 * 60 * 60 * 1_000_000;
  const traceName = `example.openobserve.work.${runId}`;
  const metricStream = `example_openobserve_requests_${runId}`;
  // Stable OTel event name + run_id attribute — filter client-side, not by munging the name.
  const logEvent = 'example.openobserve.log';

  // ── Baseline before emit ──────────────────────────────────────────────────
  const endUsBefore = Date.now() * 1000;
  const beforeLogHits = await searchHits(baseUrl, 'logs', auth, startUs, endUsBefore);
  const beforeTraceHits = await searchHits(baseUrl, 'traces', auth, startUs, endUsBefore);
  const beforeMetricStreams = await streamNames(baseUrl, 'metrics', auth);
  const beforeLogs = beforeLogHits.filter((h) => h['event'] === logEvent && h['run_id'] === runId).length;
  const beforeTraces = beforeTraceHits.filter((h) => h['operation_name'] === traceName).length;
  const before = { logs: beforeLogs, metrics_stream_present: beforeMetricStreams.has(metricStream), traces: beforeTraces };
  const requiredSignals = requiredSignalsFromEnv();
  console.log(`before=${JSON.stringify(before)}`);
  console.log(`required_signals=${JSON.stringify([...requiredSignals].sort())}`);

  // ── Run emit script ──────────────────────────────────────────────────────
  const emitScript = resolve(import.meta.dirname ?? __dirname, '01_emit_all_signals.ts');
  execSync(`npx tsx ${emitScript}`, { stdio: 'inherit', env: { ...process.env } });

  // ── Poll until ingested ───────────────────────────────────────────────────
  const deadline = Date.now() + 30_000;
  let after = { ...before };
  while (Date.now() < deadline) {
    const endUs = Date.now() * 1000;
    const logHits = await searchHits(baseUrl, 'logs', auth, startUs, endUs);
    const traceHits = await searchHits(baseUrl, 'traces', auth, startUs, endUs);
    const mStreams = await streamNames(baseUrl, 'metrics', auth);
    after = {
      logs: logHits.filter((h) => h['event'] === logEvent && h['run_id'] === runId).length,
      metrics_stream_present: mStreams.has(metricStream),
      traces: traceHits.filter((h) => h['operation_name'] === traceName).length,
    };

    const logsOk = !requiredSignals.has('logs') || after.logs > before.logs;
    const metricsOk = !requiredSignals.has('metrics') || after.metrics_stream_present;
    const tracesOk = !requiredSignals.has('traces') || after.traces > before.traces;
    if (logsOk && metricsOk && tracesOk) break;
    await new Promise((r) => setTimeout(r, 1000));
  }

  console.log(`after=${JSON.stringify(after)}`);

  const missing: string[] = [];
  if (requiredSignals.has('logs') && after.logs <= before.logs) missing.push('logs');
  if (requiredSignals.has('metrics') && !after.metrics_stream_present) missing.push('metrics');
  if (requiredSignals.has('traces') && after.traces <= before.traces) missing.push('traces');
  if (missing.length > 0) throw new Error(`ingestion did not increase for: ${missing.join(', ')}`);

  console.log('verification passed');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
