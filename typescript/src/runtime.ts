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
  getConfig,
  setupTelemetry,
} from './config.js';
import { ConfigurationError, ProviderImmutableError } from './exceptions.js';
import { getHealthSnapshot } from './health.js';
import { getLogger } from './logger.js';
import { getMeter } from './metrics.js';
import { _isLiveMeterProviderInstalled, _isLiveTracerProviderInstalled } from './otel-probe.js';
import { getTracer } from './tracing.js';

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

export enum ProviderMode {
  OWNED = 'owned',
  HOST = 'host',
  LOCAL = 'local',
}

export enum RuntimeState {
  LOCAL = 'local',
  STARTING = 'starting',
  READY = 'ready',
  DEGRADED = 'degraded',
  RECONFIGURING = 'reconfiguring',
  STOPPING = 'stopping',
  STOPPED = 'stopped',
}

export interface SignalFlushResult {
  flushed: boolean;
  notInstalled: boolean;
  notOwned: boolean;
  timedOut: boolean;
  failed: boolean;
}

export interface FlushResult {
  logs: SignalFlushResult;
  traces: SignalFlushResult;
  metrics: SignalFlushResult;
}

/**
 * Outcome of an attempted runtime reconfiguration.
 *
 * Field names are the cross-language canonical set — `previous`/`current` name the
 * configs on either side of the attempt, and `state` is the runtime state after it.
 * Python, Go and Rust declare the same five fields under the same names so a result
 * serialized by one runtime deserializes in another.
 */
export interface ReconfigureResult {
  applied: boolean;
  current?: TelemetryConfig;
  previous?: TelemetryConfig;
  state: RuntimeState;
  error?: string;
}

export class TelemetryRuntime {
  private state = RuntimeState.READY;
  private providerMode = ProviderMode.OWNED;

  constructor() {}

  async start(config?: TelemetryConfig): Promise<TelemetryConfig> {
    setupTelemetry(config);
    this.state = RuntimeState.READY;
    return getRuntimeConfig();
  }

  async shutdown(timeout?: number): Promise<void> {
    const { shutdownTelemetry } = await import('./shutdown.js');
    await shutdownTelemetry(timeout);
    // The drain has completed by here, so the terminal state is STOPPED
    // regardless of how it was requested — matching Python, Go and Rust.
    this.state = RuntimeState.STOPPED;
    return Promise.resolve();
  }

  async flush(timeoutMs?: number): Promise<FlushResult> {
    const { flushTelemetry } = await import('./shutdown.js');
    // Read provider status before draining: a signal with no provider installed
    // must report notInstalled rather than riding on flushTelemetry's vacuously
    // true [].every(). Mirrors the Rust facade.
    const providers = getRuntimeStatus().providers;
    const ok = await flushTelemetry(timeoutMs);
    const resultFor = (installed: boolean): SignalFlushResult => ({
      flushed: installed && ok,
      notInstalled: !installed,
      notOwned: false,
      timedOut: installed && !ok,
      failed: false,
    });
    return {
      logs: resultFor(providers.logs),
      traces: resultFor(providers.traces),
      metrics: resultFor(providers.metrics),
    };
  }

  getLogger(name: string): ReturnType<typeof getLogger> {
    return getLogger(name);
  }

  getTracer(name?: string): ReturnType<typeof getTracer> {
    return getTracer(name);
  }

  getMeter(name: string): ReturnType<typeof getMeter> {
    return getMeter(name);
  }

  getRuntimeConfig(): Readonly<TelemetryConfig> {
    return getRuntimeConfig();
  }

  getRuntimeStatus(): RuntimeStatus {
    return getRuntimeStatus();
  }

  updateConfig(cfg: RuntimeOverrides): ReconfigureResult {
    const previous = getRuntimeConfig();
    updateRuntimeConfig(cfg);
    return {
      applied: true,
      current: getRuntimeConfig(),
      previous,
      state: this.state,
    };
  }

  reconfigure(config: Partial<TelemetryConfig>): void {
    return reconfigureTelemetry(config);
  }
}

let _activeConfig: TelemetryConfig | null = null;
// Stryker disable next-line BooleanLiteral: initial false is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _providersRegistered = false;
// Stryker disable next-line ArrayDeclaration: initial [] is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _registeredProviders: ShutdownableProvider[] = [];
// Logs is the one signal whose provider state is bookkept at install time:
// traces and metrics are probed against the OTel globals instead (see
// getRuntimeStatus), so a host application's own SDK counts as installed. The
// logs API lives in the optional @opentelemetry/api-logs peer, which cannot be
// imported synchronously here, so there is nothing to probe against.
// Stryker disable next-line BooleanLiteral: initial value overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _logsProviderInstalled = false;

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

