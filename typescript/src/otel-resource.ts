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
 * Parity note: this honors the OTel-standard `OTEL_RESOURCE_ATTRIBUTES` and
 * `OTEL_SERVICE_NAME` env vars via the SDK's bundled `envDetector`, matching
 * Go (_buildResource merges `WithFromEnv`), Python (`Resource.create` runs
 * `OTELResourceDetector`), and Rust (`Resource::builder` runs `EnvResourceDetector`).
 * Callers can thus attach host.name, service.instance.id, k8s.* etc. without a
 * custom provider. Env attributes win on key conflict — `Resource.merge(other)`
 * gives the argument precedence — matching Go's `Merge(base, envRes)` semantics.
 */

import type { TelemetryConfig } from './config';

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

/**
 * Build the OTel `Resource` for a provider: the config-derived service identity
 * merged with any env-detected attributes, with env winning on conflict.
 */
export function buildOtelResource(res: OtelResourcesModule, cfg: TelemetryConfig): OtelResource {
  const configResource = res.resourceFromAttributes({
    'service.name': cfg.serviceName,
    'deployment.environment': cfg.environment,
    'service.version': cfg.version,
  });
  const envResource = res.detectResources({ detectors: [res.envDetector] });
  // Argument wins on conflict, so env-provided keys override config identity.
  return configResource.merge(envResource);
}
