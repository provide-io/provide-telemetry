// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/** The Prometheus pull path: status, health families, rendering and the shared response. */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { must } from './support/must.js';
import * as sdkMetrics from '@opentelemetry/sdk-metrics';
import { TelemetryError } from '../src/exceptions.js';
import { _resetHealthForTests, getHealthSnapshot, setSetupError } from '../src/health.js';
import {
  _resetPullForTests,
  COLLECTION_FAILED,
  createPullReader,
  getPullStatus,
  healthFamilies,
  HEALTH_METRIC_NAMES,
  HOST_PROVIDER,
  markPullReady,
  METRICS_DISABLED,
  NOT_SET_UP,
  optionsFor,
  PLAIN_TEXT,
  READY,
  REASONS,
  renderPrometheus,
  responseFor,
  setPullStatus,
  SHUT_DOWN,
  type PullReader,
  type SdkMetricsModule,
} from '../src/prom-pull.js';
import { CONTENT_TYPE_TEXT, CONTENT_TYPE_UTF8 } from '../src/prom-render.js';
import { promFixtures, snapshotFrom } from './support/prometheus-fixtures.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
const DEFAULT_OPTIONS = {
  strategy: 'UnderscoreEscapingWithSuffixes',
  scopeLabels: false,
  targetInfo: true,
};

function fakeReader(resourceMetrics: unknown = undefined): PullReader & { collected: number } {
  return {
    collected: 0,
    async collect() {
      this.collected += 1;
      return { resourceMetrics };
    },
  };
}

const APP_REQUESTS = {
  resource: { attributes: { 'service.name': 'x' } },
  scopeMetrics: [
    {
      scope: { name: 's' },
      metrics: [
        {
          descriptor: { name: 'app.requests', unit: '', description: '' },
          dataPointType: 3,
          isMonotonic: true,
          dataPoints: [{ attributes: {}, value: 2 }],
        },
      ],
    },
  ],
};

beforeEach(() => {
  _resetPullForTests();
  _resetHealthForTests();
});
afterEach(() => {
  _resetPullForTests();
  _resetHealthForTests();
});

describe('status and reasons', () => {
  for (const status of Object.keys(REASONS) as (keyof typeof REASONS)[]) {
    it(`${status} is a 503 naming its reason`, async () => {
      setPullStatus(status);
      expect(getPullStatus()).toBe(status);
      await expect(renderPrometheus()).rejects.toThrow(TelemetryError);
      await expect(renderPrometheus()).rejects.toThrow(REASONS[status]);
      const res = await responseFor('GET', undefined);
      expect(res).toEqual({
        status: 503,
        headers: [['content-type', 'text/plain; charset=utf-8']],
        body: `${REASONS[status]}\n`,
      });
    });
  }

  it('reasons cover the fixture states', () => {
    const states = new Set(
      (promFixtures['handler_status'] as any[]).map((c) => c['state'] as string),
    );
    expect(states).toEqual(
      new Set([NOT_SET_UP, SHUT_DOWN, METRICS_DISABLED, HOST_PROVIDER, READY]),
    );
    for (const s of states)
      if (s !== READY) expect(REASONS[s as keyof typeof REASONS]).toBeTruthy();
  });

  it('starts not set up, and reset returns there', () => {
    markPullReady(fakeReader(), DEFAULT_OPTIONS);
    expect(getPullStatus()).toBe(READY);
    _resetPullForTests();
    expect(getPullStatus()).toBe(NOT_SET_UP);
  });

  it('setPullStatus forgets the reader', async () => {
    markPullReady(fakeReader(), DEFAULT_OPTIONS);
    setPullStatus(SHUT_DOWN);
    await expect(renderPrometheus()).rejects.toThrow('shut down');
  });

  it('each reason is one line starting with the library name', () => {
    for (const reason of Object.values(REASONS)) {
      expect(reason.startsWith('provide-telemetry: ')).toBe(true);
      expect(reason).not.toContain('\n');
    }
    expect(PLAIN_TEXT).toEqual(['content-type', 'text/plain; charset=utf-8']);
  });
});

