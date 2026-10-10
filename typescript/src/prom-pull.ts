// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Prometheus pull support: the reader, its status, and the Tier 2 response.
 *
 * See prometheus_metrics in spec/telemetry-api.yaml. registerOtelProviders()
 * attaches a pull reader to the provider it builds when OTEL_METRICS_EXPORTER
 * includes prometheus (or the listener is requested) and records here whether
 * the endpoint can serve. renderPrometheus() then renders one collection per
 * call, with the health snapshot as provide_telemetry_* series. Mirrors Python
 * provide.telemetry.metrics.prometheus.
 *
 * Nothing here imports the OTel SDK or a Node built-in: the SDK module is
 * handed in, so this file is safe in the browser bundle, where it is never
 * made ready.
 */

import { TelemetryError } from './exceptions.js';
import { getHealthSnapshot, type HealthSnapshot } from './health.js';
import {
  CONTENT_TYPE_TEXT,
  CONTENT_TYPE_UTF8,
  family,
  familiesFrom,
  render,
  wantsUtf8,
  type Family,
  type RenderOptions,
  type ResourceMetricsLike,
} from './prom-render.js';

export const NOT_SET_UP = 'not_set_up';
export const READY = 'ready';
export const SHUT_DOWN = 'shut_down';
export const METRICS_DISABLED = 'metrics_disabled';
export const HOST_PROVIDER = 'host_provider';
export const NOT_SELECTED = 'not_selected';
export const OTEL_MISSING = 'otel_missing';
export const OTEL_DISABLED = 'otel_disabled';
export const SETUP_FAILED = 'setup_failed';

export type PullStatus =
  | typeof NOT_SET_UP
  | typeof READY
  | typeof SHUT_DOWN
  | typeof METRICS_DISABLED
  | typeof HOST_PROVIDER
  | typeof NOT_SELECTED
  | typeof OTEL_MISSING
  | typeof OTEL_DISABLED
  | typeof SETUP_FAILED;

/** The one-line 503 body for each status that cannot serve. */
export const REASONS: Readonly<Record<Exclude<PullStatus, typeof READY>, string>> = {
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
};

export const COLLECTION_FAILED = 'provide-telemetry: metrics collection failed';

/** What a pull reader offers: one collection per call. */
export interface PullReader {
  collect(): Promise<{ resourceMetrics: unknown }>;
}

type ReaderBase = abstract new () => PullReader;

/** The part of @opentelemetry/sdk-metrics the reader needs. */
export interface SdkMetricsModule {
  MetricReader: ReaderBase;
}

interface Serving {
  reader: PullReader;
  options: Omit<RenderOptions, 'utf8'>;
}

let _status: PullStatus = NOT_SET_UP;
let _serving: Serving | null = null;

/** Record a non-ready endpoint status, forgetting any reader. */
export function setPullStatus(status: Exclude<PullStatus, typeof READY>): void {
  _status = status;
  _serving = null;
}

/** Record that reader, attached to the installed provider, can serve. */
export function markPullReady(reader: PullReader, options: Omit<RenderOptions, 'utf8'>): void {
  _status = READY;
  _serving = { reader, options };
}

export function getPullStatus(): PullStatus {
  return _status;
}

/** The render options a config selects (scrape-time negotiation adds utf8). */
export function optionsFor(cfg: {
  prometheusTranslation: string;
  prometheusScopeLabels: boolean;
  prometheusTargetInfo: boolean;
}): Omit<RenderOptions, 'utf8'> {
  return {
    strategy: cfg.prometheusTranslation,
    scopeLabels: cfg.prometheusScopeLabels,
    targetInfo: cfg.prometheusTargetInfo,
    skip: HEALTH_METRIC_NAMES,
  };
}

/**
 * A pull reader subclassing the SDK's MetricReader, which is handed in.
 *
 * Cumulative, as Prometheus needs, because that is MetricReader's default
 * temporality whatever the OTLP reader prefers; the tests pin it. Flush and
 * shutdown have nothing to do, since nothing is pushed: collect() is the job.
 */
export function createPullReader(sdk: SdkMetricsModule): PullReader {
  class PrometheusPullReader extends sdk.MetricReader {
    protected async onForceFlush(): Promise<void> {}

    protected async onShutdown(): Promise<void> {}
  }
  return new PrometheusPullReader();
}

const SIGNALS = ['logs', 'traces', 'metrics'] as const;
type Signal = (typeof SIGNALS)[number];

function capitalized(signal: Signal): string {
  return signal.charAt(0).toUpperCase() + signal.slice(1);
}

