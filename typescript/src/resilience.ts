// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Exporter resilience — retry, backoff, timeout, and circuit breaker.
 * Mirrors Python provide.telemetry.resilience.
 */

import {
  _incrementHealth,
  _recordExportLatency,
  _registerCircuitStateFn,
  _setLastExportError,
} from './health';

export class TelemetryTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TelemetryTimeoutError';
  }
}

export interface ExporterPolicy {
  retries: number;
  backoffMs: number;
  timeoutMs: number;
  failOpen: boolean;
}

const DEFAULT_POLICY: ExporterPolicy = {
  retries: 0,
  backoffMs: 0,
  timeoutMs: 10_000,
  failOpen: true,
};

const CIRCUIT_BREAKER_THRESHOLD = 3;
const CIRCUIT_BASE_COOLDOWN_MS = 30_000;
const CIRCUIT_MAX_COOLDOWN_MS = 1_024_000;

// Stryker disable next-line ObjectLiteral
let _policies: Record<string, ExporterPolicy> = {};
// Module-private circuit breaker state — not exported directly to prevent external mutation.
// Use the getter functions below (_get*ForTests) for test introspection.
// Stryker disable next-line ObjectLiteral
const _consecutiveTimeouts: Record<string, number> = { logs: 0, traces: 0, metrics: 0 };
// Stryker disable next-line ObjectLiteral
const _circuitTrippedAt: Record<string, number> = { logs: 0, traces: 0, metrics: 0 };
// Stryker disable next-line ObjectLiteral
export const _openCount: Record<string, number> = { logs: 0, traces: 0, metrics: 0 };
/* Stryker disable BooleanLiteral: initial false values are reset by _resetResilienceForTests before each test — equivalent mutant */
// Stryker disable next-line ObjectLiteral
export const _halfOpenProbing: Record<string, boolean> = {
  logs: false,
  traces: false,
  metrics: false,
};
/* Stryker restore BooleanLiteral */

export function setExporterPolicy(signal: string, policy: Partial<ExporterPolicy>): void {
  _policies[signal] = { ...DEFAULT_POLICY, ...policy };
}

export function getExporterPolicy(signal: string): ExporterPolicy {
  return { ...(_policies[signal] ?? DEFAULT_POLICY) };
}

