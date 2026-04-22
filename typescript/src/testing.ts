// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Test utilities — reset all telemetry state between tests.
 * Mirrors Python provide.telemetry.testing.
 */

import { context, metrics, trace } from '@opentelemetry/api';
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
import { _resetOtelLogProviderForTests } from './otel-logs';
import { _resetTraceContext } from './tracing';
import { _resetRuntimeForTests } from './runtime';

function resetInstalledOtelGlobalsForTests(): void {
  trace.disable();
  metrics.disable();
  context.disable();
}

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
  resetInstalledOtelGlobalsForTests();
  _resetRootLogger();
  _resetOtelLogProviderForTests();
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
