// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Metric instruments — mirrors Python undef.telemetry counter/gauge/histogram.
 *
 * Backed by @opentelemetry/api which provides no-op instruments when no SDK is registered.
 * Safe to call in any environment; instruments are always callable without setup.
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
const METER_NAME = '@undef/telemetry';

export interface MetricOptions {
  description?: string;
  unit?: string;
}

/**
 * Create a monotonically increasing counter.
 * Mirrors Python: counter(name, description, unit)
 */
export function counter(name: string, options?: MetricOptions): Counter {
  return metrics.getMeter(METER_NAME).createCounter(name, options);
}

/**
 * Create an up-down counter (gauge — can increase or decrease).
 * Mirrors Python: gauge(name, description, unit)
 */
export function gauge(name: string, options?: MetricOptions): UpDownCounter {
  return metrics.getMeter(METER_NAME).createUpDownCounter(name, options);
}

/**
 * Create a histogram for recording distributions (latencies, sizes).
 * Mirrors Python: histogram(name, description, unit)
 */
export function histogram(name: string, options?: MetricOptions): Histogram {
  return metrics.getMeter(METER_NAME).createHistogram(name, options);
}

/**
 * Return an OTEL Meter from the global meter provider.
 * Mirrors Python: get_meter(name)
 */
export function getMeter(name?: string): Meter {
  // Stryker disable next-line LogicalOperator: getMeter(undefined) behaves identically to getMeter(name) with no-op OTEL API
  return metrics.getMeter(name ?? METER_NAME);
}
