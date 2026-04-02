// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SLO-oriented telemetry helpers (RED/USE baseline).
 * Mirrors Python provide.telemetry.slo.
 */

import {
  type CounterInstrument,
  type GaugeInstrument,
  type HistogramInstrument,
  counter,
  gauge,
  histogram,
} from './metrics';

const _counters = new Map<string, CounterInstrument>();
const _histograms = new Map<string, HistogramInstrument>();
const _gauges = new Map<string, GaugeInstrument>();

function _lazyCounter(name: string, description: string): CounterInstrument {
  let c = _counters.get(name);
  if (!c) {
    c = counter(name, { description });
    _counters.set(name, c);
  }
  return c;
}

function _lazyHistogram(name: string, description: string, unit: string): HistogramInstrument {
  let h = _histograms.get(name);
  if (!h) {
    h = histogram(name, { description, unit });
    _histograms.set(name, h);
  }
  return h;
}

function _lazyGauge(name: string, description: string, unit: string): GaugeInstrument {
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
  if (!getConfig().sloEnableRedMetrics) return;
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
  const g = _lazyGauge('resource.utilization', 'Resource utilization', opts.unit ?? '%');
  g.set(opts.utilization, { resource: opts.resource });
}

export interface ErrorClassification {
  errorType: 'server' | 'client' | 'timeout' | 'unknown';
  errorCode: number;
  errorName: string;
  category: 'server_error' | 'client_error' | 'timeout' | 'unknown';
  severity: 'critical' | 'warning' | 'info' | 'unknown';
  // OTel-aligned keys for cross-language parity with Go/Python
  'error.type': string;
  'error.category': string;
  'error.severity': string;
  'http.status_code': string;
}

export function classifyError(excName: string, statusCode: number): ErrorClassification {
  const isTimeout = statusCode === 0 || excName.toLowerCase().includes('timeout');

  if (isTimeout) {
    return {
      errorType: 'timeout',
      errorCode: statusCode,
      errorName: excName,
      category: 'timeout',
      severity: 'info',
      'error.type': excName,
      'error.category': 'timeout',
      'error.severity': 'info',
      'http.status_code': String(statusCode),
    };
  }
  if (statusCode >= 500) {
    return {
      errorType: 'server',
      errorCode: statusCode,
      errorName: excName,
      category: 'server_error',
      severity: 'critical',
      'error.type': excName,
      'error.category': 'server_error',
      'error.severity': 'critical',
      'http.status_code': String(statusCode),
    };
  }
  if (statusCode >= 400) {
    const sev = statusCode === 429 ? 'critical' : 'warning';
    return {
      errorType: 'client',
      errorCode: statusCode,
      errorName: excName,
      category: 'client_error',
      severity: sev as 'critical' | 'warning',
      'error.type': excName,
      'error.category': 'client_error',
      'error.severity': sev,
      'http.status_code': String(statusCode),
    };
  }
  return {
    errorType: 'unknown',
    errorCode: statusCode,
    errorName: excName,
    category: 'unknown',
    severity: 'unknown',
    'error.type': excName,
    'error.category': 'unknown',
    'error.severity': 'unknown',
    'http.status_code': String(statusCode),
  };
}

export function _resetSloForTests(): void {
  _counters.clear();
  _histograms.clear();
  _gauges.clear();
}
