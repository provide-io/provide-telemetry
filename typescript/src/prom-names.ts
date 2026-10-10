// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Prometheus metric and label name translation.
 *
 * A port of github.com/prometheus/otlptranslator v1.0.0 (MetricNamer and
 * LabelNamer, without namespaces), the reference named by
 * prometheus_metrics.translation in spec/telemetry-api.yaml, by way of the
 * Python port in provide.telemetry.metrics._prom_names. The cases in
 * spec/prometheus_fixtures.yaml were generated from that library, so this
 * module must reproduce it exactly rather than approximate it.
 */

export const KIND_MONOTONIC_COUNTER = 'monotonic_counter';
export const KIND_NON_MONOTONIC_COUNTER = 'non_monotonic_counter';
export const KIND_GAUGE = 'gauge';
export const KIND_HISTOGRAM = 'histogram';

/** Raised when a name or attribute cannot be translated, as the reference rejects it. */
export class PromNameError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PromNameError';
  }
}

const UNIT_MAP: Readonly<Record<string, string>> = {
  d: 'days',
  h: 'hours',
  min: 'minutes',
  s: 'seconds',
  ms: 'milliseconds',
  us: 'microseconds',
  ns: 'nanoseconds',
  By: 'bytes',
  KiBy: 'kibibytes',
  MiBy: 'mebibytes',
  GiBy: 'gibibytes',
  TiBy: 'tibibytes',
  KBy: 'kilobytes',
  MBy: 'megabytes',
  GBy: 'gigabytes',
  TBy: 'terabytes',
  m: 'meters',
  V: 'volts',
  A: 'amperes',
  J: 'joules',
  W: 'watts',
  g: 'grams',
  Cel: 'celsius',
  Hz: 'hertz',
  '1': '',
  '%': 'percent',
};
const PER_UNIT_MAP: Readonly<Record<string, string>> = {
  s: 'second',
  m: 'minute',
  h: 'hour',
  d: 'day',
  w: 'week',
  mo: 'month',
  y: 'year',
};

/** Whether the strategy escapes names to the legacy character set. */
export function escapes(strategy: string): boolean {
  return strategy.startsWith('UnderscoreEscaping');
}

/** Whether the strategy appends unit, _total and _ratio suffixes. */
export function addsSuffixes(strategy: string): boolean {
  return strategy.endsWith('WithSuffixes');
}

// Runs of characters outside the legacy sets, "_" included, so replacing each
// run with one "_" also collapses repeated underscores as the reference does.
const METRIC_SEPARATORS = /[^a-zA-Z0-9:]+/;
const METRIC_SEPARATORS_KEEPING_UNDERSCORE = /[^a-zA-Z0-9:_]+/;
const INVALID_UNIT_RUNS = /[^a-zA-Z0-9:]+/g;
const INVALID_LABEL_RUNS = /[^a-zA-Z0-9]+/g;

/** Own-property lookup, so a unit such as "constructor" is not read off Object.prototype. */
function lookup(map: Readonly<Record<string, string>>, key: string): string {
  return Object.prototype.hasOwnProperty.call(map, key) ? (map[key] as string) : key;
}

/** Split name on separators, dropping empty fields (Go's strings.FieldsFunc). */
function tokens(separators: RegExp, name: string): string[] {
  return name.split(separators).filter((t) => t !== '');
}

function stripUnderscores(text: string): string {
  return text.replace(/^_+/, '').replace(/_+$/, '');
}

function removeSuffix(text: string, suffix: string): string {
  return text.endsWith(suffix) ? text.slice(0, text.length - suffix.length) : text;
}

function cleanUpUnit(unit: string): string {
  const cleaned = unit.replace(INVALID_UNIT_RUNS, '_');
  return cleaned.startsWith('_') ? cleaned.slice(1) : cleaned;
}

/** A unit as written, or "" when blank or an {annotation}. */
function unitSuffix(unit: string): string {
  const trimmed = unit.trim();
  if (trimmed.includes('{') || trimmed.includes('}')) return '';
  return trimmed;
}

/** The main and per-unit suffixes for unit, e.g. ['bytes', 'per_second'] for By/s. */
function unitSuffixes(unit: string): [string, string] {
  const slash = unit.indexOf('/');
  const main = unitSuffix(slash < 0 ? unit : unit.slice(0, slash));
  const per = unitSuffix(slash < 0 ? '' : unit.slice(slash + 1));
  return [lookup(UNIT_MAP, main), per ? `per_${lookup(PER_UNIT_MAP, per)}` : ''];
}

