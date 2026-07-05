// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OTel `Resource` construction shared by the trace, metric, and log providers.
 *
 * The three provider builders in otel.ts / otel-logs.ts each dynamically import
 * `@opentelemetry/resources` (an optional peer dep) and hand the module here.
 * Keeping the logic in this statically-imported module means it is unit-tested
 * and mutation-tested (otel.ts / otel-logs.ts are Stryker-exempt because their
 * `await import('pkg' as string)` pattern defeats V8 per-test coverage).
 *
 * Precedence (cross-language contract, see spec/behavioral_fixtures.yaml):
 *
 *   framework default  <  OTEL_* env  <  explicit config
 *
 * A config identity key (service.name / deployment.environment / service.version)
 * only overrides the env layer when it differs from the framework default — so an
 * explicitly named service is never hijacked by an ambient OTEL_RESOURCE_ATTRIBUTES,
 * while OTEL_SERVICE_NAME still fills an unset service name. Additive env keys
 * (host.name, service.instance.id, k8s.*) always merge through untouched.
 *
 * Matches Go (_buildResource), Python (build_resource), and Rust (build_resource).
 */

import type { TelemetryConfig } from './config';
import { DEFAULTS } from './config';

/** Minimal structural view of the parts of `@opentelemetry/resources` we use. */
export interface OtelResourcesModule {
  resourceFromAttributes: (attributes: Record<string, string>) => OtelResource;
  detectResources: (config: { detectors: unknown[] }) => OtelResource;
  envDetector: unknown;
}

/** Minimal structural view of an OTel `Resource`. */
export interface OtelResource {
  merge: (other: OtelResource) => OtelResource;
}

/** The framework-default identity floor — the value each key falls back to. */
export function frameworkFloorAttrs(): Record<string, string> {
  return {
    'service.name': DEFAULTS.serviceName,
    'deployment.environment': DEFAULTS.environment,
    'service.version': DEFAULTS.version,
  };
}

/**
 * The identity attributes the caller explicitly set — i.e. those whose config
 * value differs from the framework default. These form the top precedence layer
 * so they win over env; keys left at the default are omitted so env can fill them.
 */
export function explicitResourceAttrs(cfg: TelemetryConfig): Record<string, string> {
  const attrs: Record<string, string> = {};
  if (cfg.serviceName !== DEFAULTS.serviceName) {
    attrs['service.name'] = cfg.serviceName;
  }
  if (cfg.environment !== DEFAULTS.environment) {
    attrs['deployment.environment'] = cfg.environment;
  }
  if (cfg.version !== DEFAULTS.version) {
    attrs['service.version'] = cfg.version;
  }
  return attrs;
}

/**
 * Build the OTel `Resource` for a provider by layering floor ⊕ env ⊕ explicit.
 * `Resource.merge(other)` gives the argument precedence, so each `.merge` call
 * lets the later (higher-priority) layer override the earlier one.
 */
export function buildOtelResource(res: OtelResourcesModule, cfg: TelemetryConfig): OtelResource {
  const floor = res.resourceFromAttributes(frameworkFloorAttrs());
  const env = res.detectResources({ detectors: [res.envDetector] });
  const explicit = res.resourceFromAttributes(explicitResourceAttrs(cfg));
  return floor.merge(env).merge(explicit);
}
