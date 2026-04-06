// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Runtime reconfiguration helpers.
 * Mirrors Python provide.telemetry.runtime.
 */

import {
  type RuntimeOverrides,
  type TelemetryConfig,
  configFromEnv,
  setupTelemetry,
} from './config';

/** Minimal interface for providers that can be flushed and shut down cleanly. */
export interface ShutdownableProvider {
  forceFlush?(): Promise<void>;
  shutdown?(): Promise<void>;
}

let _activeConfig: TelemetryConfig | null = null;
// Stryker disable next-line BooleanLiteral: initial false is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _providersRegistered = false;
// Stryker disable next-line ArrayDeclaration: initial [] is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _registeredProviders: ShutdownableProvider[] = [];

/** Store the live providers so shutdownTelemetry can flush and drain them. */
export function _storeRegisteredProviders(providers: ShutdownableProvider[]): void {
  _registeredProviders = providers;
}

/** Return the currently registered providers (snapshot). */
export function _getRegisteredProviders(): ShutdownableProvider[] {
  return [..._registeredProviders];
}

/** Called by registerOtelProviders once providers are live. */
export function _markProvidersRegistered(): void {
  _providersRegistered = true;
}

/** Return true if OTEL providers have been registered. */
export function _areProvidersRegistered(): boolean {
  return _providersRegistered;
}

function deepFreeze<T extends object>(obj: T): Readonly<T> {
  for (const val of Object.values(obj)) {
    if (typeof val === 'object' && val !== null && !Object.isFrozen(val)) {
      deepFreeze(val as object);
    }
  }
  return Object.freeze(obj);
}

/** Return the active runtime config (or env-derived defaults if none set). */
export function getRuntimeConfig(): Readonly<TelemetryConfig> {
  const cfg = _activeConfig ?? configFromEnv();
  return deepFreeze({ ...cfg });
}

/** Merge hot-reloadable overrides into the active config and re-apply policies. */
export function updateRuntimeConfig(overrides: RuntimeOverrides): void {
  const base = _activeConfig ?? configFromEnv();
  const merged: TelemetryConfig = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined) {
      (merged as unknown as Record<string, unknown>)[key] = value;
    }
  }
  _activeConfig = merged;
  setupTelemetry(_activeConfig);
}

const _COLD_FIELDS: (keyof TelemetryConfig)[] = [
  'serviceName',
  'environment',
  'version',
  'otelEnabled',
  'otlpEndpoint',
  'otlpHeaders',
];

/** Reload config from env vars and apply only hot-reloadable fields. */
export function reloadRuntimeFromEnv(): void {
  const fresh = configFromEnv();
  const current = _activeConfig;
  if (current) {
    const drifted = _COLD_FIELDS.filter(
      (k) => JSON.stringify(current[k]) !== JSON.stringify(fresh[k]),
    );
    if (drifted.length > 0) {
      console.warn(
        '[provide-telemetry] runtime.cold_field_drift:',
        drifted.join(', '),
        '— restart required to apply',
      );
    }
  }
  // Apply only hot fields via overrides
  const overrides: RuntimeOverrides = {
    samplingLogsRate: fresh.samplingLogsRate,
    samplingTracesRate: fresh.samplingTracesRate,
    samplingMetricsRate: fresh.samplingMetricsRate,
    backpressureLogsMaxsize: fresh.backpressureLogsMaxsize,
    backpressureTracesMaxsize: fresh.backpressureTracesMaxsize,
    backpressureMetricsMaxsize: fresh.backpressureMetricsMaxsize,
    exporterLogsRetries: fresh.exporterLogsRetries,
    exporterLogsBackoffMs: fresh.exporterLogsBackoffMs,
    exporterLogsTimeoutMs: fresh.exporterLogsTimeoutMs,
    exporterLogsFailOpen: fresh.exporterLogsFailOpen,
    exporterTracesRetries: fresh.exporterTracesRetries,
    exporterTracesBackoffMs: fresh.exporterTracesBackoffMs,
    exporterTracesTimeoutMs: fresh.exporterTracesTimeoutMs,
    exporterTracesFailOpen: fresh.exporterTracesFailOpen,
    exporterMetricsRetries: fresh.exporterMetricsRetries,
    exporterMetricsBackoffMs: fresh.exporterMetricsBackoffMs,
    exporterMetricsTimeoutMs: fresh.exporterMetricsTimeoutMs,
    exporterMetricsFailOpen: fresh.exporterMetricsFailOpen,
    securityMaxAttrValueLength: fresh.securityMaxAttrValueLength,
    securityMaxAttrCount: fresh.securityMaxAttrCount,
    sloEnableRedMetrics: fresh.sloEnableRedMetrics,
    sloEnableUseMetrics: fresh.sloEnableUseMetrics,
    piiMaxDepth: fresh.piiMaxDepth,
  };
  updateRuntimeConfig(overrides);
}

const PROVIDER_CHANGING_FIELDS: (keyof TelemetryConfig)[] = [
  'otelEnabled',
  'otlpEndpoint',
  'otlpHeaders',
];

/**
 * Apply config changes.
 * If provider-changing fields differ and providers are already registered, performs a
 * best-effort shutdown (fire-and-forget) then re-initialises — matching Go/Python behaviour.
 * Otherwise delegates to setupTelemetry.
 */
export function reconfigureTelemetry(config: Partial<TelemetryConfig>): void {
  const current = getRuntimeConfig();
  const proposed: TelemetryConfig = { ...current, ...config };

  if (_providersRegistered) {
    const changed = PROVIDER_CHANGING_FIELDS.some(
      (k) => JSON.stringify(current[k]) !== JSON.stringify(proposed[k]),
    );
    if (changed) {
      // Best-effort async shutdown — fire-and-forget, errors ignored (mirrors Go's `_ = ShutdownTelemetry(ctx)`)
      const providers = _getRegisteredProviders();
      // Stryker disable LogicalOperator: ?? vs && is equivalent here — forceFlush/shutdown return Promise (truthy) so && still resolves; when undefined, Promise.allSettled wraps both in Promise.resolve
      void Promise.allSettled(providers.map((p) => p.forceFlush?.() ?? Promise.resolve())).then(
        () => Promise.allSettled(providers.map((p) => p.shutdown?.() ?? Promise.resolve())),
      );
      // Stryker restore LogicalOperator
      _providersRegistered = false;
      _registeredProviders = [];
    }
  }

  setupTelemetry(proposed);
  _activeConfig = proposed;
}

export function _resetRuntimeForTests(): void {
  _activeConfig = null;
  _providersRegistered = false;
  _registeredProviders = [];
}
