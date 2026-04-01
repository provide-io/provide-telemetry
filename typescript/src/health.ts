// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Internal self-observability counters — mirrors Python provide.telemetry.health.
 */

export interface HealthSnapshot {
  // Logs (8)
  logsEmitted: number;
  logsDropped: number;
  exportFailuresLogs: number;
  retriesLogs: number;
  exportLatencyMsLogs: number;
  asyncBlockingRiskLogs: number;
  circuitStateLogs: string;
  circuitOpenCountLogs: number;
  // Traces (8)
  tracesEmitted: number;
  tracesDropped: number;
  exportFailuresTraces: number;
  retriesTraces: number;
  exportLatencyMsTraces: number;
  asyncBlockingRiskTraces: number;
  circuitStateTraces: string;
  circuitOpenCountTraces: number;
  // Metrics (8)
  metricsEmitted: number;
  metricsDropped: number;
  exportFailuresMetrics: number;
  retriesMetrics: number;
  exportLatencyMsMetrics: number;
  asyncBlockingRiskMetrics: number;
  circuitStateMetrics: string;
  circuitOpenCountMetrics: number;
  // Global (1)
  setupError: string | null;
}

/** Numeric fields that live in the mutable _state object (not derived circuit fields). */
type NumericHealthField =
  | 'logsEmitted'
  | 'logsDropped'
  | 'tracesEmitted'
  | 'tracesDropped'
  | 'metricsEmitted'
  | 'metricsDropped'
  | 'exportFailuresLogs'
  | 'exportFailuresTraces'
  | 'exportFailuresMetrics'
  | 'retriesLogs'
  | 'retriesTraces'
  | 'retriesMetrics'
  | 'exportLatencyMsLogs'
  | 'exportLatencyMsTraces'
  | 'exportLatencyMsMetrics'
  | 'asyncBlockingRiskLogs'
  | 'asyncBlockingRiskTraces'
  | 'asyncBlockingRiskMetrics';

let _setupError: string | null = null;

const _state = {
  logsEmitted: 0,
  logsDropped: 0,
  tracesEmitted: 0,
  tracesDropped: 0,
  metricsEmitted: 0,
  metricsDropped: 0,
  exportFailuresLogs: 0,
  exportFailuresTraces: 0,
  exportFailuresMetrics: 0,
  retriesLogs: 0,
  retriesTraces: 0,
  retriesMetrics: 0,
  exportLatencyMsLogs: 0,
  exportLatencyMsTraces: 0,
  exportLatencyMsMetrics: 0,
  asyncBlockingRiskLogs: 0,
  asyncBlockingRiskTraces: 0,
  asyncBlockingRiskMetrics: 0,
};

// Lazy reference to avoid circular dependency at module load time.
// resilience.ts imports from health.ts, so we register the callback after load.
type CircuitStateResult = { state: string; openCount: number; cooldownRemainingMs: number };
type CircuitStateFn = (signal: string) => CircuitStateResult;

const _defaultCircuitState: CircuitStateResult = {
  state: 'closed',
  openCount: 0,
  cooldownRemainingMs: 0,
};
let _circuitStateFn: CircuitStateFn = () => _defaultCircuitState;

/** Called by resilience module to register the getCircuitState function. */
export function _registerCircuitStateFn(fn: CircuitStateFn): void {
  _circuitStateFn = fn;
}

export function getHealthSnapshot(): HealthSnapshot {
  const csLogs = _circuitStateFn('logs');
  const csTraces = _circuitStateFn('traces');
  const csMetrics = _circuitStateFn('metrics');
  return {
    ..._state,
    circuitStateLogs: csLogs.state,
    circuitStateTraces: csTraces.state,
    circuitStateMetrics: csMetrics.state,
    circuitOpenCountLogs: csLogs.openCount,
    circuitOpenCountTraces: csTraces.openCount,
    circuitOpenCountMetrics: csMetrics.openCount,
    setupError: _setupError,
  };
}

export function setSetupError(error: string | null): void {
  _setupError = error;
}

export function _incrementHealth(field: NumericHealthField, by: number = 1): void {
  _state[field] += by;
}

/** Map a signal name to the per-signal emitted field. */
export function _emittedField(signal: string): 'logsEmitted' | 'tracesEmitted' | 'metricsEmitted' {
  if (signal === 'traces') return 'tracesEmitted';
  if (signal === 'metrics') return 'metricsEmitted';
  return 'logsEmitted';
}

/** Map a signal name to the per-signal dropped field. */
export function _droppedField(signal: string): 'logsDropped' | 'tracesDropped' | 'metricsDropped' {
  if (signal === 'traces') return 'tracesDropped';
  if (signal === 'metrics') return 'metricsDropped';
  return 'logsDropped';
}

/** Map a signal name to the per-signal export-failures field. */
export function _exportFailuresField(
  signal: string,
): 'exportFailuresLogs' | 'exportFailuresTraces' | 'exportFailuresMetrics' {
  if (signal === 'traces') return 'exportFailuresTraces';
  if (signal === 'metrics') return 'exportFailuresMetrics';
  return 'exportFailuresLogs';
}

/** Map a signal name to the per-signal retries field. */
export function _retriesField(signal: string): 'retriesLogs' | 'retriesTraces' | 'retriesMetrics' {
  if (signal === 'traces') return 'retriesTraces';
  if (signal === 'metrics') return 'retriesMetrics';
  return 'retriesLogs';
}

/** Map a signal name to the per-signal export latency field. */
export function _exportLatencyField(
  signal: string,
): 'exportLatencyMsLogs' | 'exportLatencyMsTraces' | 'exportLatencyMsMetrics' {
  if (signal === 'traces') return 'exportLatencyMsTraces';
  if (signal === 'metrics') return 'exportLatencyMsMetrics';
  return 'exportLatencyMsLogs';
}

export function _recordExportLatency(signal: string, ms: number): void {
  _state[_exportLatencyField(signal)] = ms;
}

export function _resetHealthForTests(): void {
  _state.logsEmitted = 0;
  _state.logsDropped = 0;
  _state.tracesEmitted = 0;
  _state.tracesDropped = 0;
  _state.metricsEmitted = 0;
  _state.metricsDropped = 0;
  _state.exportFailuresLogs = 0;
  _state.exportFailuresTraces = 0;
  _state.exportFailuresMetrics = 0;
  _state.retriesLogs = 0;
  _state.retriesTraces = 0;
  _state.retriesMetrics = 0;
  _state.exportLatencyMsLogs = 0;
  _state.exportLatencyMsTraces = 0;
  _state.exportLatencyMsMetrics = 0;
  _state.asyncBlockingRiskLogs = 0;
  _state.asyncBlockingRiskTraces = 0;
  _state.asyncBlockingRiskMetrics = 0;
  _setupError = null;
}
