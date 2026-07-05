// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Regression + mutation-kill tests for buildOtelResource() and its helpers.
 *
 * Guards the cross-language precedence contract:
 *   framework default  <  OTEL_* env  <  explicit config
 * with explicit-vs-default decided by comparing to DEFAULTS.
 *
 * Uses the real @opentelemetry/resources SDK so merge precedence and env
 * detection are exercised end-to-end, not mocked.
 */

import { afterEach, describe, expect, it } from 'vitest';
import * as resources from '@opentelemetry/resources';
import {
  buildOtelResource,
  explicitResourceAttrs,
  frameworkFloorAttrs,
  type OtelResourcesModule,
} from '../src/otel-resource';
import { DEFAULTS, type TelemetryConfig } from '../src/config';

const res = resources as unknown as OtelResourcesModule;

const RESOURCE_ATTRS_ENV = 'OTEL_RESOURCE_ATTRIBUTES';
const SERVICE_NAME_ENV = 'OTEL_SERVICE_NAME';

function config(overrides: Partial<TelemetryConfig> = {}): TelemetryConfig {
  return { ...DEFAULTS, ...overrides };
}

async function attributesOf(resource: unknown): Promise<Record<string, unknown>> {
  const r = resource as {
    waitForAsyncAttributes?: () => Promise<void>;
    attributes: Record<string, unknown>;
  };
  await r.waitForAsyncAttributes?.();
  return r.attributes;
}

afterEach(() => {
  delete process.env[RESOURCE_ATTRS_ENV];
  delete process.env[SERVICE_NAME_ENV];
});

describe('frameworkFloorAttrs', () => {
  it('returns the framework defaults for all three identity keys', () => {
    expect(frameworkFloorAttrs()).toEqual({
      'service.name': DEFAULTS.serviceName,
      'deployment.environment': DEFAULTS.environment,
      'service.version': DEFAULTS.version,
    });
  });
});

describe('explicitResourceAttrs', () => {
  it('omits keys left at the framework default', () => {
    expect(explicitResourceAttrs(config())).toEqual({});
  });

  it('includes only the keys whose config value differs from the default', () => {
    expect(explicitResourceAttrs(config({ serviceName: 'checkout' }))).toEqual({
      'service.name': 'checkout',
    });
    expect(explicitResourceAttrs(config({ environment: 'prod' }))).toEqual({
      'deployment.environment': 'prod',
    });
    expect(explicitResourceAttrs(config({ version: '1.2.3' }))).toEqual({
      'service.version': '1.2.3',
    });
  });

  it('includes every explicitly-set key together', () => {
    expect(
      explicitResourceAttrs(config({ serviceName: 'checkout', environment: 'prod', version: '1.2.3' })),
    ).toEqual({
      'service.name': 'checkout',
      'deployment.environment': 'prod',
      'service.version': '1.2.3',
    });
  });
});

describe('buildOtelResource precedence', () => {
  it('falls back to the framework floor when nothing is set', async () => {
    const attrs = await attributesOf(buildOtelResource(res, config()));
    expect(attrs['service.name']).toBe(DEFAULTS.serviceName);
    expect(attrs['deployment.environment']).toBe(DEFAULTS.environment);
    expect(attrs['service.version']).toBe(DEFAULTS.version);
  });

  it('lets OTEL_SERVICE_NAME override the floor when config is default (env > floor)', async () => {
    process.env[SERVICE_NAME_ENV] = 'env-service';
    const attrs = await attributesOf(buildOtelResource(res, config()));
    // Env fills an unset (default) service name.
    expect(attrs['service.name']).toBe('env-service');
  });

  it('lets explicit config override OTEL_SERVICE_NAME (explicit > env)', async () => {
    process.env[SERVICE_NAME_ENV] = 'env-service';
    const attrs = await attributesOf(buildOtelResource(res, config({ serviceName: 'app-service' })));
    // Explicit identity is never hijacked by ambient env.
    expect(attrs['service.name']).toBe('app-service');
  });

  it('merges additive OTEL_RESOURCE_ATTRIBUTES keys and keeps floor identity', async () => {
    process.env[RESOURCE_ATTRS_ENV] = 'host.name=web-1';
    const attrs = await attributesOf(buildOtelResource(res, config({ version: '9.9.9' })));
    expect(attrs['host.name']).toBe('web-1'); // additive env key
    expect(attrs['service.version']).toBe('9.9.9'); // explicit
    expect(attrs['service.name']).toBe(DEFAULTS.serviceName); // floor
  });
});
