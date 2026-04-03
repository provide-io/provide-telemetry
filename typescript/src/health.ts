// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Internal self-observability counters — mirrors Python provide.telemetry.health.
 */

export interface HealthSnapshot {
  logsEmitted: number;
  logsDropped: number;
  tracesEmitted: number;
  tracesDropped: number;
  metricsEmitted: number;
  metricsDropped: number;
  exportFailures: number;
  exportRetries: number;
  asyncBlockingRisk: number;
  exemplarUnsupported: number;
  lastExportError: string | null;
  exportLatencyMs: number;
  circuitStateLogs: string;
  circuitStateTraces: string;
  circuitStateMetrics: string;
  circuitOpenCountLogs: number;
  circuitOpenCountTraces: number;
  circuitOpenCountMetrics: number;
  circuitCooldownRemainingLogs: number;
  circuitCooldownRemainingTraces: number;
  circuitCooldownRemainingMetrics: number;
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
  | 'exportFailures'
  | 'exportRetries'
  | 'asyncBlockingRisk'
  | 'exemplarUnsupported';

let _setupError: string | null = null;

const _state = {
  logsEmitted: 0,
  logsDropped: 0,
  tracesEmitted: 0,
  tracesDropped: 0,
  metricsEmitted: 0,
  metricsDropped: 0,
  exportFailures: 0,
  exportRetries: 0,
  asyncBlockingRisk: 0,
  exemplarUnsupported: 0,
  lastExportError: null as string | null,
  exportLatencyMs: 0,
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
    circuitCooldownRemainingLogs: csLogs.cooldownRemainingMs,
    circuitCooldownRemainingTraces: csTraces.cooldownRemainingMs,
    circuitCooldownRemainingMetrics: csMetrics.cooldownRemainingMs,
    setupError: _setupError,
  };
}

export function setSetupError(error: string | null): void {
  _setupError = error;
}

export function _incrementHealth(field: NumericHealthField, by: number = 1): void {
  _state[field] += by;
}

export function _recordExportLatency(ms: number): void {
  _state.exportLatencyMs = ms;
}

/** Set the last export error message (used by resilience module). */
export function _setLastExportError(err: string | null): void {
  _state.lastExportError = err;
}

export function _resetHealthForTests(): void {
  _state.logsEmitted = 0;
  _state.logsDropped = 0;
  _state.tracesEmitted = 0;
  _state.tracesDropped = 0;
  _state.metricsEmitted = 0;
  _state.metricsDropped = 0;
  _state.exportFailures = 0;
  _state.exportRetries = 0;
  _state.asyncBlockingRisk = 0;
  _state.exemplarUnsupported = 0;
  _state.lastExportError = null;
  _state.exportLatencyMs = 0;
  _setupError = null;
}
