// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

import {
  getConfig,
  getLogger,
  getRuntimeConfig,
  getRuntimeStatus,
  reconfigureTelemetry,
  registerOtelProviders,
  resetTelemetryState,
  setTraceContext,
  setupTelemetry,
  shutdownTelemetry,
  updateRuntimeConfig,
} from '../../typescript/src/index.js';
import { _resetRootLogger } from '../../typescript/src/logger.js';

const TRACE_ID = '0af7651916cd43dd8448eb211c80319c';
const SPAN_ID = 'b7ad6b7169203331';

function ensureWindow(): Record<string, unknown[]> {
  const globalWithWindow = globalThis as typeof globalThis & {
    window?: Record<string, unknown[]>;
  };
  if (!globalWithWindow.window) globalWithWindow.window = {};
  globalWithWindow.window['__pinoLogs'] = [];
  return globalWithWindow.window;
}

function captureRecord(message: string): Record<string, unknown> {
  const windowRef = ensureWindow();
  const restore = {
    log: console.log,
    warn: console.warn,
    error: console.error,
  };
  console.log = () => {};
  console.warn = () => {};
  console.error = () => {};
  setTraceContext(TRACE_ID, SPAN_ID);
  try {
    getLogger('probe').info({ event: message }, message);
    const logs = (windowRef['__pinoLogs'] ?? []) as Record<string, unknown>[];
    if (logs.length === 0) {
      throw new Error('no captured logs');
    }
    return logs[0];
  } finally {
    console.log = restore.log;
    console.warn = restore.warn;
    console.error = restore.error;
  }
}

function caseLazyInitLogger(): Record<string, unknown> {
  resetTelemetryState();
  return { case: 'lazy_init_logger', record: captureRecord('log.output.parity') };
}

async function caseLazyLoggerShutdownReSetup(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  const first = captureRecord('log.output.parity');
  await shutdownTelemetry();
  const second = getRuntimeStatus();
  process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] = 'probe-restarted';
  process.env['PROVIDE_TELEMETRY_ENV'] = 'parity-restarted';
  process.env['PROVIDE_TELEMETRY_VERSION'] = '9.9.9';
  setupTelemetry({ consoleOutput: false, captureToWindow: true });
  const third = getRuntimeStatus();
  const restarted = captureRecord('log.output.restart');
  await shutdownTelemetry();
  return {
    case: 'lazy_logger_shutdown_re_setup',
    first_logger_emitted: first['message'] === 'log.output.parity',
    shutdown_cleared_setup: !second.setupDone,
    shutdown_cleared_providers:
      !second.providers.logs && !second.providers.traces && !second.providers.metrics,
    shutdown_fallback_all: second.fallback.logs && second.fallback.traces && second.fallback.metrics,
    re_setup_done: third.setupDone,
    second_logger_uses_fresh_config:
      restarted['service'] === 'probe-restarted' &&
      restarted['env'] === 'parity-restarted' &&
      restarted['version'] === '9.9.9',
  };
}

async function caseStrictSchemaRejection(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true });
  const record = captureRecord('Bad.Event.Ok');
  await shutdownTelemetry();
  return {
    case: 'strict_schema_rejection',
    emitted: true,
    schema_error: Object.prototype.hasOwnProperty.call(record, '_schema_error'),
  };
}

async function caseStrictEventNameOnly(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true });
  const record = captureRecord('Bad.Event.Ok');
  await shutdownTelemetry();
  return {
    case: 'strict_event_name_only',
    emitted: true,
    schema_error: Object.prototype.hasOwnProperty.call(record, '_schema_error'),
  };
}

async function caseRequiredKeysRejection(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true });
  const record = captureRecord('user.auth.ok');
  await shutdownTelemetry();
  return {
    case: 'required_keys_rejection',
    emitted: true,
    schema_error: Object.prototype.hasOwnProperty.call(record, '_schema_error'),
  };
}

function caseInvalidConfig(): Record<string, unknown> {
  resetTelemetryState();
  try {
    setupTelemetry();
    return { case: 'invalid_config', raised: false };
  } catch {
    return { case: 'invalid_config', raised: true };
  }
}

async function caseFailOpenExporterInit(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true, otelEnabled: true });
  await registerOtelProviders(getConfig());
  const status = getRuntimeStatus();
  await shutdownTelemetry();
  return {
    case: 'fail_open_exporter_init',
    setup_done: status.setupDone,
    providers_cleared: !status.providers.logs && !status.providers.traces && !status.providers.metrics,
    fallback_all: status.fallback.logs && status.fallback.traces && status.fallback.metrics,
  };
}

async function caseSignalEnablement(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true, otelEnabled: true });
  const status = getRuntimeStatus();
  await shutdownTelemetry();
  return {
    case: 'signal_enablement',
    setup_done: status.setupDone,
    logs_enabled: status.signals.logs,
    traces_enabled: status.signals.traces,
    metrics_enabled: status.signals.metrics,
  };
}

