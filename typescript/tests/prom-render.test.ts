// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Text exposition rendering, driven by plain objects shaped like the SDK's
 * ResourceMetrics; the last cases render what a real MeterProvider collects.
 */

import { describe, expect, it } from 'vitest';
import { MeterProvider, MetricReader } from '@opentelemetry/sdk-metrics';
import {
  CONTENT_TYPE_TEXT,
  CONTENT_TYPE_UTF8,
  effectiveStrategy,
  family,
  familiesFrom,
  formatValue,
  render,
  translateLabels,
  wantsUtf8,
  type MetricLike,
  type PointLike,
  type RenderOptions,
  type ResourceMetricsLike,
} from '../src/prom-render.js';

const SUM = 3;
const GAUGE = 2;
const HISTOGRAM = 0;
const EXPONENTIAL = 1;

function point(value: number, attributes: Record<string, unknown> = {}): PointLike {
  return { value, attributes };
}

function metric(
  name: string,
  dataPointType: number,
  dataPoints: PointLike[],
  extra: { unit?: string; description?: string; isMonotonic?: boolean } = {},
): MetricLike {
  return {
    descriptor: { name, unit: extra.unit ?? '', description: extra.description ?? '' },
    dataPointType,
    isMonotonic: extra.isMonotonic ?? true,
    dataPoints,
  };
}

function data(
  metrics: MetricLike[],
  opts: { scope?: { name: string; version?: string }; resource?: Record<string, unknown> } = {},
): ResourceMetricsLike {
  return {
    resource: { attributes: opts.resource ?? { 'service.name': 'svc' } },
    scopeMetrics: [
      { scope: opts.scope ?? { name: 'provide.telemetry', version: '1.2.3' }, metrics },
    ],
  };
}

/** The last sample line of a rendered body (it ends with a newline). */
function lastLine(out: string): string | undefined {
  const lines = out.split('\n');
  return lines[lines.length - 2];
}

function text(
  collected: ResourceMetricsLike | undefined,
  opts: Partial<RenderOptions> = {},
): string {
  return render(
    familiesFrom(collected, {
      strategy: 'UnderscoreEscapingWithSuffixes',
      scopeLabels: false,
      targetInfo: true,
      utf8: false,
      ...opts,
    }),
  );
}

