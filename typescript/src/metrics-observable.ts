// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Observable (callback-reported) instruments.
 *
 * See prometheus_metrics.observable_instruments in spec/telemetry-api.yaml. A
 * callback runs at each collection (every scrape for Prometheus, every export
 * interval for OTLP) and returns the current observations. Like the
 * synchronous instruments, an observable binds to the provider live at
 * creation: create it after registerOtelProviders(), or its callback never
 * runs. Mirrors Python provide.telemetry.metrics.observable.
 */

import {
  metrics,
  type Attributes,
  type Observable,
  type ObservableCallback as OtelObservableCallback,
} from '@opentelemetry/api';
import { getConfig } from './config.js';
import { shouldAllow } from './consent.js';
import { _emittedField, _incrementHealth } from './health.js';
import type { MetricOptions } from './metrics.js';
import { _isLiveMeterProviderInstalled } from './otel-probe.js';

// Stryker disable next-line StringLiteral: meter name not observable through the API's no-op meter
const METER_NAME = '@provide-io/telemetry';

/** One value an observable instrument's callback reports. */
export interface Observation {
  value: number;
  attributes?: Attributes;
}

/** Reports the current observations; may be async. */
export type ObservableCallback = () => Iterable<Observation> | Promise<Iterable<Observation>>;

type Factory =
  'createObservableCounter' | 'createObservableGauge' | 'createObservableUpDownCounter';

/** A registered observable; unregister() stops its callback. */
export class ObservableInstrument {
  readonly name: string;
  private _detach: (() => void) | undefined;
  private _failures = 0;

  constructor(name: string) {
    this.name = name;
  }

  /** Whether the callback is attached to a provider and not unregistered. */
  get registered(): boolean {
    return this._detach !== undefined;
  }

  /** How many collections the callback has failed in. */
  get failures(): number {
    return this._failures;
  }

  /** Stop the callback. Calling it again, or on an unattached instrument, is a no-op. */
  unregister(): void {
    const detach = this._detach;
    this._detach = undefined;
    if (detach) detach();
  }

  /** @internal */
  _attach(detach: () => void): void {
    this._detach = detach;
  }

  /** @internal Count a failed collection, warning on the first only. */
  _failed(err: unknown): void {
    this._failures += 1;
    if (this._failures === 1) {
      console.warn(
        `[provide/telemetry] metrics.observable_callback_failed: ${this.name}: ${String(err)}`,
      );
    }
  }
}

/** The collection-time metrics gates: the enabled flag and consent. */
function metricsAllowed(): boolean {
  // Stryker disable next-line StringLiteral: 'metrics' vs '' is equivalent — shouldAllow treats any non-'logs'/non-'context' signal identically across all consent levels
  return getConfig().metricsEnabled && shouldAllow('metrics');
}

function collector(
  handle: ObservableInstrument,
  callback: ObservableCallback,
): OtelObservableCallback {
  return async (result) => {
    if (!metricsAllowed()) return;
    let observations: Observation[];
    try {
      observations = Array.from(await callback());
    } catch (err) {
      handle._failed(err);
      return;
    }
    for (const o of observations) {
      result.observe(o.value, o.attributes);
      _incrementHealth(_emittedField('metrics'));
    }
  };
}

function register(
  factory: Factory,
  name: string,
  callback: ObservableCallback,
  options?: MetricOptions,
): ObservableInstrument {
  const handle = new ObservableInstrument(name);
  if (!_isLiveMeterProviderInstalled()) return handle;
  let instrument: Observable;
  try {
    instrument = metrics.getMeter(METER_NAME)[factory](name, options);
  } catch (err) {
    console.warn(`[provide/telemetry] metrics.observable.create_failed: ${name}: ${String(err)}`);
    return handle;
  }
  const otelCallback = collector(handle, callback);
  instrument.addCallback(otelCallback);
  handle._attach(() => instrument.removeCallback(otelCallback));
  return handle;
}

/** Register callback as a monotonic counter reporting cumulative totals. */
export function observableCounter(
  name: string,
  callback: ObservableCallback,
  options?: MetricOptions,
): ObservableInstrument {
  return register('createObservableCounter', name, callback, options);
}

/** Register callback as a gauge; a series it stops reporting disappears from the next collection. */
export function observableGauge(
  name: string,
  callback: ObservableCallback,
  options?: MetricOptions,
): ObservableInstrument {
  return register('createObservableGauge', name, callback, options);
}

/** Register callback as a non-monotonic sum. */
export function observableUpDownCounter(
  name: string,
  callback: ObservableCallback,
  options?: MetricOptions,
): ObservableInstrument {
  return register('createObservableUpDownCounter', name, callback, options);
}