async function casePerSignalLogsEndpoint(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true, otelEnabled: true });
  await registerOtelProviders(getConfig());
  const status = getRuntimeStatus();
  await shutdownTelemetry();
  return {
    case: 'per_signal_logs_endpoint',
    setup_done: status.setupDone,
    logs_provider: status.providers.logs,
    traces_provider: status.providers.traces,
    metrics_provider: status.providers.metrics,
  };
}

async function caseProviderIdentityReconfigure(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({ consoleOutput: false, captureToWindow: true, otelEnabled: true });
  await registerOtelProviders(getConfig());
  const before = getRuntimeStatus();
  const serviceBefore = getRuntimeConfig().serviceName;
  let raised = false;
  try {
    reconfigureTelemetry({ serviceName: `${serviceBefore}-renamed` });
  } catch {
    raised = true;
  }
  const configPreserved = getRuntimeConfig().serviceName === serviceBefore;
  await shutdownTelemetry();
  return {
    case: 'provider_identity_reconfigure',
    providers_active: before.providers.logs || before.providers.traces || before.providers.metrics,
    raised,
    config_preserved: configPreserved,
  };
}

/**
 * A host application's own SDK provider must be adopted, and gated on enablement.
 *
 * TypeScript detects this for itself: installing the provider on the OTel
 * global is enough, because getRuntimeStatus probes the global for the
 * forceFlush/shutdown lifecycle pair.
 */
/** Counter, gauge and histogram output — the values, not just the flags. */
async function caseMetricInstrumentValues(): Promise<Record<string, unknown>> {
  const { counter, gauge, histogram } = await import('../../typescript/src/index.js');

  setupTelemetry({ metricsEnabled: true });

  const c = counter('probe.metric.counter');
  c.add(1);
  c.add(2);
  c.add(4);

  const g = gauge('probe.metric.gauge');
  g.set(42);

  const h = histogram('probe.metric.histogram');
  for (const value of [1, 2, 3]) h.record(value);

  const result = {
    case: 'metric_instrument_values',
    counter_value: String(c.value),
    gauge_value: String(g.value),
    histogram_count: String(h.count),
    histogram_total: String(h.total),
  };
  await shutdownTelemetry();
  return result;
}

async function caseHostProviderAdoption(): Promise<Record<string, unknown>> {
  // Resolved against the facade's own package rather than this file: the probe
  // lives outside typescript/, so a bare specifier here would not resolve — and
  // resolving it to a *second* copy of @opentelemetry/api would silently defeat
  // the test, since the global we set would not be the global the facade reads.
  const { createRequire } = await import('node:module');
  const facadeRequire = createRequire(new URL('../../typescript/package.json', import.meta.url));
  const api = facadeRequire('@opentelemetry/api') as typeof import('@opentelemetry/api');
  const sdk = facadeRequire('@opentelemetry/sdk-trace-base') as typeof import('@opentelemetry/sdk-trace-base');

  api.trace.setGlobalTracerProvider(new sdk.BasicTracerProvider() as never);

  const before = getRuntimeStatus();

  setupTelemetry({ tracingEnabled: true });
  const enabled = getRuntimeStatus();
  await shutdownTelemetry();

  setupTelemetry({ tracingEnabled: false });
  const disabled = getRuntimeStatus();
  await shutdownTelemetry();

  return {
    case: 'host_provider_adoption',
    adopted_before_setup: before.providers.traces,
    adopted_after_enabled_setup: enabled.providers.traces,
    fallback_after_disabled_setup: disabled.fallback.traces,
  };
}

function captureEmit(name: string, level: 'debug' | 'info', message: string): Record<string, unknown>[] {
  const windowRef = ensureWindow();
  const restore = { log: console.log, warn: console.warn, error: console.error };
  console.log = () => {};
  console.warn = () => {};
  console.error = () => {};
  try {
    const logger = getLogger(name);
    if (level === 'debug') {
      logger.debug({ event: message }, message);
    } else {
      logger.info({ event: message }, message);
    }
    return [...((windowRef['__pinoLogs'] ?? []) as Record<string, unknown>[])];
  } finally {
    console.log = restore.log;
    console.warn = restore.warn;
    console.error = restore.error;
  }
}

function hasMessage(records: Record<string, unknown>[], message: string): boolean {
  return records.some((rec) => rec['message'] === message || rec['msg'] === message);
}

async function caseHotReloadLogLevel(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({
    serviceName: 'probe',
    logLevel: 'info',
    logFormat: 'json',
    captureToWindow: true,
    consoleOutput: false,
  });
  const serviceBefore = getRuntimeConfig().serviceName;
  ensureWindow();
  _resetRootLogger();
  const before = captureEmit('probe', 'debug', 'hot.level.debug.before');

  updateRuntimeConfig({ logging: { logLevel: 'debug' } });
  _resetRootLogger();
  ensureWindow();
  const after = captureEmit('probe', 'debug', 'hot.level.debug.after');
  const cfg = getRuntimeConfig();
  await shutdownTelemetry();
  return {
    case: 'hot_reload_log_level',
    first_debug_suppressed: !hasMessage(before, 'hot.level.debug.before'),
    second_debug_emitted: hasMessage(after, 'hot.level.debug.after'),
    level_config_updated: String(cfg.logLevel).toLowerCase() === 'debug',
    service_preserved: cfg.serviceName === serviceBefore,
  };
}

