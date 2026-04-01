// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Metric instruments — mirrors Python provide.telemetry counter/gauge/histogram.
 *
 * Backed by @opentelemetry/api which provides no-op instruments when no SDK is registered.
 * Safe to call in any environment; instruments are always callable without setup.
 *
 * Wrapper classes gate every `.add()`/`.record()` call through sampling + backpressure,
 * matching the Python fallback.py pattern.
 */

import {
  type Attributes,
  type Counter,
  type Histogram,
  type Meter,
  type UpDownCounter,
  metrics,
} from '@opentelemetry/api';
import { shouldSample } from './sampling';
import { tryAcquire, release } from './backpressure';
import { getActiveTraceIds } from './tracing';

export type { Counter, Histogram, Meter, UpDownCounter };

// Stryker disable next-line StringLiteral: meter name not observable with no-op OTEL SDK in tests
const METER_NAME = '@provide-io/telemetry';

export interface MetricOptions {
  description?: string;
  unit?: string;
}

/**
 * Wrapper around OTel Counter that gates add() through sampling + backpressure.
 */
export class CounterInstrument {
  readonly name: string;
  private readonly _inner: Counter;

  constructor(name: string, inner: Counter) {
    this.name = name;
    this._inner = inner;
  }

  add(value: number, attributes?: Attributes): void {
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      const ids = getActiveTraceIds();
      const enriched =
        ids.trace_id && ids.span_id
          ? { ...attributes, trace_id: ids.trace_id, span_id: ids.span_id }
          : attributes;
      this._inner.add(value, enriched);
    } finally {
      release(ticket);
    }
  }
}

/**
 * Wrapper around OTel UpDownCounter with set semantics.
 * Gates add()/set() through sampling + backpressure.
 */
export class GaugeInstrument {
  readonly name: string;
  private readonly _inner: UpDownCounter;
  private readonly _values: Map<string, number> = new Map();

  constructor(name: string, inner: UpDownCounter) {
    this.name = name;
    this._inner = inner;
  }

  add(value: number, attributes?: Attributes): void {
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      this._inner.add(value, attributes);
    } finally {
      release(ticket);
    }
  }

  set(value: number, attributes?: Attributes): void {
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      const key = attributes ? JSON.stringify(attributes) : '';
      const prev = this._values.get(key) ?? 0;
      const delta = value - prev;
      this._values.set(key, value);
      this._inner.add(delta, attributes);
    } finally {
      release(ticket);
    }
  }
}

/**
 * Wrapper around OTel Histogram that gates record() through sampling + backpressure.
 */
export class HistogramInstrument {
  readonly name: string;
  private readonly _inner: Histogram;

  constructor(name: string, inner: Histogram) {
    this.name = name;
    this._inner = inner;
  }

  record(value: number, attributes?: Attributes): void {
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      const ids = getActiveTraceIds();
      const enriched =
        ids.trace_id && ids.span_id
          ? { ...attributes, trace_id: ids.trace_id, span_id: ids.span_id }
          : attributes;
      this._inner.record(value, enriched);
    } finally {
      release(ticket);
    }
  }
}

/**
 * Create a monotonically increasing counter.
 * Mirrors Python: counter(name, description, unit)
 */
export function counter(name: string, options?: MetricOptions): CounterInstrument {
  const inner = metrics.getMeter(METER_NAME).createCounter(name, options);
  return new CounterInstrument(name, inner);
}

/**
 * Create an up-down counter (gauge — can increase or decrease).
 * Mirrors Python: gauge(name, description, unit)
 */
export function gauge(name: string, options?: MetricOptions): GaugeInstrument {
  const inner = metrics.getMeter(METER_NAME).createUpDownCounter(name, options);
  return new GaugeInstrument(name, inner);
}

/**
 * Create a histogram for recording distributions (latencies, sizes).
 * Mirrors Python: histogram(name, description, unit)
 */
export function histogram(name: string, options?: MetricOptions): HistogramInstrument {
  const inner = metrics.getMeter(METER_NAME).createHistogram(name, options);
  return new HistogramInstrument(name, inner);
}

/**
 * Return an OTEL Meter from the global meter provider.
 * Mirrors Python: get_meter(name)
 */
export function getMeter(name?: string): Meter {
  // Stryker disable next-line LogicalOperator: getMeter(undefined) behaves identically to getMeter(name) with no-op OTEL API
  return metrics.getMeter(name ?? METER_NAME);
}