/** Called by registerOtelProviders once the OTLP log provider is live. */
export function _setLogsProviderInstalled(installed: boolean): void {
  _logsProviderInstalled = installed;
}

export function getRuntimeStatus(): RuntimeStatus {
  const cfg = resolveEffectiveConfig();
  // traces and metrics are probed live rather than read from install flags, so
  // a provider a host application installed itself reports as installed (and
  // not as fallback) instead of being invisible to us.
  //
  // Gated on the signal being enabled, because that is what the emit paths do
  // first (withTrace checks tracingEnabled, the instruments check
  // metricsEnabled). Reporting a provider for a signal the caller switched off
  // would claim an export path that nothing can reach.
  //
  // Deliberately getConfig() and not cfg: the emit paths read getConfig(),
  // which is the DEFAULTS until setupTelemetry() loads the environment, while
  // cfg falls back to configFromEnv() so `signals` can report configured
  // intent. Gating on cfg would make providers.traces claim a signal is dead
  // before setup while withTrace still exports through a host application's
  // provider — and would disagree with Python and Go, which both default a
  // signal on until a loaded config switches it off.
  const emitCfg = getConfig();
  const tracesInstalled = emitCfg.tracingEnabled && _isLiveTracerProviderInstalled();
  const metricsInstalled = emitCfg.metricsEnabled && _isLiveMeterProviderInstalled();
  return {
    setupDone: _activeConfig !== null,
    signals: {
      logs: true,
      traces: cfg.tracingEnabled,
      metrics: cfg.metricsEnabled,
    },
    providers: {
      logs: _logsProviderInstalled,
      traces: tracesInstalled,
      metrics: metricsInstalled,
    },
    fallback: {
      logs: !_logsProviderInstalled,
      traces: !tracesInstalled,
      metrics: !metricsInstalled,
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

/** Return the active runtime config (or live setupTelemetry config if none explicitly set via updateRuntimeConfig). */
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
    if (value === undefined) continue;
    if (key === 'logging') {
      // Flatten the nested logging override onto the flat TelemetryConfig
      // (parity with Python's RuntimeOverrides.logging which carries the
      // whole LoggingConfig dataclass).
      for (const [lk, lv] of Object.entries(value as Record<string, unknown>)) {
        if (lv !== undefined) {
          (merged as unknown as Record<string, unknown>)[lk] = lv;
        }
      }
      continue;
    }
    (merged as unknown as Record<string, unknown>)[key] = value;
  }
  _activeConfig = merged;
  // setupTelemetry() bumps _configVersion, which forces the logger root to
  // rebuild on next getLogger() call so new level/format take effect.
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
  'otlpLogsEndpoint',
  'otlpLogsHeaders',
  'otlpTracesEndpoint',
  'otlpTracesHeaders',
  'otlpMetricsEndpoint',
  'otlpMetricsHeaders',
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
    strictEventName: fresh.strictEventName,
    logging: {
      logLevel: fresh.logLevel,
      logFormat: fresh.logFormat,
      logIncludeTimestamp: fresh.logIncludeTimestamp,
      logIncludeCaller: fresh.logIncludeCaller,
      logSanitize: fresh.logSanitize,
      logCodeAttributes: fresh.logCodeAttributes,
      logModuleLevels: fresh.logModuleLevels,
      logPrettyKeyColor: fresh.logPrettyKeyColor,
      logPrettyValueColor: fresh.logPrettyValueColor,
      logPrettyFields: fresh.logPrettyFields,
    },
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
      throw new ProviderImmutableError(
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
  _logsProviderInstalled = false;
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
  _logsProviderInstalled = false;
}

export const _coldFieldsForTest: readonly (keyof TelemetryConfig)[] = _COLD_FIELDS;
export const _providerChangingFieldsForTest: readonly (keyof TelemetryConfig)[] =
  PROVIDER_CHANGING_FIELDS;

export type telemetryRuntime = TelemetryRuntime;
export type telemetryConfig = TelemetryConfig;
export type runtimeStatus = RuntimeStatus;
export type runtimeState = RuntimeState;
export type providerMode = ProviderMode;
export type signalFlushResult = SignalFlushResult;
export type flushResult = FlushResult;
export type reconfigureResult = ReconfigureResult;
