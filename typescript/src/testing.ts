// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Test utilities — reset all telemetry state between tests.
 * Mirrors Python provide.telemetry.testing.
 */

import { _resetConfig } from './config';
import { _resetContext } from './context';
import { _resetHealthForTests } from './health';
import { _resetBackpressureForTests } from './backpressure';
import { _resetCardinalityForTests } from './cardinality';
import { _resetSamplingForTests } from './sampling';
import { _resetResilienceForTests } from './resilience';
import { resetPiiRulesForTests } from './pii';
import { _resetSloForTests } from './slo';
import { _resetPropagationForTests } from './propagation';
import { _resetRootLogger } from './logger';
import { _resetTraceContext } from './tracing';
import { _resetRuntimeForTests } from './runtime';

/** Reset all telemetry state (config, context, PII rules, health, queues, sampling, resilience, SLO). */
export function resetTelemetryState(): void {
  _resetConfig();
  _resetContext();
  _resetHealthForTests();
  _resetBackpressureForTests();
  _resetCardinalityForTests();
  _resetSamplingForTests();
  _resetResilienceForTests();
  resetPiiRulesForTests();
  _resetSloForTests();
  _resetPropagationForTests();
  _resetRootLogger();
  _resetRuntimeForTests();
}

/** Clear manual trace context (traceId / spanId set via setTraceContext). */
export function resetTraceContext(): void {
  _resetTraceContext();
}

/** Vitest plugin for automatic per-test telemetry isolation. */
export const telemetryTestPlugin = {
  beforeEach(): void {
    resetTelemetryState();
    resetTraceContext();
  },
  afterEach(): void {
    resetTelemetryState();
    resetTraceContext();
  },
};