describe('handler_status fixtures', () => {
  const states: Record<string, () => void> = {
    not_set_up: () => setPullStatus(NOT_SET_UP),
    shut_down: () => setPullStatus(SHUT_DOWN),
    metrics_disabled: () => setPullStatus(METRICS_DISABLED),
    host_provider: () => setPullStatus(HOST_PROVIDER),
    ready: () => markPullReady(fakeReader(), DEFAULT_OPTIONS),
  };
  for (const c of promFixtures['handler_status'] as any[]) {
    it(c['id'] as string, async () => {
      must(states[c['state'] as string])();
      const res = await responseFor((c['method'] as string | undefined) ?? 'GET', undefined);
      expect(res.status).toBe(c['status']);
      if (c['content_type_prefix']) {
        expect(must(res.headers[0])[1].startsWith(c['content_type_prefix'] as string)).toBe(true);
      }
    });
  }
});

describe('serving', () => {
  it('a ready reader serves metrics and health, one collection per call', async () => {
    const reader = fakeReader();
    markPullReady(reader, DEFAULT_OPTIONS);
    const { body, contentType } = await renderPrometheus();
    expect(contentType).toBe(CONTENT_TYPE_TEXT);
    expect(body).toContain('provide_telemetry_emitted_total{signal="metrics"} 0');
    expect(reader.collected).toBe(1);
    const utf8 = await renderPrometheus('text/plain;version=1.0.0;escaping=allow-utf-8');
    expect(utf8.contentType).toBe(CONTENT_TYPE_UTF8);
    expect(reader.collected).toBe(2);
  });

  it('health is read after the collection', async () => {
    const reader: PullReader = {
      async collect() {
        setSetupError('during collection');
        return { resourceMetrics: undefined };
      },
    };
    markPullReady(reader, DEFAULT_OPTIONS);
    expect((await renderPrometheus()).body).toContain('provide_telemetry_setup_error 1\n');
  });

  it('scrape options pass through to the renderer', async () => {
    markPullReady(fakeReader(APP_REQUESTS), {
      strategy: 'NoTranslation',
      scopeLabels: true,
      targetInfo: false,
    });
    const utf8 = (await renderPrometheus('text/plain;escaping=allow-utf-8')).body;
    expect(utf8).toContain('{"app.requests",otel_scope_name="s"} 2');
    expect(utf8).not.toContain('target_info');
    expect((await renderPrometheus()).body).toContain('app_requests{otel_scope_name="s"} 2');
  });

  it('responses for each method', async () => {
    markPullReady(fakeReader(), DEFAULT_OPTIONS);
    expect(await responseFor('POST', undefined)).toEqual({
      status: 405,
      headers: [
        ['allow', 'GET, HEAD'],
        ['content-type', 'text/plain; charset=utf-8'],
      ],
      body: 'method not allowed\n',
    });
    const head = await responseFor('HEAD', undefined);
    expect(head).toEqual({ status: 200, headers: [['content-type', CONTENT_TYPE_TEXT]], body: '' });
    const get = await responseFor('GET', 'text/plain;escaping=allow-utf-8');
    expect(get.headers).toEqual([['content-type', CONTENT_TYPE_UTF8]]);
    expect(get.body.startsWith('# TYPE provide_telemetry')).toBe(true);
  });

  it('a collection that fails is a 503, not a crash', async () => {
    markPullReady(
      {
        collect: () => Promise.reject(new Error('boom')),
      },
      DEFAULT_OPTIONS,
    );
    expect(await responseFor('GET', undefined)).toEqual({
      status: 503,
      headers: [['content-type', 'text/plain; charset=utf-8']],
      body: `${COLLECTION_FAILED}\n`,
    });
  });

  it('optionsFor reads the Prometheus config', () => {
    expect(
      optionsFor({
        prometheusTranslation: 'NoTranslation',
        prometheusScopeLabels: true,
        prometheusTargetInfo: false,
      }),
    ).toEqual({
      strategy: 'NoTranslation',
      scopeLabels: true,
      targetInfo: false,
      skip: HEALTH_METRIC_NAMES,
    });
  });

  it('HEALTH_METRIC_NAMES lists every health family', () => {
    const names = healthFamilies(getHealthSnapshot()).map((f) => f.name);
    expect([...HEALTH_METRIC_NAMES].sort()).toEqual([...names].sort());
    expect(HEALTH_METRIC_NAMES.size).toBe(11);
  });
});

