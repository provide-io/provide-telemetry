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
import { ConfigurationError } from './exceptions';
import { getHealthSnapshot } from './health';

/** Minimal interface for providers that can be flushed and shut down cleanly. */
export interface ShutdownableProvider {
  forceFlush?(): Promise<void>;
  shutdown?(): Promise<void>;
}

export interface RuntimeStatus {
  setupDone: boolean;
  signals: {
    logs: boolean;
    traces: boolean;
    metrics: boolean;
  };
  providers: {
    logs: boolean;
    traces: boolean;
    metrics: boolean;
  };
  fallback: {
    logs: boolean;
    traces: boolean;
    metrics: boolean;
  };
  setupError: string | null;
}

let _activeConfig: TelemetryConfig | null = null;
// Stryker disable next-line BooleanLiteral: initial false is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _providersRegistered = false;
// Stryker disable next-line ArrayDeclaration: initial [] is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _registeredProviders: ShutdownableProvider[] = [];
let _providerSignals = { logs: false, traces: false, metrics: false };

function resolveEffectiveConfig(): TelemetryConfig {
  return _activeConfig ?? configFromEnv();
}

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

export function _setProviderSignalInstalled(signal: 'logs' | 'traces' | 'metrics', installed: boolean): void {
  _providerSignals[signal] = installed;
}

export function getRuntimeStatus(): RuntimeStatus {
  const cfg = resolveEffectiveConfig();
  return {
    setupDone: _activeConfig !== null,
    signals: {
      logs: true,
      traces: cfg.tracingEnabled,
      metrics: cfg.metricsEnabled,
    },
    providers: { ..._providerSignals },
    fallback: {
      logs: !_providerSignals.logs,
      traces: !_providerSignals.traces,
      metrics: !_providerSignals.metrics,
    },
    setupError: getHealthSnapshot().setupError,
  };
}

function deepFreeze<T extends object>(obj: T): Readonly<T> {
  for (const val of Object.values(obj)) {
    // Stryker disable next-line ConditionalExpression,EqualityOperator,LogicalOperator: frozen-object guard — all sub-conditions required but only observable with deeply nested mutable objects
    if (typeof val === 'object' && val !== null && !Object.isFrozen(val)) {
      deepFreeze(val as object);
    }
  }
  return Object.freeze(obj);
}

/** Return the active runtime config (or env-derived defaults if none set). */
export function getRuntimeConfig(): Readonly<TelemetryConfig> {
  const cfg = resolveEffectiveConfig();
  return deepFreeze({ ...cfg });
}

/** Merge hot-reloadable overrides into the active config and re-apply policies. */
export function updateRuntimeConfig(overrides: RuntimeOverrides): void {
  validateRuntimeOverrides(overrides);
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

function validateRate(name: string, value: number | undefined): void {
  if (value === undefined) return;
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    // Stryker disable next-line StringLiteral: error message content
    throw new ConfigurationError(`${name} must be in [0, 1], got ${String(value)}`);
  }
}

function validateNonNegativeInteger(name: string, value: number | undefined): void {
  if (value === undefined) return;
  if (!Number.isInteger(value) || value < 0) {
    // Stryker disable next-line StringLiteral: error message content
    throw new ConfigurationError(`${name} must be a non-negative integer, got ${String(value)}`);
  }
}

function validateNonNegativeNumber(name: string, value: number | undefined): void {
  if (value === undefined) return;
  if (!Number.isFinite(value) || value < 0) {
    // Stryker disable next-line StringLiteral: error message content
    throw new ConfigurationError(`${name} must be >= 0, got ${String(value)}`);
  }
}