// The health snapshot fields served per signal, in the spec's
// prometheus_metrics.health_metrics order: (snapshot key, metric, type).
const PER_SIGNAL: readonly [(s: Signal) => keyof HealthSnapshot, string, Family['kind']][] = [
  [(s) => `${s}Emitted` as keyof HealthSnapshot, 'provide_telemetry_emitted_total', 'counter'],
  [(s) => `${s}Dropped` as keyof HealthSnapshot, 'provide_telemetry_dropped_total', 'counter'],
  [
    (s) => `exportFailures${capitalized(s)}` as keyof HealthSnapshot,
    'provide_telemetry_export_failures_total',
    'counter',
  ],
  [
    (s) => `retries${capitalized(s)}` as keyof HealthSnapshot,
    'provide_telemetry_export_retries_total',
    'counter',
  ],
  [
    (s) => `exportLatencyMs${capitalized(s)}` as keyof HealthSnapshot,
    'provide_telemetry_export_latency_milliseconds',
    'gauge',
  ],
  [
    (s) => `asyncBlockingRisk${capitalized(s)}` as keyof HealthSnapshot,
    'provide_telemetry_async_blocking_risk_total',
    'counter',
  ],
  [
    (s) => `circuitState${capitalized(s)}` as keyof HealthSnapshot,
    'provide_telemetry_circuit_state',
    'gauge',
  ],
  [
    (s) => `circuitOpenCount${capitalized(s)}` as keyof HealthSnapshot,
    'provide_telemetry_circuit_open_total',
    'counter',
  ],
];

const SETUP_ERROR = 'provide_telemetry_setup_error';
const RECEIPT_FAILURES = 'provide_telemetry_receipt_failures_total';

/**
 * The collector's family names. Instruments of these names on the provider
 * (from PROVIDE_METRICS_HEALTH_OTLP) are left out of a scrape, which serves the
 * collector's copy instead, so each family appears once.
 */
export const HEALTH_METRIC_NAMES: ReadonlySet<string> = new Set([
  ...PER_SIGNAL.map(([, metric]) => metric),
  SETUP_ERROR,
  RECEIPT_FAILURES,
]);

const CIRCUIT_STATES: ReadonlyMap<string, number> = new Map([
  ['closed', 0],
  ['half-open', 1],
  ['open', 2],
]);
const CIRCUIT_UNKNOWN = -1;

/** The health snapshot as provide_telemetry_* families. */
export function healthFamilies(snapshot: HealthSnapshot): Family[] {
  const families = PER_SIGNAL.map(([key, metric, kind]) => {
    const fam = family(metric, kind);
    for (const signal of SIGNALS) {
      const raw = snapshot[key(signal)];
      // circuit_state is the one string field; the rest are already numbers.
      const value =
        typeof raw === 'string' ? (CIRCUIT_STATES.get(raw) ?? CIRCUIT_UNKNOWN) : Number(raw);
      fam.samples.push(['', { signal }, value]);
    }
    return fam;
  });
  const setupError = family(SETUP_ERROR, 'gauge');
  setupError.samples.push(['', {}, snapshot.setupError ? 1 : 0]);
  const receipts = family(RECEIPT_FAILURES, 'counter');
  receipts.samples.push(['', {}, snapshot.receiptFailures]);
  return [...families, setupError, receipts];
}

/** One rendered collection. */
export interface PrometheusResponseBody {
  body: string;
  contentType: string;
}

/**
 * Run one collection and return its body and content type in the text format.
 *
 * accept is the scraper's Accept header, if any; it decides whether UTF-8
 * names are allowed. Rejects with a TelemetryError naming the reason when
 * there is nothing to serve.
 */
export async function renderPrometheus(accept?: string): Promise<PrometheusResponseBody> {
  const serving = _serving;
  if (serving === null) {
    throw new TelemetryError(REASONS[_status as Exclude<PullStatus, typeof READY>]);
  }
  const utf8 = wantsUtf8(accept);
  const { resourceMetrics } = await serving.reader.collect();
  const families = [
    ...familiesFrom(resourceMetrics as ResourceMetricsLike, { ...serving.options, utf8 }),
    ...healthFamilies(getHealthSnapshot()),
  ];
  return { body: render(families), contentType: utf8 ? CONTENT_TYPE_UTF8 : CONTENT_TYPE_TEXT };
}

/** An HTTP answer: status, headers in send order, body. */
export interface PrometheusResponse {
  status: number;
  headers: [string, string][];
  body: string;
}

export const PLAIN_TEXT: [string, string] = ['content-type', 'text/plain; charset=utf-8'];

/** The answer to one scrape; shared by metricsHandler() and the listener. */
export async function responseFor(
  method: string,
  accept: string | undefined,
): Promise<PrometheusResponse> {
  if (method !== 'GET' && method !== 'HEAD') {
    return {
      status: 405,
      headers: [['allow', 'GET, HEAD'], PLAIN_TEXT],
      body: 'method not allowed\n',
    };
  }
  let rendered: PrometheusResponseBody;
  try {
    rendered = await renderPrometheus(accept);
  } catch (err) {
    const reason = err instanceof TelemetryError ? err.message : COLLECTION_FAILED;
    return { status: 503, headers: [PLAIN_TEXT], body: `${reason}\n` };
  }
  return {
    status: 200,
    headers: [['content-type', rendered.contentType]],
    body: method === 'GET' ? rendered.body : '',
  };
}

export function _resetPullForTests(): void {
  setPullStatus(NOT_SET_UP);
}
