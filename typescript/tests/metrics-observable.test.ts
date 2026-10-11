// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/** Observable instruments, against a real MeterProvider on the OTel global. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { metrics } from '@opentelemetry/api';
import { MeterProvider, MetricReader } from '@opentelemetry/sdk-metrics';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { resetConsentForTests, setConsentLevel } from '../src/consent.js';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health.js';
import {
  ObservableInstrument,
  observableCounter,
  observableGauge,
  observableUpDownCounter,
} from '../src/metrics-observable.js';
import { render, familiesFrom, type ResourceMetricsLike } from '../src/prom-render.js';

class TestReader extends MetricReader {
  protected async onForceFlush(): Promise<void> {}
  protected async onShutdown(): Promise<void> {}
}

let reader: TestReader;
let provider: MeterProvider;

async function scrape(): Promise<string> {
  const { resourceMetrics } = await reader.collect();
  return render(
    familiesFrom(resourceMetrics as unknown as ResourceMetricsLike, {
      strategy: 'UnderscoreEscapingWithSuffixes',
      scopeLabels: false,
      targetInfo: false,
      utf8: false,
    }),
  );
}

beforeEach(() => {
  _resetHealthForTests();
  resetConsentForTests();
  _resetConfig();
  reader = new TestReader();
  provider = new MeterProvider({ readers: [reader] });
  metrics.setGlobalMeterProvider(provider);
});

afterEach(async () => {
  metrics.disable();
  await provider.shutdown();
  resetConsentForTests();
  _resetConfig();
  vi.restoreAllMocks();
});

describe('observable instruments', () => {
  it('report at each collection with the right type and unit', async () => {
    let temperature = 41.5;
    const g = observableGauge(
      'room.temperature',
      () => [{ value: temperature, attributes: { room: 'a' } }],
      {
        unit: 'Cel',
        description: 'Room temperature',
      },
    );
    const c = observableCounter('jobs.done', () => [{ value: 7 }]);
    const u = observableUpDownCounter('queue.depth', () => [{ value: -2 }]);
    expect([g.registered, c.registered, u.registered]).toEqual([true, true, true]);
    const first = await scrape();
    expect(first).toContain('# HELP room_temperature_celsius Room temperature\n');
    expect(first).toContain(
      '# TYPE room_temperature_celsius gauge\nroom_temperature_celsius{room="a"} 41.5\n',
    );
    expect(first).toContain('# TYPE jobs_done_total counter\njobs_done_total 7\n');
    expect(first).toContain('# TYPE queue_depth gauge\nqueue_depth -2\n');
    temperature = 20;
    expect(await scrape()).toContain('room_temperature_celsius{room="a"} 20\n');
    expect(getHealthSnapshot().metricsEmitted).toBe(6);
  });

  it('accepts async callbacks and any iterable', async () => {
    observableGauge('async.value', async () => new Set([{ value: 3 }]));
    expect(await scrape()).toContain('async_value 3\n');
  });

  it('a failing callback contributes nothing, never fails the collection, and warns once', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const bad = observableGauge('bad.value', () => {
      throw new Error('broken');
    });
    observableGauge('good.value', () => [{ value: 1 }]);
    const out = await scrape();
    expect(out).toContain('good_value 1\n');
    expect(out).not.toContain('bad_value');
    expect(warn).toHaveBeenCalledTimes(1);
    await scrape();
    expect(bad.failures).toBe(2);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      '[provide/telemetry] metrics.observable_callback_failed: bad.value: Error: broken',
    );
  });

  it('a rejecting async callback is a failure too', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const bad = observableGauge('rejects', () => Promise.reject(new Error('later')));
    await scrape();
    expect(bad.failures).toBe(1);
  });

  it('unregister stops the callback and is idempotent', async () => {
    const callback = vi.fn(() => [{ value: 1 }]);
    const g = observableGauge('dropped.value', callback);
    await scrape();
    expect(callback).toHaveBeenCalledTimes(1);
    g.unregister();
    expect(g.registered).toBe(false);
    g.unregister();
    await scrape();
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('observes nothing while metrics are disabled', async () => {
    const callback = vi.fn(() => [{ value: 1 }]);
    observableGauge('gated.value', callback);
    setupTelemetry({ metricsEnabled: false });
    expect(await scrape()).not.toContain('gated_value 1');
    expect(callback).not.toHaveBeenCalled();
    setupTelemetry({ metricsEnabled: true });
    expect(await scrape()).toContain('gated_value 1\n');
  });

  it('observes nothing when consent denies metrics', async () => {
    const callback = vi.fn(() => [{ value: 1 }]);
    observableGauge('consent.value', callback);
    setConsentLevel('NONE');
    await scrape();
    expect(callback).not.toHaveBeenCalled();
    expect(getHealthSnapshot().metricsEmitted).toBe(0);
  });

  it('a creation error is logged and leaves an unattached handle', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(metrics, 'getMeter').mockReturnValue({
      createObservableGauge: () => {
        throw new Error('no');
      },
    } as never);
    const g = observableGauge('x', () => []);
    expect(g.registered).toBe(false);
    expect(warn).toHaveBeenCalledWith(
      '[provide/telemetry] metrics.observable.create_failed: x: Error: no',
    );
  });
});

describe('observables created with no live provider', () => {
  it('never run their callback and unregister is a no-op', async () => {
    metrics.disable();
    const callback = vi.fn(() => [{ value: 1 }]);
    const g = observableCounter('early', callback);
    expect(g).toBeInstanceOf(ObservableInstrument);
    expect(g.name).toBe('early');
    expect(g.registered).toBe(false);
    g.unregister();
    metrics.setGlobalMeterProvider(provider);
    await scrape();
    expect(callback).not.toHaveBeenCalled();
    expect(g.failures).toBe(0);
  });
});