/* Stryker disable StringLiteral: field names in validation calls are only used in error messages — mutating them does not change validation behavior */
function validateRuntimeOverrides(overrides: RuntimeOverrides): void {
  validateRate('samplingLogsRate', overrides.samplingLogsRate);
  validateRate('samplingTracesRate', overrides.samplingTracesRate);
  validateRate('samplingMetricsRate', overrides.samplingMetricsRate);
  validateNonNegativeInteger('backpressureLogsMaxsize', overrides.backpressureLogsMaxsize);
  validateNonNegativeInteger('backpressureTracesMaxsize', overrides.backpressureTracesMaxsize);
  validateNonNegativeInteger('backpressureMetricsMaxsize', overrides.backpressureMetricsMaxsize);
  validateNonNegativeInteger('exporterLogsRetries', overrides.exporterLogsRetries);
  validateNonNegativeInteger('exporterTracesRetries', overrides.exporterTracesRetries);
  validateNonNegativeInteger('exporterMetricsRetries', overrides.exporterMetricsRetries);
  validateNonNegativeNumber('exporterLogsBackoffMs', overrides.exporterLogsBackoffMs);
  validateNonNegativeNumber('exporterTracesBackoffMs', overrides.exporterTracesBackoffMs);
  validateNonNegativeNumber('exporterMetricsBackoffMs', overrides.exporterMetricsBackoffMs);
  validateNonNegativeNumber('exporterLogsTimeoutMs', overrides.exporterLogsTimeoutMs);
  validateNonNegativeNumber('exporterTracesTimeoutMs', overrides.exporterTracesTimeoutMs);
  validateNonNegativeNumber('exporterMetricsTimeoutMs', overrides.exporterMetricsTimeoutMs);
  validateNonNegativeInteger('securityMaxAttrValueLength', overrides.securityMaxAttrValueLength);
  validateNonNegativeInteger('securityMaxAttrCount', overrides.securityMaxAttrCount);
  validateNonNegativeInteger('piiMaxDepth', overrides.piiMaxDepth);
}
/* Stryker restore StringLiteral */

const _COLD_FIELDS: (keyof TelemetryConfig)[] = [
  'serviceName',
  'environment',
  'version',
  'otelEnabled',
  'tracingEnabled',
  'metricsEnabled',
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
      /* Stryker disable StringLiteral: warning message content */
      console.warn(
        '[provide-telemetry] runtime.cold_field_drift:',
        drifted.join(', '),
        '— restart required to apply',
      );
      /* Stryker restore StringLiteral */
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
    strictSchema: fresh.strictSchema,
  };
  updateRuntimeConfig(overrides);
}

const PROVIDER_CHANGING_FIELDS: (keyof TelemetryConfig)[] = [
  'serviceName',
  'environment',
  'version',
  'otelEnabled',
  'tracingEnabled',
  'metricsEnabled',
  'otlpEndpoint',
  'otlpHeaders',
  'otlpLogsEndpoint',
  'otlpLogsHeaders',
  'otlpTracesEndpoint',
  'otlpTracesHeaders',
  'otlpMetricsEndpoint',
  'otlpMetricsHeaders',
];

/**
 * Apply config changes.
 * If provider-changing fields differ and providers are already registered, fail fast:
 * provider replacement requires explicit process restart to avoid async export loss.
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
      throw new ConfigurationError(
        'provider-changing reconfiguration is unsupported after OpenTelemetry providers are installed; restart the process and call setupTelemetry() with the new config',
      );
    }
  }

  setupTelemetry(proposed);
}

/** Clear provider registration state. Called by shutdownTelemetry after flush/shutdown. */
export function _clearProviderState(): void {
  _providersRegistered = false;
  _registeredProviders = [];
  _providerSignals = { logs: false, traces: false, metrics: false };
  _activeConfig = null;
}

/** Called by setupTelemetry to keep _activeConfig in sync. */
export function _setActiveConfig(cfg: TelemetryConfig): void {
  _activeConfig = cfg;
}

export function _resetRuntimeForTests(): void {
  _activeConfig = null;
  _providersRegistered = false;
  _registeredProviders = [];
  _providerSignals = { logs: false, traces: false, metrics: false };
}