function addUnitTokens(nameTokens: string[], main: string, per: string): string[] {
  const mainSuffix = nameTokens.includes(main) ? '' : main;
  // The reference also drops a per suffix already among the tokens, but that
  // cannot happen: tokens never contain "_" and a per suffix always does.
  const perSuffix = per === 'per_' ? '' : removeSuffix(per, '_');
  const trimmedMain = perSuffix ? removeSuffix(mainSuffix, '_') : mainSuffix;
  return [...nameTokens, ...[trimmedMain, perSuffix].filter((t) => t !== '')];
}

function prefixLeadingDigit(name: string): string {
  return /^[0-9]/.test(name) ? `_${name}` : name;
}

/** Full escaping normalization with suffixes (otlptranslator normalizeName). */
function normalize(name: string, unit: string, kind: string): string {
  const [main, per] = unitSuffixes(unit);
  let result = addUnitTokens(tokens(METRIC_SEPARATORS, name), cleanUpUnit(main), cleanUpUnit(per));
  if (kind === KIND_MONOTONIC_COUNTER) {
    result = [...result.filter((t) => t !== 'total'), 'total'];
  }
  if (unit === '1' && kind === KIND_GAUGE) {
    result = [...result.filter((t) => t !== 'ratio'), 'ratio'];
  }
  return prefixLeadingDigit(result.join('_'));
}

/**
 * Trim suffix plus one delimiter character, when something is left before it.
 *
 * Counted in code points, as the Python port counts them, so a delimiter
 * outside the Basic Multilingual Plane is removed whole.
 */
function trimSuffix(name: string, suffix: string): string {
  const chars = Array.from(name);
  const keep = chars.length - suffix.length - 1;
  return name.endsWith(suffix) && keep > 0 ? chars.slice(0, keep).join('') : name;
}

/**
 * UTF-8 naming with suffixes (otlptranslator buildMetricName).
 *
 * Outer suffixes are trimmed first and re-appended last, so the result reads
 * name, main unit, per unit, then _total or _ratio.
 */
function utf8WithSuffixes(name: string, unit: string, kind: string): string {
  let base = name;
  let outer = '';
  if (unit === '1' && kind === KIND_GAUGE) {
    base = trimSuffix(base, 'ratio');
    outer = '_ratio';
  }
  if (kind === KIND_MONOTONIC_COUNTER) {
    base = trimSuffix(base, 'total');
    outer = '_total';
  }
  const [main, per] = unitSuffixes(unit);
  let perSuffix = '';
  if (per) {
    base = trimSuffix(base, per);
    perSuffix = `_${per}`;
  }
  if (main && !base.endsWith(main)) base = `${base}_${main}`;
  return base + perSuffix + outer;
}

/**
 * Translate an OTel instrument name into a Prometheus metric name.
 *
 * Throws PromNameError when translation leaves no usable name, as the reference does.
 */
export function metricName(name: string, unit: string, kind: string, strategy: string): string {
  if (!escapes(strategy)) {
    return addsSuffixes(strategy) ? utf8WithSuffixes(name, unit, kind) : name;
  }
  const result = addsSuffixes(strategy)
    ? normalize(name, unit, kind)
    : prefixLeadingDigit(tokens(METRIC_SEPARATORS_KEEPING_UNDERSCORE, name).join('_'));
  if (!result || (result !== name && !stripUnderscores(result))) {
    throw new PromNameError(`metric name ${JSON.stringify(name)} translates to nothing usable`);
  }
  return result;
}

/**
 * Translate an attribute key into a Prometheus label name.
 *
 * Throws PromNameError for an empty key or one that is only underscores.
 */
export function labelName(attribute: string, strategy: string): string {
  const rejected = new PromNameError(
    `attribute ${JSON.stringify(attribute)} cannot be a label name`,
  );
  if (!stripUnderscores(attribute)) throw rejected;
  if (!escapes(strategy)) return attribute;
  // A key that starts and ends with "__" keeps both; shorter such keys are all
  // underscores and were rejected above.
  const reserved = attribute.startsWith('__') && attribute.endsWith('__');
  const body = reserved ? attribute.slice(2, -2) : attribute;
  let sanitized = body.replace(INVALID_LABEL_RUNS, '_');
  if (reserved) sanitized = `__${sanitized}__`;
  if (/^[0-9]/.test(sanitized)) sanitized = `key_${sanitized}`;
  if (!stripUnderscores(sanitized)) throw rejected;
  return sanitized;
}
