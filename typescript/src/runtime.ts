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
import {
  _areProvidersRegistered,
  _clearProviderRegistry,
  _isLogsProviderInstalled,
  type SignalName,
} from './provider-registry.js';

export {
  _areProvidersRegistered,
  _getProvidersBySignal,
  _getRegisteredProviders,
  _markProvidersRegistered,
  _setLogsProviderInstalled,
  _storeRegisteredProviders,
  type ShutdownableProvider,
  type SignalName,
} from './provider-registry.js';

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

  /**
   * Drain installed providers and report each signal's own outcome.
   *
   * A signal with no provider is `notInstalled`. A signal reported installed but
   * with no provider of ours behind it — traces and metrics status is probed
   * against the OTel globals, so a host application's own SDK counts — is
   * `notOwned`: we do not drain it, and calling it `flushed` would say the
   * records are out when they are still in the host's queue. The rest carry
   * their own drain result, not an aggregate of all three.
   */
  async flush(timeoutMs?: number): Promise<FlushResult> {
    const { flushSignals } = await import('./shutdown.js');
    const providers = getRuntimeStatus().providers;
    const drained = await flushSignals(timeoutMs);
    const resultFor = (signal: SignalName, installed: boolean): SignalFlushResult => {
      const base = {
        flushed: false,
        notInstalled: false,
        notOwned: false,
        timedOut: false,
        failed: false,
      };
      if (!installed) return { ...base, notInstalled: true };
      const ours = drained[signal];
      if (ours === undefined) return { ...base, notOwned: true };
      return { ...base, flushed: ours, timedOut: !ours };
    };
    return {
      logs: resultFor('logs', providers.logs),
      traces: resultFor('traces', providers.traces),
      metrics: resultFor('metrics', providers.metrics),
    };
  }

  // All three names are optional, matching the module-level functions these
  // delegate to and the Python/Rust facades. A required name here would narrow
  // the underlying API for no reason — the same defect that made Python's
  // get_logger() raise TypeError on the documented zero-argument form.
  getLogger(name?: string): ReturnType<typeof getLogger> {
    return getLogger(name);
  }

  getTracer(name?: string): ReturnType<typeof getTracer> {
    return getTracer(name);
  }

  getMeter(name?: string): ReturnType<typeof getMeter> {
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
function resolveEffectiveConfig(): TelemetryConfig {
  return _activeConfig ?? configFromEnv();
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
      logs: _isLogsProviderInstalled(),
      traces: tracesInstalled,
      metrics: metricsInstalled,
    },
    fallback: {
      logs: !_isLogsProviderInstalled(),
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
  // Publish only once setupTelemetry has accepted the merged config. It applies
  // ceilings this function does not (exporter retries, for one) and throws on a
  // value that passed validateRuntimeOverrides, so assigning first would leave
  // the snapshot reporting a rejected config while the exporter policy still
  // ran on the old one.
  const previous = _activeConfig;
  _activeConfig = merged;
  try {
    // setupTelemetry() bumps _configVersion, which forces the logger root to
    // rebuild on next getLogger() call so new level/format take effect.
    setupTelemetry(merged);
  } catch (err: unknown) {
    _activeConfig = previous;
    throw err;
  }
}

function validateNonNegativeNumber(name: string, value: number | undefined): void {
  if (value === undefined) return;
  if (!Number.isFinite(value) || value < 0) {
    // Stryker disable next-line StringLiteral: error message content
    throw new ConfigurationError(`${name} must be >= 0, got ${String(value)}`);
  }
}

/**
 * Check the override fields `setupTelemetry` does not.
 *
 * Rates, backpressure sizes, retry counts and the security/PII limits are all
 * re-checked by `_validateConfig` against the merged config a few lines below,
 * with the same bounds and the same message wording. Validating them here as
 * well duplicated the rule without changing any outcome: with the rejected
 * update now rolled back, disabling either copy left the other one throwing, so
 * neither was observable on its own.
 *
 * The backoff and timeout fields are genuinely only checked here — they are not
 * part of `_validateConfig` — so this is what remains.
 */
/* Stryker disable StringLiteral: field names in validation calls are only used in error messages — mutating them does not change validation behavior */
function validateRuntimeOverrides(overrides: RuntimeOverrides): void {
  validateNonNegativeNumber('exporterLogsBackoffMs', overrides.exporterLogsBackoffMs);
  validateNonNegativeNumber('exporterTracesBackoffMs', overrides.exporterTracesBackoffMs);
  validateNonNegativeNumber('exporterMetricsBackoffMs', overrides.exporterMetricsBackoffMs);
  validateNonNegativeNumber('exporterLogsTimeoutMs', overrides.exporterLogsTimeoutMs);
  validateNonNegativeNumber('exporterTracesTimeoutMs', overrides.exporterTracesTimeoutMs);
  validateNonNegativeNumber('exporterMetricsTimeoutMs', overrides.exporterMetricsTimeoutMs);
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

  if (_areProvidersRegistered()) {
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
  _clearProviderRegistry();
  _activeConfig = null;
}

/** Called by setupTelemetry to keep _activeConfig in sync. */
export function _setActiveConfig(cfg: TelemetryConfig): void {
  _activeConfig = cfg;
}

export function _resetRuntimeForTests(): void {
  _activeConfig = null;
  _clearProviderRegistry();
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