async function caseHotReloadLogFormat(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({
    serviceName: 'probe',
    logLevel: 'info',
    logFormat: 'json',
    captureToWindow: true,
    consoleOutput: false,
  });
  const statusBefore = getRuntimeStatus();
  const serviceBefore = getRuntimeConfig().serviceName;
  updateRuntimeConfig({ logging: { logFormat: 'console' } });
  const cfg = getRuntimeConfig();
  const statusAfter = getRuntimeStatus();
  await shutdownTelemetry();
  return {
    case: 'hot_reload_log_format',
    format_config_updated: String(cfg.logFormat).toLowerCase() === 'console',
    service_preserved: cfg.serviceName === serviceBefore,
    providers_unchanged:
      JSON.stringify(statusBefore.providers) === JSON.stringify(statusAfter.providers),
  };
}

async function caseHotReloadModuleLevel(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry({
    serviceName: 'probe',
    logLevel: 'info',
    logFormat: 'json',
    captureToWindow: true,
    consoleOutput: false,
  });
  const serviceBefore = getRuntimeConfig().serviceName;
  ensureWindow();
  _resetRootLogger();
  const before = captureEmit('probe.child', 'debug', 'hot.module.debug.before');

  // Pure module-only promotion: the global level stays at info and only the
  // module override lifts `probe.child` to debug.  All four languages must
  // honour this precise contract.
  updateRuntimeConfig({
    logging: {
      logModuleLevels: { 'probe.child': 'debug' },
    },
  });
  _resetRootLogger();
  ensureWindow();
  const after = captureEmit('probe.child', 'debug', 'hot.module.debug.after');
  const cfg = getRuntimeConfig();
  await shutdownTelemetry();
  return {
    case: 'hot_reload_module_level',
    first_debug_suppressed: !hasMessage(before, 'hot.module.debug.before'),
    module_debug_emitted: hasMessage(after, 'hot.module.debug.after'),
    module_levels_config_updated:
      String((cfg.logModuleLevels ?? {})['probe.child']).toLowerCase() === 'debug',
    service_preserved: cfg.serviceName === serviceBefore,
  };
}

async function caseShutdownReSetup(): Promise<Record<string, unknown>> {
  resetTelemetryState();
  setupTelemetry();
  const first = getRuntimeStatus();
  await shutdownTelemetry();
  const second = getRuntimeStatus();
  setupTelemetry();
  const third = getRuntimeStatus();
  await shutdownTelemetry();
  return {
    case: 'shutdown_re_setup',
    first_setup_done: first.setupDone,
    shutdown_cleared_setup: !second.setupDone,
    shutdown_cleared_providers:
      !second.providers.logs && !second.providers.traces && !second.providers.metrics,
    shutdown_fallback_all: second.fallback.logs && second.fallback.traces && second.fallback.metrics,
    re_setup_done: third.setupDone,
    signals_match: JSON.stringify(first.signals) === JSON.stringify(third.signals),
    providers_match: JSON.stringify(first.providers) === JSON.stringify(third.providers),
  };
}

async function main(): Promise<void> {
  const caseId = process.env['PROVIDE_PARITY_PROBE_CASE'];
  const cases: Record<string, () => Promise<object> | object> = {
    lazy_init_logger: caseLazyInitLogger,
    lazy_logger_shutdown_re_setup: caseLazyLoggerShutdownReSetup,
    strict_schema_rejection: caseStrictSchemaRejection,
    strict_event_name_only: caseStrictEventNameOnly,
    required_keys_rejection: caseRequiredKeysRejection,
    invalid_config: caseInvalidConfig,
    fail_open_exporter_init: caseFailOpenExporterInit,
    signal_enablement: caseSignalEnablement,
    per_signal_logs_endpoint: casePerSignalLogsEndpoint,
    provider_identity_reconfigure: caseProviderIdentityReconfigure,
    host_provider_adoption: caseHostProviderAdoption,
    metric_instrument_values: caseMetricInstrumentValues,
    shutdown_re_setup: caseShutdownReSetup,
    hot_reload_log_level: caseHotReloadLogLevel,
    hot_reload_log_format: caseHotReloadLogFormat,
    hot_reload_module_level: caseHotReloadModuleLevel,
  };

  const handler = cases[caseId ?? ''];
  if (!handler) {
    throw new Error(`unknown case: ${String(caseId)}`);
  }
  const result = await handler();
  console.log(JSON.stringify(result));
}

void main();
