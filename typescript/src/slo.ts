// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SLO-oriented telemetry helpers (RED/USE baseline).
 * Mirrors Python provide.telemetry.slo.
 */

import type { Counter, Histogram, UpDownCounter } from '@opentelemetry/api';
import { counter, gauge, histogram } from './metrics';

const _counters = new Map<string, Counter>();
const _histograms = new Map<string, Histogram>();
const _gauges = new Map<string, UpDownCounter>();

function _lazyCounter(name: string, description: string): Counter {
  let c = _counters.get(name);
  if (!c) {
    c = counter(name, { description });
    _counters.set(name, c);
  }
  return c;
}

function _lazyHistogram(name: string, description: string, unit: string): Histogram {
  let h = _histograms.get(name);
  if (!h) {
    h = histogram(name, { description, unit });
    _histograms.set(name, h);
  }
  return h;
}

function _lazyGauge(name: string, description: string, unit: string): UpDownCounter {
  let g = _gauges.get(name);
  if (!g) {
    g = gauge(name, { description, unit });
    _gauges.set(name, g);
  }
  return g;
}

export function recordRedMetrics(opts: {
  route: string;
  method: string;
  statusCode: number;
  durationMs: number;
}): void {
  const attrs = {
    route: opts.route,
    method: opts.method,
    status_code: String(opts.statusCode),
  };
  _lazyCounter('http.requests.total', 'Total HTTP requests').add(1, attrs);
  if (opts.statusCode >= 500) {
    // Stryker disable next-line StringLiteral: error counter description is not tested
    _lazyCounter('http.errors.total', 'Total HTTP errors').add(1, attrs);
  }
  _lazyHistogram('http.request.duration_ms', 'HTTP request latency', 'ms').record(
    opts.durationMs,
    attrs,
  );
}

export function recordUseMetrics(opts: {
  resource: string;
  utilization: number;
  unit?: string;
}): void {
  _lazyGauge('resource.utilization', 'Resource utilization', opts.unit ?? '%').add(
    opts.utilization,
    { resource: opts.resource },
  );
}

export function classifyError(statusCode: number): {
  errorType: 'server' | 'client' | 'none';
  errorCode: number;
  errorName: string;
} {
  if (statusCode >= 500) {
    return { errorType: 'server', errorCode: statusCode, errorName: 'ServerError' };
  }
  if (statusCode >= 400) {
    return { errorType: 'client', errorCode: statusCode, errorName: 'ClientError' };
  }
  return { errorType: 'none', errorCode: statusCode, errorName: '' };
}

export function _resetSloForTests(): void {
  _counters.clear();
  _histograms.clear();
  _gauges.clear();
}
