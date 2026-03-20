// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * SLO-oriented telemetry helpers (RED/USE baseline).
 * Mirrors Python undef.telemetry.slo.
 */

import type { Counter, Histogram, UpDownCounter } from '@opentelemetry/api';
import { counter, gauge, histogram } from './metrics';

const _counters = new Map<string, Counter>();
const _histograms = new Map<string, Histogram>();
const _gauges = new Map<string, UpDownCounter>();

function _lazyCounter(name: string, description: string): Counter {
  if (!_counters.has(name)) _counters.set(name, counter(name, { description }));
  return _counters.get(name)!;
}

function _lazyHistogram(name: string, description: string, unit: string): Histogram {
  if (!_histograms.has(name))
    _histograms.set(name, histogram(name, { description, unit }));
  return _histograms.get(name)!;
}

function _lazyGauge(name: string, description: string, unit: string): UpDownCounter {
  if (!_gauges.has(name)) _gauges.set(name, gauge(name, { description, unit }));
  return _gauges.get(name)!;
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
  _lazyGauge(
    'resource.utilization',
    'Resource utilization',
    opts.unit ?? '%',
  ).add(opts.utilization, { resource: opts.resource });
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
