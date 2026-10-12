// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Render collected OTel metrics in the Prometheus text exposition format.
 *
 * Names go through the reference translation in prom-names. A scraper that
 * negotiates escaping=allow-utf-8 (Prometheus 3 does) gets the UTF-8 names of
 * the NoUTF8/NoTranslation strategies in the quoted text-format syntax; any
 * other scraper gets the UnderscoreEscaping output with the same suffix choice,
 * as prometheus_metrics.translation.rules requires. Mirrors Python
 * provide.telemetry.metrics._prom_render.
 *
 * The SDK's ResourceMetrics is typed structurally here, so neither this module
 * nor its declarations import @opentelemetry/sdk-metrics, an optional peer.
 */

import {
  addsSuffixes,
  escapes,
  KIND_GAUGE,
  KIND_HISTOGRAM,
  KIND_MONOTONIC_COUNTER,
  KIND_NON_MONOTONIC_COUNTER,
  labelName,
  metricName,
} from './prom-names.js';

export const CONTENT_TYPE_TEXT = 'text/plain; version=0.0.4; charset=utf-8; escaping=underscores';
export const CONTENT_TYPE_UTF8 = 'text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8';

export const TARGET_INFO = 'target_info';
export const TARGET_INFO_HELP = 'Target metadata';

// sdk-metrics DataPointType values.
export const POINT_HISTOGRAM = 0;
export const POINT_GAUGE = 2;
export const POINT_SUM = 3;

const LEGACY_NAME = /^[a-zA-Z_:][a-zA-Z0-9_:]*$/;
const LEGACY_LABEL = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

export interface RenderOptions {
  strategy: string;
  scopeLabels: boolean;
  targetInfo: boolean;
  /** The scraper negotiated escaping=allow-utf-8. */
  utf8: boolean;
  /** OTel instrument names left out of the output. */
  skip?: ReadonlySet<string>;
}

export type Labels = Record<string, string>;
/** (suffix, labels, value) */
export type Sample = [string, Labels, number];

/** One metric family: a translated name, a Prometheus type and its samples. */
export interface Family {
  name: string;
  kind: 'counter' | 'gauge' | 'histogram';
  help: string;
  samples: Sample[];
}

export function family(name: string, kind: Family['kind'], help = ''): Family {
  return { name, kind, help, samples: [] };
}

type AttributeMap = Record<string, unknown>;

export interface HistogramValue {
  buckets: { boundaries: number[]; counts: number[] };
  sum?: number;
  count: number;
}

export interface PointLike {
  attributes: AttributeMap;
  value: number | HistogramValue;
}

export interface MetricLike {
  descriptor: { name: string; description: string; unit: string };
  dataPointType: number;
  isMonotonic?: boolean;
  dataPoints: PointLike[];
}

export interface ResourceMetricsLike {
  resource: { attributes: AttributeMap };
  scopeMetrics: { scope: { name: string; version?: string }; metrics: MetricLike[] }[];
}

/** Whether an Accept header asks for the text format with UTF-8 names. */
export function wantsUtf8(accept: string | undefined): boolean {
  if (!accept) return false;
  return accept.split(',').some((mediaRange) => {
    const [type, ...params] = mediaRange.split(';').map((p) => p.trim().toLowerCase());
    return type === 'text/plain' && params.includes('escaping=allow-utf-8');
  });
}

/** The strategy to translate with for this scrape. */
export function effectiveStrategy(opts: RenderOptions): string {
  if (escapes(opts.strategy) || opts.utf8) return opts.strategy;
  return addsSuffixes(opts.strategy)
    ? 'UnderscoreEscapingWithSuffixes'
    : 'UnderscoreEscapingWithoutSuffixes';
}

/** [translation kind, Prometheus type] for a metric, or undefined if unsupported. */
function kindOf(metric: MetricLike): [string, Family['kind']] | undefined {
  if (metric.dataPointType === POINT_SUM) {
    return metric.isMonotonic
      ? [KIND_MONOTONIC_COUNTER, 'counter']
      : [KIND_NON_MONOTONIC_COUNTER, 'gauge'];
  }
  if (metric.dataPointType === POINT_GAUGE) return [KIND_GAUGE, 'gauge'];
  if (metric.dataPointType === POINT_HISTOGRAM) return [KIND_HISTOGRAM, 'histogram'];
  return undefined; // exponential histograms are not exported over this path
}

/**
 * Translate attribute keys to label names, dropping keys that cannot be labels.
 *
 * A key the reference rejects, or translates to a name starting with "__"
 * (reserved by Prometheus), is dropped; the sample is kept.
 */
export function translateLabels(attributes: AttributeMap, strategy: string): Labels {
  const labels: Labels = {};
  for (const [key, value] of Object.entries(attributes)) {
    let label: string;
    try {
      label = labelName(key, strategy);
    } catch {
      continue;
    }
    if (!label.startsWith('__')) labels[label] = String(value);
  }
  return labels;
}

