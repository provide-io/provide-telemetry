// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * PROVIDE_METRICS_HEALTH_OTLP: the health series as observable instruments.
 *
 * See prometheus_metrics.health_metrics.health_otlp in spec/telemetry-api.yaml.
 * Each health family becomes one observable instrument, named verbatim, on the
 * provider registerOtelProviders() installs, so the series are exported over
 * OTLP too. The observations describe the SDK rather than user data: they are
 * not consent-gated and do not count toward emitted metrics. The pull renderer
 * skips these instruments, so a scrape carries only the collector's copy.
 * Mirrors Python provide.telemetry.metrics._health_otlp.
 */

import type { Meter } from '@opentelemetry/api';
import { getHealthSnapshot } from './health.js';
import { healthFamilies } from './prom-pull.js';

/** Create one observable per health family on meter. */
export function registerHealthOtlp(meter: Meter): void {
  for (const fam of healthFamilies(getHealthSnapshot())) {
    const instrument =
      fam.kind === 'counter'
        ? meter.createObservableCounter(fam.name)
        : meter.createObservableGauge(fam.name);
    instrument.addCallback((result) => {
      // A fresh snapshot each collection; the family is always there by name.
      const current = healthFamilies(getHealthSnapshot()).find(
        (f) => f.name === fam.name,
      ) as typeof fam;
      for (const [, labels, value] of current.samples) result.observe(value, labels);
    });
  }
}
