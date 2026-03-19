// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Internal self-observability counters — mirrors Python undef.telemetry.health.
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
}

type NumericHealthField = {
  [K in keyof HealthSnapshot]: HealthSnapshot[K] extends number ? K : never;
}[keyof HealthSnapshot];

const _state: HealthSnapshot = {
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
  lastExportError: null,
  exportLatencyMs: 0,
};

export function getHealthSnapshot(): HealthSnapshot {
  return { ..._state };
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
}
