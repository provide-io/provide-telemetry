// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OTLP header parsing and secret redaction.
 *
 * Split out of config.ts, which is at the repo's 500-line ceiling. Everything
 * here is re-exported from config.ts, so consumers keep importing from there.
 */

import type { TelemetryConfig } from './config.js';

/**
 * Parse OTLP-style header string "key=value,key2=value2" into a Record.
 * Keys and values are URL-decoded. Malformed pairs (no '=') and empty keys are skipped.
 * Values may contain '=' characters (only the first '=' splits key from value).
 */
export function parseOtlpHeaders(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  // Stryker disable next-line ConditionalExpression: early return is an optimization — empty string splits to [""], idx<1 skips the only pair, returns {} identically
  if (!raw) return result;
  for (const pair of raw.split(',')) {
    const idx = pair.indexOf('=');
    if (idx < 1) continue; // no '=' or empty key
    const rawKey = pair.slice(0, idx).trim();
    const rawVal = pair.slice(idx + 1).trim();
    try {
      const key = decodeURIComponent(rawKey);
      // Stryker disable next-line ConditionalExpression: defensive guard — unreachable because idx<1 check and trim() already exclude empty keys
      /* v8 ignore next: defensive — idx<1 and trim() already exclude observable empty keys */
      if (!key) continue;
      const val = decodeURIComponent(rawVal);
      result[key] = val;
      // `continue` in a for..of catch is equivalent to an empty body — the
      // block ending naturally starts the next iteration either way.
      // Stryker disable BlockStatement
    } catch {
      continue;
    }
    // Stryker restore BlockStatement
  }
  return result;
}

/** Mask a single header value: show first 4 chars + **** if >= 8 chars, else ****. */
function maskHeaderValue(v: string): string {
  return v.length < 8 ? '****' : v.slice(0, 4) + '****';
}

/** Mask the password component of a URL's userinfo, if present. */
function maskEndpointUrl(raw: string): string {
  try {
    const u = new URL(raw);
    if (u.password) {
      u.password = '****';
      return u.toString();
    }
  } catch {
    /* not a valid URL — return as-is */
  }
  return raw;
}

/** Mask every value of a header record. */
function maskHeaders(headers: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(headers).map(([k, v]) => [k, maskHeaderValue(v)]));
}

const _HEADER_FIELDS = ['otlpLogsHeaders', 'otlpTracesHeaders', 'otlpMetricsHeaders'] as const;
const _ENDPOINT_FIELDS = ['otlpLogsEndpoint', 'otlpTracesEndpoint', 'otlpMetricsEndpoint'] as const;

/**
 * Return a copy of the config with OTLP secrets masked.
 * Safe to log or serialize — never leaks header values or endpoint credentials.
 *
 * The presence guards are load-bearing in both directions, so none of them is
 * suppressed: forcing one false leaves a secret unmasked, and forcing one true
 * writes an `undefined` key onto a config that did not carry the field at all
 * (asserted with `Object.hasOwn` in config.redact.test.ts).
 */
export function redactConfig(config: TelemetryConfig): Record<string, unknown> {
  const result: Record<string, unknown> = { ...config };
  // Stryker disable next-line EqualityOperator: length is never negative — `> 0` vs `>= 0` only differ at length 0, where maskHeaders({}) produces the same {} the spread already put there
  if (config.otlpHeaders && Object.keys(config.otlpHeaders).length > 0) {
    result.otlpHeaders = maskHeaders(config.otlpHeaders);
  }
  for (const field of _HEADER_FIELDS) {
    const hdrs = config[field];
    // Stryker disable next-line EqualityOperator: see above — length 0 masks to the same {}
    if (hdrs && Object.keys(hdrs).length > 0) {
      result[field] = maskHeaders(hdrs);
    }
  }
  if (config.otlpEndpoint) {
    result.otlpEndpoint = maskEndpointUrl(config.otlpEndpoint);
  }
  for (const field of _ENDPOINT_FIELDS) {
    const endpoint = config[field];
    if (endpoint) {
      result[field] = maskEndpointUrl(endpoint);
    }
  }
  return result;
}
