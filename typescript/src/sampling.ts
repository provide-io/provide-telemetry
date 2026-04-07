// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Runtime sampling policy — mirrors Python provide.telemetry.sampling.
 */

import { ConfigurationError } from './exceptions';
import { _droppedField, _emittedField, _incrementHealth } from './health';

export interface SamplingPolicy {
  defaultRate: number;
  overrides?: Record<string, number>;
}

const DEFAULT_POLICY: SamplingPolicy = { defaultRate: 1.0 };
let _policies: Record<string, SamplingPolicy> = {};

const VALID_SIGNALS = new Set(['logs', 'traces', 'metrics']);

function _validateSignal(signal: string): void {
  if (!VALID_SIGNALS.has(signal)) {
    throw new ConfigurationError(
      `unknown signal "${signal}", expected one of [logs, metrics, traces]`,
    );
  }
}

function _clamp(rate: number): number {
  return Math.max(0, Math.min(1, rate));
}

export function setSamplingPolicy(signal: string, policy: SamplingPolicy): void {
  _validateSignal(signal);
  _policies[signal] = {
    defaultRate: _clamp(policy.defaultRate),
    overrides: policy.overrides
      ? Object.fromEntries(Object.entries(policy.overrides).map(([k, v]) => [k, _clamp(v)]))
      : undefined,
  };
}

export function getSamplingPolicy(signal: string): SamplingPolicy {
  _validateSignal(signal);
  const _policy = _policies[signal] ?? DEFAULT_POLICY;
  return {
    defaultRate: _policy.defaultRate,
    overrides: _policy.overrides ? { ..._policy.overrides } : undefined,
  };
}

export function shouldSample(signal: string, key?: string): boolean {
  _validateSignal(signal);
  const _policy = _policies[signal] ?? DEFAULT_POLICY;
  const overrides = _policy.overrides;
  // Only consult the override map when an explicit non-null key is provided.
  // Using `key ?? signal` would cause any override keyed by signal name (e.g. "logs")
  // to silently apply to all unkeyed shouldSample("logs") calls — a shadow-override hazard.
  // Stryker disable next-line ConditionalExpression: equivalent mutant — `true && overrides && key in overrides` short-circuits identically to `key != null && ...` because null/undefined are never valid string keys in overrides
  const rate = key != null && overrides && key in overrides ? overrides[key] : _policy.defaultRate;
  const clamped = _clamp(rate);
  // Stryker disable next-line ConditionalExpression,EqualityOperator: equivalent mutant — Math.random() in [0,1) so boundary is not observable
  if (clamped <= 0) {
    _incrementHealth(_droppedField(signal));
    return false;
  }
  // Stryker disable next-line ConditionalExpression,EqualityOperator: equivalent mutant — Math.random() in [0,1) so boundary is not observable
  if (clamped >= 1) {
    _incrementHealth(_emittedField(signal));
    return true;
  }
  // Stryker disable next-line EqualityOperator: Math.random() is in [0,1) so < 1.0 and <= 1.0 are equivalent (random never equals 1.0)
  const sampled = Math.random() < clamped;
  _incrementHealth(sampled ? _emittedField(signal) : _droppedField(signal));
  return sampled;
}

export function _resetSamplingForTests(): void {
  _policies = {};
}
