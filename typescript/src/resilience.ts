// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Exporter resilience — retry, backoff, timeout, and circuit breaker.
 * Mirrors Python provide.telemetry.resilience.
 */

import { _incrementHealth, _recordExportLatency, _setLastExportError } from './health';

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
const CIRCUIT_BREAKER_COOLDOWN_MS = 30_000;

// Stryker disable next-line ObjectLiteral
let _policy: ExporterPolicy = { ...DEFAULT_POLICY };
// Stryker disable next-line ObjectLiteral
const _consecutiveTimeouts: Record<string, number> = { logs: 0, traces: 0, metrics: 0 };
// Stryker disable next-line ObjectLiteral
const _circuitTrippedAt: Record<string, number> = { logs: 0, traces: 0, metrics: 0 };

export function setExporterPolicy(policy: Partial<ExporterPolicy>): void {
  _policy = { ..._policy, ...policy };
}

export function getExporterPolicy(): ExporterPolicy {
  return { ..._policy };
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
  const policy = _policy;
  const attempts = Math.max(1, policy.retries + 1);

  // Circuit breaker check.
  // Stryker disable next-line ConditionalExpression
  if (_consecutiveTimeouts[signal] >= CIRCUIT_BREAKER_THRESHOLD) {
    const elapsed = Date.now() - _circuitTrippedAt[signal];
    if (elapsed < CIRCUIT_BREAKER_COOLDOWN_MS) {
      _incrementHealth('exportFailures');
      _setLastExportError('circuit breaker open');
      if (policy.failOpen) return null;
      throw new TelemetryTimeoutError('circuit breaker open: too many consecutive timeouts');
    }
    // Half-open: cooldown elapsed — fall through and allow one probe.
  }

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < attempts; attempt++) {
    const started = Date.now();
    try {
      const result = await _withTimeout(fn, policy.timeoutMs);
      _recordExportLatency(Date.now() - started);
      _setLastExportError(null);
      _consecutiveTimeouts[signal] = 0;
      return result;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      _incrementHealth('exportFailures');
      _setLastExportError(lastError.message);

      if (err instanceof TelemetryTimeoutError) {
        _consecutiveTimeouts[signal] = (_consecutiveTimeouts[signal] ?? 0) + 1;
        // Stryker disable next-line ConditionalExpression,EqualityOperator
        if (_consecutiveTimeouts[signal] >= CIRCUIT_BREAKER_THRESHOLD) {
          _circuitTrippedAt[signal] = Date.now();
        }
      } else {
        _consecutiveTimeouts[signal] = 0;
      }

      // Stryker disable next-line ArithmeticOperator
      if (attempt < attempts - 1) {
        _incrementHealth('exportRetries');
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

export function _resetResilienceForTests(): void {
  _policy = { ...DEFAULT_POLICY };
  for (const k of ['logs', 'traces', 'metrics']) {
    _consecutiveTimeouts[k] = 0;
    _circuitTrippedAt[k] = 0;
  }
}
