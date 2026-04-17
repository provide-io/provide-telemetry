// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

import {
  getConfig,
  getLogger,
  getRuntimeStatus,
  registerOtelProviders,
  resetTelemetryState,
  setTraceContext,
  setupTelemetry,
  shutdownTelemetry,
} from '../../typescript/src/index.js';

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
    re_setup_done: third.setupDone,
    signals_match: JSON.stringify(first.signals) === JSON.stringify(third.signals),
    providers_match: JSON.stringify(first.providers) === JSON.stringify(third.providers),
  };
}

async function main(): Promise<void> {
  const caseId = process.env['PROVIDE_PARITY_PROBE_CASE'];
  const result =
    caseId === 'lazy_init_logger'
      ? caseLazyInitLogger()
      : caseId === 'strict_schema_rejection'
        ? await caseStrictSchemaRejection()
        : caseId === 'required_keys_rejection'
          ? await caseRequiredKeysRejection()
          : caseId === 'invalid_config'
            ? caseInvalidConfig()
            : caseId === 'fail_open_exporter_init'
              ? await caseFailOpenExporterInit()
            : caseId === 'signal_enablement'
              ? await caseSignalEnablement()
            : caseId === 'shutdown_re_setup'
              ? await caseShutdownReSetup()
              : (() => {
                  throw new Error(`unknown case: ${String(caseId)}`);
                })();

  console.log(JSON.stringify(result));
}

void main();
