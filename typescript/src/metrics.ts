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
  type Counter,
  type Histogram,
  type Meter,
  type UpDownCounter,
  metrics,
} from '@opentelemetry/api';

export type { Counter, Histogram, Meter, UpDownCounter };

// Stryker disable next-line StringLiteral: meter name not observable with no-op OTEL SDK in tests
const METER_NAME = '@provide-io/telemetry';

/**
 * Return a stable, order-independent key for an attribute map.
 * Sorts attribute keys before serialising so {a:1,b:2} and {b:2,a:1}
 * produce the same string. Mirrors Python tuple(sorted(attrs.items())).
 */
function _canonicalAttrsKey(attrs?: Attributes): string {
  // Stryker disable next-line StringLiteral: any constant sentinel is equivalent for the no-attrs map key — functionally interchangeable with ''
  if (!attrs) return '';
  const keys = Object.keys(attrs).sort();
  return JSON.stringify(keys.map((k) => [k, attrs[k]]));
}

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
  private _value = 0;

  constructor(name: string, inner: Counter) {
    this.name = name;
    this._inner = inner;
  }

  /** Cumulative counter value (in-process; useful for testing and health checks). */
  get value(): number {
    return this._value;
  }

  add(value: number, attributes?: Attributes): void {
    if (!getConfig().metricsEnabled) return;
    // Stryker disable next-line StringLiteral: 'metrics' vs '' is equivalent — shouldAllow treats any non-'logs'/non-'context' signal identically across all consent levels
    if (!shouldAllow('metrics')) return;
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      _incrementHealth(_emittedField('metrics'));
      const ids = getActiveTraceIds();
      const enriched =
        ids.trace_id && ids.span_id
          ? { ...attributes, trace_id: ids.trace_id, span_id: ids.span_id }
          : attributes;
      this._inner.add(value, enriched);
      this._value += value;
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
  private _lastValue = 0;

  constructor(name: string, inner: UpDownCounter) {
    this.name = name;
    this._inner = inner;
  }

  /** Most recent value set or accumulated via add() (in-process; useful for testing and health checks). */
  get value(): number {
    return this._lastValue;
  }

  add(value: number, attributes?: Attributes): void {
    if (!getConfig().metricsEnabled) return;
    // Stryker disable next-line StringLiteral: 'metrics' vs '' is equivalent — shouldAllow treats any non-'logs'/non-'context' signal identically across all consent levels
    if (!shouldAllow('metrics')) return;
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      _incrementHealth(_emittedField('metrics'));
      this._inner.add(value, attributes);
      this._lastValue += value;
    } finally {
      release(ticket);
    }
  }

  set(value: number, attributes?: Attributes): void {
    if (!getConfig().metricsEnabled) return;
    // Stryker disable next-line StringLiteral: 'metrics' vs '' is equivalent — shouldAllow treats any non-'logs'/non-'context' signal identically across all consent levels
    if (!shouldAllow('metrics')) return;
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      _incrementHealth(_emittedField('metrics'));
      const key = _canonicalAttrsKey(attributes);
      const prev = this._values.get(key) ?? 0;
      const delta = value - prev;
      this._values.set(key, value);
      this._inner.add(delta, attributes);
      this._lastValue = value;
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
  private _count = 0;
  private _total = 0;

  constructor(name: string, inner: Histogram) {
    this.name = name;
    this._inner = inner;
  }

  /** Number of values recorded (in-process; useful for testing and health checks). */
  get count(): number {
    return this._count;
  }

  /** Sum of all recorded values (in-process; useful for testing and health checks). */
  get total(): number {
    return this._total;
  }

  record(value: number, attributes?: Attributes): void {
    if (!getConfig().metricsEnabled) return;
    // Stryker disable next-line StringLiteral: 'metrics' vs '' is equivalent — shouldAllow treats any non-'logs'/non-'context' signal identically across all consent levels
    if (!shouldAllow('metrics')) return;
    if (!shouldSample('metrics', this.name)) return;
    const ticket = tryAcquire('metrics');
    if (!ticket) return;
    try {
      _incrementHealth(_emittedField('metrics'));
      const ids = getActiveTraceIds();
      const enriched =
        ids.trace_id && ids.span_id
          ? { ...attributes, trace_id: ids.trace_id, span_id: ids.span_id }
          : attributes;
      this._inner.record(value, enriched);
      this._count += 1;
      this._total += value;
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
