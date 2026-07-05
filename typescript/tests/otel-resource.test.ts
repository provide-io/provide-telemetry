// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Regression + mutation-kill tests for buildOtelResource().
 *
 * Guards the cross-language parity contract: the trace/metric/log providers
 * must honor OTEL_RESOURCE_ATTRIBUTES / OTEL_SERVICE_NAME (matching Go, Python,
 * Rust) with env attributes winning on key conflict.
 *
 * Uses the real @opentelemetry/resources SDK so the merge precedence and env
 * detection are exercised end-to-end, not mocked.
 */

import { afterEach, describe, expect, it } from 'vitest';
import * as resources from '@opentelemetry/resources';
import { buildOtelResource, type OtelResourcesModule } from '../src/otel-resource';
import type { TelemetryConfig } from '../src/config';

const res = resources as unknown as OtelResourcesModule;

const RESOURCE_ATTRS_ENV = 'OTEL_RESOURCE_ATTRIBUTES';
const SERVICE_NAME_ENV = 'OTEL_SERVICE_NAME';

function makeConfig(): TelemetryConfig {
  return {
    serviceName: 'cfg-service',
    environment: 'cfg-env',
    version: '9.9.9',
  } as TelemetryConfig;
}

// Resolve merged attributes, awaiting the env detector's (possibly async) attrs.
async function attributesOf(resource: unknown): Promise<Record<string, unknown>> {
  const r = resource as { waitForAsyncAttributes?: () => Promise<void>; attributes: Record<string, unknown> };
  await r.waitForAsyncAttributes?.();
  return r.attributes;
}

afterEach(() => {
  delete process.env[RESOURCE_ATTRS_ENV];
  delete process.env[SERVICE_NAME_ENV];
});

describe('buildOtelResource', () => {
  it('carries service identity from config when no env vars are set', async () => {
    const attrs = await attributesOf(buildOtelResource(res, makeConfig()));
    // Kills mutants that drop or swap any of the three config attribute mappings.
    expect(attrs['service.name']).toBe('cfg-service');
    expect(attrs['deployment.environment']).toBe('cfg-env');
    expect(attrs['service.version']).toBe('9.9.9');
  });

  it('honors OTEL_SERVICE_NAME, with env winning over config service.name', async () => {
    process.env[SERVICE_NAME_ENV] = 'env-service';
    const attrs = await attributesOf(buildOtelResource(res, makeConfig()));
    // Kills the `detectors: [envDetector]` → `[]` mutant and the merge-order
    // mutant: if env were ignored or lost the merge, this would be 'cfg-service'.
    expect(attrs['service.name']).toBe('env-service');
  });

  it('honors OTEL_RESOURCE_ATTRIBUTES for additive keys and env-wins overrides', async () => {
    process.env[RESOURCE_ATTRS_ENV] = 'host.name=web-1,deployment.environment=prod';
    const attrs = await attributesOf(buildOtelResource(res, makeConfig()));
    // Additive key the config never sets — proves the env detector ran.
    expect(attrs['host.name']).toBe('web-1');
    // Overlapping key — proves env wins on conflict (merge argument precedence).
    expect(attrs['deployment.environment']).toBe('prod');
    // Non-overlapping config keys survive.
    expect(attrs['service.name']).toBe('cfg-service');
    expect(attrs['service.version']).toBe('9.9.9');
  });
});