function scopeLabelsOf(scope: { name: string; version?: string }): Labels {
  const labels: Labels = { otel_scope_name: scope.name };
  if (scope.version) labels['otel_scope_version'] = scope.version;
  return labels;
}

/** Convert collected ResourceMetrics into families keyed by translated name, sorted by name. */
export function familiesFrom(
  collected: ResourceMetricsLike | undefined,
  opts: RenderOptions,
): Family[] {
  const strategy = effectiveStrategy(opts);
  const families = new Map<string, Family>();
  if (collected !== undefined) {
    const info = family(TARGET_INFO, 'gauge', TARGET_INFO_HELP);
    const resourceLabels = translateLabels(collected.resource.attributes, strategy);
    if (opts.targetInfo && Object.keys(resourceLabels).length > 0) {
      info.samples.push(['', resourceLabels, 1]);
    }
    for (const scopeMetrics of collected.scopeMetrics) {
      const scope = opts.scopeLabels ? scopeLabelsOf(scopeMetrics.scope) : {};
      for (const metric of scopeMetrics.metrics) {
        if (!opts.skip?.has(metric.descriptor.name)) addMetric(families, metric, scope, strategy);
      }
    }
    if (info.samples.length > 0 && !families.has(TARGET_INFO)) families.set(TARGET_INFO, info);
  }
  return [...families.keys()].sort().map((name) => families.get(name) as Family);
}

function addMetric(
  families: Map<string, Family>,
  metric: MetricLike,
  scope: Labels,
  strategy: string,
): void {
  const kinds = kindOf(metric);
  if (kinds === undefined) return;
  const [kind, promType] = kinds;
  let name: string;
  try {
    name = metricName(metric.descriptor.name, metric.descriptor.unit, kind, strategy);
  } catch {
    return;
  }
  let target = families.get(name);
  if (target === undefined) {
    target = family(name, promType, metric.descriptor.description);
    families.set(name, target);
  }
  if (target.kind !== promType) return; // another instrument under the same name but another type
  for (const point of metric.dataPoints) {
    const labels = { ...translateLabels(point.attributes, strategy), ...scope };
    if (promType === 'histogram') {
      target.samples.push(...histogramSamples(point.value as HistogramValue, labels));
    } else {
      target.samples.push(['', labels, point.value as number]);
    }
  }
}

function histogramSamples(value: HistogramValue, labels: Labels): Sample[] {
  const samples: Sample[] = [];
  let running = 0;
  value.buckets.boundaries.forEach((bound, index) => {
    running += value.buckets.counts[index] as number;
    samples.push(['_bucket', { ...labels, le: formatValue(bound) }, running]);
  });
  samples.push(['_bucket', { ...labels, le: '+Inf' }, value.count]);
  samples.push(['_sum', labels, value.sum ?? 0]);
  samples.push(['_count', labels, value.count]);
  return samples;
}

/** Format a sample value: the shortest round-trip form, ±Inf as Prometheus spells it (NaN already is). */
export function formatValue(value: number): string {
  if (value === Infinity) return '+Inf';
  if (value === -Infinity) return '-Inf';
  return String(value);
}

function escapeHelp(text: string): string {
  return text.replace(/[\\\n]/g, escapeChar);
}

/** Escape a label value or a quoted name: backslash, newline and double quote. */
function escapeQuoted(text: string): string {
  return text.replace(/[\\\n"]/g, escapeChar);
}

/** One pass per string, so no escape can be escaped again. */
function escapeChar(char: string): string {
  return char === '\n' ? '\\n' : `\\${char}`;
}

function labelPairs(labels: Labels): string[] {
  return Object.entries(labels).map(([key, value]) => {
    const name = LEGACY_LABEL.test(key) ? key : `"${escapeQuoted(key)}"`;
    return `${name}="${escapeQuoted(value)}"`;
  });
}

function sampleLine(name: string, labels: Labels, value: number): string {
  const pairs = labelPairs(labels);
  if (LEGACY_NAME.test(name)) {
    return pairs.length > 0
      ? `${name}{${pairs.join(',')}} ${formatValue(value)}`
      : `${name} ${formatValue(value)}`;
  }
  return `{"${escapeQuoted(name)}"${pairs.map((p) => `,${p}`).join('')}} ${formatValue(value)}`;
}

/** Render families as text exposition, HELP and TYPE first in each. */
export function render(families: Family[]): string {
  const lines: string[] = [];
  for (const fam of families) {
    const header = LEGACY_NAME.test(fam.name) ? fam.name : `"${escapeQuoted(fam.name)}"`;
    if (fam.help) lines.push(`# HELP ${header} ${escapeHelp(fam.help)}`);
    lines.push(`# TYPE ${header} ${fam.kind}`);
    for (const [suffix, labels, value] of fam.samples) {
      lines.push(sampleLine(fam.name + suffix, labels, value));
    }
  }
  return lines.length > 0 ? `${lines.join('\n')}\n` : '';
}
