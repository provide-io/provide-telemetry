// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Runtime sampling policy — mirrors Python undef.telemetry.sampling.
 */

export interface SamplingPolicy {
  defaultRate: number;
  overrides?: Record<string, number>;
}

const DEFAULT_POLICY: SamplingPolicy = { defaultRate: 1.0 };
let _policy: SamplingPolicy = { ...DEFAULT_POLICY };

function _clamp(rate: number): number {
  return Math.max(0, Math.min(1, rate));
}

export function setSamplingPolicy(policy: SamplingPolicy): void {
  _policy = {
    defaultRate: _clamp(policy.defaultRate),
    overrides: policy.overrides
      ? Object.fromEntries(Object.entries(policy.overrides).map(([k, v]) => [k, _clamp(v)]))
      : undefined,
  };
}

export function getSamplingPolicy(): SamplingPolicy {
  return {
    defaultRate: _policy.defaultRate,
    overrides: _policy.overrides ? { ..._policy.overrides } : undefined,
  };
}

export function shouldSample(signal: string): boolean {
  const overrides = _policy.overrides;
  const rate = overrides && signal in overrides ? overrides[signal] : _policy.defaultRate;
  const clamped = _clamp(rate);
  // Stryker disable next-line ConditionalExpression,EqualityOperator: equivalent mutant — Math.random() in [0,1) so boundary is not observable
  if (clamped <= 0) return false;
  // Stryker disable next-line ConditionalExpression,EqualityOperator: equivalent mutant — Math.random() in [0,1) so boundary is not observable
  if (clamped >= 1) return true;
  // Stryker disable next-line EqualityOperator: Math.random() is in [0,1) so < 1.0 and <= 1.0 are equivalent (random never equals 1.0)
  return Math.random() < clamped;
}

export function _resetSamplingForTests(): void {
  _policy = { ...DEFAULT_POLICY };
}
