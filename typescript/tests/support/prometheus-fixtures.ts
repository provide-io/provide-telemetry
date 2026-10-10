// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * The shared Prometheus cases (spec/prometheus_fixtures.yaml) and the
 * prometheus_metrics section of spec/telemetry-api.yaml, read from the YAML
 * rather than copied, so a regenerated fixture reaches these tests unchanged.
 */

import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import type { HealthSnapshot } from '../../src/health.js';
import { specFixturePath } from './spec-fixtures.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
export const promFixtures: Record<string, any> = parse(
  readFileSync(specFixturePath('prometheus_fixtures.yaml'), 'utf8'),
) as Record<string, any>;

export const promSpec: Record<string, any> = (
  parse(readFileSync(specFixturePath('telemetry-api.yaml'), 'utf8')) as Record<string, any>
)['prometheus_metrics'] as Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

/** Run fn with exactly these PROVIDE_* / OTEL_* variables set, restoring the rest afterwards. */
export function withEnv<T>(vars: Record<string, string>, fn: () => T): T {
  const saved = { ...process.env };
  for (const key of Object.keys(process.env)) {
    if (key.startsWith('PROVIDE_') || key.startsWith('OTEL_')) delete process.env[key];
  }
  Object.assign(process.env, vars);
  try {
    return fn();
  } finally {
    for (const key of Object.keys(process.env)) delete process.env[key];
    Object.assign(process.env, saved);
  }
}

/** Turn a fixture snapshot (snake_case, per spec) into this SDK's HealthSnapshot. */
export function snapshotFrom(values: Record<string, unknown>): HealthSnapshot {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    const match = /^(emitted|dropped)_(logs|traces|metrics)$/.exec(key);
    if (match) {
      out[
        `${match[2]}${(match[1] as string).charAt(0).toUpperCase()}${(match[1] as string).slice(1)}`
      ] = value;
      continue;
    }
    out[key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())] = value;
  }
  return out as unknown as HealthSnapshot;
}