describe('prom-render', () => {
  it('renders counter, gauge and up-down counter with types and help, sorted by name', () => {
    const out = text(
      data([
        metric('app.requests', SUM, [point(3, { route: '/a' })], {
          description: 'Requests\nserved',
        }),
        metric('app.cpu', GAUGE, [point(0.5)], { unit: '1' }),
        metric('app.queue', SUM, [point(-2)], { isMonotonic: false }),
      ]),
      { targetInfo: false },
    );
    expect(out).toBe(
      '# TYPE app_cpu_ratio gauge\n' +
        'app_cpu_ratio 0.5\n' +
        '# TYPE app_queue gauge\n' +
        'app_queue -2\n' +
        '# HELP app_requests_total Requests\\nserved\n' +
        '# TYPE app_requests_total counter\n' +
        'app_requests_total{route="/a"} 3\n',
    );
  });

  it('histogram buckets are cumulative with +Inf, sum and count', () => {
    const p: PointLike = {
      attributes: { k: 'v' },
      value: { buckets: { boundaries: [0.5, 10], counts: [1, 2, 3] }, sum: 12.5, count: 6 },
    };
    const out = text(data([metric('lat', HISTOGRAM, [p], { unit: 'ms' })]), { targetInfo: false });
    expect(out.split('\n').slice(0, -1)).toEqual([
      '# TYPE lat_milliseconds histogram',
      'lat_milliseconds_bucket{k="v",le="0.5"} 1',
      'lat_milliseconds_bucket{k="v",le="10"} 3',
      'lat_milliseconds_bucket{k="v",le="+Inf"} 6',
      'lat_milliseconds_sum{k="v"} 12.5',
      'lat_milliseconds_count{k="v"} 6',
    ]);
  });

  it('a histogram without a sum reports 0', () => {
    const p: PointLike = {
      attributes: {},
      value: { buckets: { boundaries: [], counts: [2] }, count: 2 },
    };
    expect(text(data([metric('h', HISTOGRAM, [p])]), { targetInfo: false })).toContain('h_sum 0\n');
  });

  it('target_info and scope labels', () => {
    const out = text(
      data([metric('c', SUM, [point(1)])], {
        resource: { 'service.name': 'svc', 'host.name': 'h1' },
      }),
      { scopeLabels: true },
    );
    expect(out).toContain('target_info{service_name="svc",host_name="h1"} 1');
    expect(out).toContain('# HELP target_info Target metadata\n# TYPE target_info gauge\n');
    expect(out).toContain(
      'c_total{otel_scope_name="provide.telemetry",otel_scope_version="1.2.3"} 1',
    );
  });

  it('target_info can be switched off', () => {
    expect(text(data([metric('c', SUM, [point(1)])]), { targetInfo: false })).not.toContain(
      'target_info',
    );
  });

  it('scope without version and resource without attributes', () => {
    const out = text(
      data([metric('c', SUM, [point(1)])], { scope: { name: 'provide.telemetry' }, resource: {} }),
      { scopeLabels: true },
    );
    expect(out).toContain('c_total{otel_scope_name="provide.telemetry"} 1');
    expect(out).not.toContain('target_info');
  });

  it('reserved and untranslatable attributes are dropped, not the sample', () => {
    const out = text(
      data([metric('c', SUM, [point(1, { __internal: 'x', ___: 'y', kept: 'z' })])]),
      {
        strategy: 'NoTranslation',
        utf8: true,
        targetInfo: false,
      },
    );
    expect(lastLine(out)).toBe('c{kept="z"} 1');
  });

  it('escaping rescues a double-underscore key', () => {
    const out = text(data([metric('c', SUM, [point(1, { __internal: 'x' })])]), {
      targetInfo: false,
    });
    expect(lastLine(out)).toBe('c_total{_internal="x"} 1');
  });

  it('unsupported data, untranslatable names and type clashes are skipped', () => {
    const hist: PointLike = {
      attributes: {},
      value: { buckets: { boundaries: [], counts: [1] }, sum: 1, count: 1 },
    };
    const out = text(
      data([
        metric('expo', EXPONENTIAL, [point(1)]),
        metric('...', GAUGE, [point(1)]),
        metric('dup', GAUGE, [point(1)]),
        metric('dup', SUM, [point(2)], { isMonotonic: false }),
        metric('dup', HISTOGRAM, [hist]),
      ]),
      { strategy: 'UnderscoreEscapingWithoutSuffixes', targetInfo: false },
    );
    expect(out).toBe('# TYPE dup gauge\ndup 1\ndup 2\n');
  });

  it('UTF-8 names render quoted when negotiated', () => {
    const d = data([metric('app.requests', SUM, [point(1, { 'http.route': 'a"b\\c' })])]);
    expect(text(d, { strategy: 'NoUTF8EscapingWithSuffixes', utf8: true, targetInfo: false })).toBe(
      '# TYPE "app.requests_total" counter\n{"app.requests_total","http.route"="a\\"b\\\\c"} 1\n',
    );
  });

  it('UTF-8 strategies fall back to escaping for other scrapers', () => {
    const d = data([metric('app.requests', SUM, [point(1, { 'http.route': '/a' })])]);
    const withSuffixes = text(d, { strategy: 'NoUTF8EscapingWithSuffixes', targetInfo: false });
    const without = text(d, { strategy: 'NoTranslation', targetInfo: false });
    expect(lastLine(withSuffixes)).toBe('app_requests_total{http_route="/a"} 1');
    expect(lastLine(without)).toBe('app_requests{http_route="/a"} 1');
  });

  it('empty data renders nothing', () => {
    expect(text(undefined)).toBe('');
    expect(text(data([]), { targetInfo: false })).toBe('');
    expect(render([family('x', 'gauge')])).toBe('# TYPE x gauge\n');
  });

  it('skips metrics whose instrument name is in skip', () => {
    const d = data([metric('drop.me', GAUGE, [point(1)]), metric('keep.me', GAUGE, [point(2)])]);
    expect(text(d, { targetInfo: false, skip: new Set(['drop.me']) })).toBe(
      '# TYPE keep_me gauge\nkeep_me 2\n',
    );
  });

  it('a metric named target_info keeps its family', () => {
    expect(text(data([metric('target_info', GAUGE, [point(5)])]))).toBe(
      '# TYPE target_info gauge\ntarget_info 5\n',
    );
  });

  it('quotes are escaped in names and label keys but not in help', () => {
    const fam = family('odd"name', 'gauge', 'say "hi"\\now');
    fam.samples.push(['', { 'k"ey': 'v', plain: 'w' }, 1]);
    expect(render([fam])).toBe(
      '# HELP "odd\\"name" say "hi"\\\\now\n# TYPE "odd\\"name" gauge\n{"odd\\"name","k\\"ey"="v",plain="w"} 1\n',
    );
  });

  it('newlines are escaped in label values', () => {
    const fam = family('n', 'gauge');
    fam.samples.push(['', { k: 'a\nb' }, 1]);
    expect(render([fam])).toBe('# TYPE n gauge\nn{k="a\\nb"} 1\n');
  });

  it('a UTF-8 label key in a legacy-named sample is quoted', () => {
    const fam = family('plain', 'gauge');
    fam.samples.push(['', { 'a.b': '1', c: '2' }, 3]);
    expect(render([fam])).toBe('# TYPE plain gauge\nplain{"a.b"="1",c="2"} 3\n');
  });

  it('a quoted name with no labels', () => {
    const fam = family('a.b', 'gauge');
    fam.samples.push(['', {}, 1]);
    expect(render([fam])).toBe('# TYPE "a.b" gauge\n{"a.b"} 1\n');
  });

  it('label values are stringified', () => {
    expect(translateLabels({ n: 1, b: true }, 'NoTranslation')).toEqual({ n: '1', b: 'true' });
  });

  it.each([
    [undefined, false],
    ['', false],
    ['text/plain;version=0.0.4', false],
    ['application/openmetrics-text;version=1.0.0;escaping=allow-utf-8', false],
    ['text/plain', false],
    [
      'application/openmetrics-text;q=0.6, text/plain; version=1.0.0; escaping=allow-utf-8;q=0.5',
      true,
    ],
    ['TEXT/PLAIN;ESCAPING=ALLOW-UTF-8', true],
    ['escaping=allow-utf-8;text/plain', false],
  ])('wantsUtf8(%s) is %s', (accept, want) => {
    expect(wantsUtf8(accept)).toBe(want);
  });

  it.each([
    [3, '3'],
    [-2, '-2'],
    [41.5, '41.5'],
    [1e20, '100000000000000000000'],
    [1e21, '1e+21'],
    [Infinity, '+Inf'],
    [-Infinity, '-Inf'],
    [NaN, 'NaN'],
  ])('formatValue(%s) is %s', (value, want) => {
    expect(formatValue(value)).toBe(want);
  });

  it('effectiveStrategy', () => {
    const o = (strategy: string, utf8 = false): RenderOptions => ({
      strategy,
      utf8,
      scopeLabels: false,
      targetInfo: true,
    });
    for (const s of ['UnderscoreEscapingWithSuffixes', 'UnderscoreEscapingWithoutSuffixes']) {
      expect(effectiveStrategy(o(s))).toBe(s);
      expect(effectiveStrategy(o(s, true))).toBe(s);
    }
    expect(effectiveStrategy(o('NoTranslation', true))).toBe('NoTranslation');
    expect(effectiveStrategy(o('NoUTF8EscapingWithSuffixes'))).toBe(
      'UnderscoreEscapingWithSuffixes',
    );
    expect(effectiveStrategy(o('NoTranslation'))).toBe('UnderscoreEscapingWithoutSuffixes');
  });

  it('content types', () => {
    expect(CONTENT_TYPE_TEXT).toBe(
      'text/plain; version=0.0.4; charset=utf-8; escaping=underscores',
    );
    expect(CONTENT_TYPE_UTF8).toBe(
      'text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8',
    );
  });
});

class TestReader extends MetricReader {
  protected async onForceFlush(): Promise<void> {}
  protected async onShutdown(): Promise<void> {}
}

describe('prom-render against the real SDK', () => {
  it('renders counters, histograms and gauges a MeterProvider collected', async () => {
    const reader = new TestReader();
    const provider = new MeterProvider({ readers: [reader] });
    const meter = provider.getMeter('t');
    meter.createCounter('real.requests').add(2, { route: '/a' });
    meter.createHistogram('real.latency', { unit: 'ms' }).record(7);
    meter.createGauge('real.cpu', { unit: '1' }).record(0.25);
    meter.createUpDownCounter('real.queue').add(-4);
    const { resourceMetrics } = await reader.collect();
    const out = text(resourceMetrics as unknown as ResourceMetricsLike, { targetInfo: false });
    expect(out).toContain('real_requests_total{route="/a"} 2\n');
    expect(out).toContain('real_latency_milliseconds_count 1\n');
    expect(out).toContain('real_latency_milliseconds_bucket{le="+Inf"} 1\n');
    expect(out).toContain('real_cpu_ratio 0.25\n');
    expect(out).toContain('# TYPE real_queue gauge\nreal_queue -4\n');
    await provider.shutdown();
  });
});