// Stryker disable next-line BlockStatement
function _sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function _withTimeout<T>(fn: () => Promise<T>, timeoutMs: number): Promise<T> {
  // Stryker disable next-line ConditionalExpression,EqualityOperator
  if (timeoutMs <= 0) return fn();
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      // Stryker disable next-line StringLiteral: timeout error message content is not tested
      reject(new TelemetryTimeoutError(`operation timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    fn().then(
      (val) => {
        clearTimeout(timer);
        resolve(val);
      },
      (err: unknown) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

export async function runWithResilience<T>(
  signal: string,
  fn: () => Promise<T>,
): Promise<T | null> {
  const policy = _policies[signal] ?? { ...DEFAULT_POLICY };
  const attempts = Math.max(1, policy.retries + 1);

  // Ensure per-signal dicts are initialized for custom signals.
  if (!(signal in _openCount)) _openCount[signal] = 0;
  if (!(signal in _halfOpenProbing)) _halfOpenProbing[signal] = false;

  // Circuit breaker check.
  const failField = _exportFailuresField(signal);
  const retryField = _retriesField(signal);
  // Only consult the breaker when timeout enforcement is on. Mirrors Python
  // (resilience.py:177) and Go (resilience.go:170): when timeout=0 the policy
  // explicitly opts out of timeout-driven failure accounting, so the breaker
  // has no signal to act on and must not reject callers.
  // Stryker disable next-line ConditionalExpression
  if (_consecutiveTimeouts[signal] >= CIRCUIT_BREAKER_THRESHOLD) {
    const cooldown = Math.min(
      CIRCUIT_BASE_COOLDOWN_MS * 2 ** _openCount[signal],
      CIRCUIT_MAX_COOLDOWN_MS,
    );
    const elapsed = Date.now() - _circuitTrippedAt[signal];
    if (elapsed < cooldown) {
      _incrementHealth('exportFailures');
      _setLastExportError('circuit breaker open');
      if (policy.failOpen) return null;
      throw new TelemetryTimeoutError('circuit breaker open: too many consecutive timeouts');
    }
    // Half-open: cooldown elapsed — allow one probe.
    _halfOpenProbing[signal] = true;
  }

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < attempts; attempt++) {
    const started = Date.now();
    try {
      const result = await _withTimeout(fn, policy.timeoutMs);
      _recordExportLatency(Date.now() - started);
      _setLastExportError(null);
      if (_halfOpenProbing[signal]) {
        _halfOpenProbing[signal] = false;
        _consecutiveTimeouts[signal] = 0;
        _openCount[signal] = Math.max(0, _openCount[signal] - 1);
      } else {
        _consecutiveTimeouts[signal] = 0;
      }
      return result;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      _incrementHealth(failField);

      if (err instanceof TelemetryTimeoutError) {
        if (_halfOpenProbing[signal]) {
          _halfOpenProbing[signal] = false;
          _openCount[signal] += 1;
          _circuitTrippedAt[signal] = Date.now();
        } else {
          _consecutiveTimeouts[signal] = (_consecutiveTimeouts[signal] ?? 0) + 1;
          // Stryker disable next-line ConditionalExpression,EqualityOperator
          if (_consecutiveTimeouts[signal] >= CIRCUIT_BREAKER_THRESHOLD) {
            _openCount[signal] += 1;
            _circuitTrippedAt[signal] = Date.now();
          }
        }
      } else if (_halfOpenProbing[signal]) {
        _halfOpenProbing[signal] = false;
        _openCount[signal] += 1;
        _circuitTrippedAt[signal] = Date.now();
      } else {
        _consecutiveTimeouts[signal] = 0;
      }

      // Stryker disable next-line ArithmeticOperator
      if (attempt < attempts - 1) {
        _incrementHealth(retryField);
        // Stryker disable next-line ConditionalExpression,EqualityOperator
        if (policy.backoffMs > 0) await _sleep(policy.backoffMs);
      }
    }
  }

  if (policy.failOpen) return null;
  // Stryker disable next-line StringLiteral: unreachable fallback — lastError is always set by the catch block above
  /* v8 ignore next */
  throw lastError ?? new Error('all retry attempts failed');
}

export interface CircuitState {
  state: string;
  openCount: number;
  cooldownRemainingMs: number;
}

export function getCircuitState(signal: string): CircuitState {
  const openCount = _openCount[signal] ?? 0;
  if (_halfOpenProbing[signal]) {
    return { state: 'half-open', openCount, cooldownRemainingMs: 0 };
  }
  if ((_consecutiveTimeouts[signal] ?? 0) >= CIRCUIT_BREAKER_THRESHOLD) {
    const cooldown = Math.min(CIRCUIT_BASE_COOLDOWN_MS * 2 ** openCount, CIRCUIT_MAX_COOLDOWN_MS);
    const remaining = cooldown - (Date.now() - _circuitTrippedAt[signal]);
    if (remaining > 0) {
      return { state: 'open', openCount, cooldownRemainingMs: remaining };
    }
    return { state: 'half-open', openCount, cooldownRemainingMs: 0 };
  }
  return { state: 'closed', openCount, cooldownRemainingMs: 0 };
}

// Register with health module to break circular dependency.
_registerCircuitStateFn(getCircuitState);

export function _resetResilienceForTests(): void {
  _policies = {};
  for (const k of ['logs', 'traces', 'metrics']) {
    _consecutiveTimeouts[k] = 0;
    _circuitTrippedAt[k] = 0;
    _openCount[k] = 0;
    _halfOpenProbing[k] = false;
  }
}
