// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * The shared Prometheus cases (spec/prometheus_fixtures.yaml) and the
 * prometheus_metrics section of spec/telemetry-api.yaml, read from the YAML
 * rather than copied, so a regenerated fixture reaches these tests unchanged.
 */

import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
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
