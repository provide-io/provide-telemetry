// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Test utilities — reset all telemetry state between tests.
 * Mirrors Python provide.telemetry.testing.
 */

import { context, metrics, trace } from '@opentelemetry/api';
import { _resetConfig } from './config.js';
import { _resetContext } from './context.js';
import { _resetHealthForTests } from './health.js';
import { _resetBackpressureForTests } from './backpressure.js';
import { _resetCardinalityForTests } from './cardinality.js';
import { _resetSamplingForTests } from './sampling.js';
import { _resetResilienceForTests } from './resilience.js';
import { resetPiiRulesForTests } from './pii.js';
import { _resetSloForTests } from './slo.js';
import { _resetPropagationForTests } from './propagation.js';
import { _resetRootLogger } from './logger.js';
import { _resetReservedWarningsForTests } from './reserved-fields.js';
import { _resetOtelLogProviderForTests } from './otel-logs.js';
import { _resetTraceContext } from './tracing.js';
import { _resetRuntimeForTests } from './runtime.js';
import { _resetPullForTests } from './prom-pull.js';
import { _resetExporterWarningsForTests } from './config-prometheus.js';
import { _resetTlsChecksForTests } from './otlp-tls.js';

function resetInstalledOtelGlobalsForTests(): void {
  trace.disable();
  metrics.disable();
  context.disable();
}

/**
 * Reset all telemetry state (config, context, PII rules, health, queues, sampling,
 * resilience, SLO, and what setup last reported as setupError).
 */
export function resetTelemetryState(): void {
  _resetConfig();
  _resetContext();
  _resetHealthForTests();
  _resetReservedWarningsForTests();
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
  _resetPullForTests();
  _resetExporterWarningsForTests();
  _resetTlsChecksForTests();
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