describe('health_metrics fixtures', () => {
  const full = (promFixtures['health_metrics'] as any[])[0]['snapshot'] as Record<string, any>;
  for (const c of promFixtures['health_metrics'] as any[]) {
    it(c['id'] as string, () => {
      const values = { ...full, ...((c['snapshot_overrides'] as Record<string, any>) ?? {}) };
      const families = healthFamilies(snapshotFrom(values));
      const got = new Map<string, number>();
      for (const f of families) {
        for (const [, labels, value] of f.samples)
          got.set(`${f.name}${JSON.stringify(labels)}`, value);
      }
      for (const want of c['expected_samples'] as any[]) {
        const key = `${want['metric'] as string}${JSON.stringify(want['labels'])}`;
        expect(got.get(key), key).toBe(want['value']);
      }
      if (c['id'] === 'full_snapshot') {
        expect(got.size).toBe((c['expected_samples'] as unknown[]).length);
      }
    });
  }

  it('the snapshot converter produces every HealthSnapshot field', () => {
    expect(Object.keys(snapshotFrom(full)).sort()).toEqual(Object.keys(getHealthSnapshot()).sort());
  });

  it('family types, an unknown circuit state and the empty defaults', () => {
    const snapshot = {
      ...getHealthSnapshot(),
      circuitStateLogs: 'weird',
      circuitStateTraces: 'constructor',
    };
    const families = new Map(healthFamilies(snapshot).map((f) => [f.name, f]));
    expect(must(families.get('provide_telemetry_circuit_state')).samples.slice(0, 2)).toEqual([
      ['', { signal: 'logs' }, -1],
      ['', { signal: 'traces' }, -1],
    ]);
    expect(must(families.get('provide_telemetry_export_latency_milliseconds')).kind).toBe('gauge');
    expect(must(families.get('provide_telemetry_circuit_state')).kind).toBe('gauge');
    expect(must(families.get('provide_telemetry_emitted_total')).kind).toBe('counter');
    expect(must(families.get('provide_telemetry_setup_error')).kind).toBe('gauge');
    expect(must(families.get('provide_telemetry_setup_error')).samples).toEqual([['', {}, 0]]);
    expect(must(families.get('provide_telemetry_receipt_failures_total')).kind).toBe('counter');
    expect(must(families.get('provide_telemetry_receipt_failures_total')).samples).toEqual([
      ['', {}, 0],
    ]);
    expect(
      must(families.get('provide_telemetry_reserved_field_replacements_total')).samples,
    ).toEqual([['', {}, 0]]);
    expect(must(families.get('provide_telemetry_emitted_total')).help).toBe('');
    expect(families.size).toBe(11);
  });
});

describe('createPullReader against the real SDK', () => {
  it('is cumulative whatever the provider, and collects what was recorded', async () => {
    const reader = createPullReader(
      sdkMetrics as unknown as SdkMetricsModule,
    ) as sdkMetrics.MetricReader;
    for (const type of Object.values(sdkMetrics.InstrumentType)) {
      expect(reader.selectAggregationTemporality(type)).toBe(
        sdkMetrics.AggregationTemporality.CUMULATIVE,
      );
    }
    const provider = new sdkMetrics.MeterProvider({ readers: [reader] });
    const c = provider.getMeter('t').createCounter('pulled');
    c.add(2);
    await reader.collect();
    c.add(3);
    markPullReady(reader, DEFAULT_OPTIONS);
    expect((await renderPrometheus()).body).toContain('pulled_total 5\n');
    await reader.forceFlush();
    await provider.shutdown();
  });
});
