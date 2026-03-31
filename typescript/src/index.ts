// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * @provide-io/telemetry — TypeScript structured logging + OTEL
 *
 * Feature parity with the Python provide.telemetry package.
 *
 * Quick start:
 *   import { setupTelemetry, getLogger, bindContext } from '@provide-io/telemetry';
 *
 *   setupTelemetry({ serviceName: 'my-app', logLevel: 'debug' });
 *   const log = getLogger('api');
 *   log.info({ event: 'request_ok', method: 'GET', path: '/api/v1/users', status: 200 });
 */

// Config + setup
export {
  setupTelemetry,
  applyConfigPolicies,
  getConfig,
  configFromEnv,
  parseOtlpHeaders,
  redactConfig,
  version,
  __version__,
} from './config';
export type { TelemetryConfig, RuntimeOverrides } from './config';

// Logger
export { getLogger, logger } from './logger';
export type { Logger } from './logger';

// Context binding (mirrors Python bind_context / unbind_context / clear_context)
export {
  bindContext,
  unbindContext,
  clearContext,
  getContext,
  runWithContext,
  bindSessionContext,
  getSessionId,
  clearSessionContext,
} from './context';

// Error fingerprinting (mirrors Python add_error_fingerprint processor)
export { computeErrorFingerprint } from './fingerprint';

// Metrics (mirrors Python counter / gauge / histogram)
export {
  counter,
  gauge,
  histogram,
  getMeter,
  CounterInstrument,
  GaugeInstrument,
  HistogramInstrument,
} from './metrics';
export type { Counter, Histogram, Meter, MetricOptions, UpDownCounter } from './metrics';

// Tracing (mirrors Python @trace decorator)
export {
  withTrace,
  traceDecorator as trace,
  getActiveTraceIds,
  getTracer,
  tracer,
  setTraceContext,
  getTraceContext,
} from './tracing';

// Optional OTEL SDK wiring (call after setupTelemetry to activate exporters)
export { registerOtelProviders } from './otel';

// PII sanitization utilities
export {
  sanitize,
  DEFAULT_SANITIZE_FIELDS,
  sanitizePayload,
  registerPiiRule,
  getPiiRules,
  replacePiiRules,
  resetPiiRulesForTests,
  registerSecretPattern,
  getSecretPatterns,
  resetSecretPatternsForTests,
} from './pii';
export type { MaskMode, PIIRule, SanitizePayloadOptions, SecretPattern } from './pii';

// Exceptions
export { TelemetryError, ConfigurationError } from './exceptions';

// Health
export { getHealthSnapshot, setSetupError } from './health';
export type { HealthSnapshot } from './health';

// Backpressure
export { setQueuePolicy, getQueuePolicy, tryAcquire, release } from './backpressure';
export type { QueuePolicy, QueueTicket } from './backpressure';

// Cardinality
export {
  OVERFLOW_VALUE,
  registerCardinalityLimit,
  getCardinalityLimits,
  clearCardinalityLimits,
  guardAttributes,
} from './cardinality';
export type { CardinalityLimit } from './cardinality';

// Sampling
export { setSamplingPolicy, getSamplingPolicy, shouldSample } from './sampling';
export type { SamplingPolicy } from './sampling';

// Resilience
export {
  setExporterPolicy,
  getExporterPolicy,
  runWithResilience,
  TelemetryTimeoutError,
} from './resilience';
export type { ExporterPolicy } from './resilience';

// Schema
export {
  EventSchemaError,
  event,
  eventName,
  getStrictSchema,
  setStrictSchema,
  validateEventName,
  validateRequiredKeys,
} from './schema';
export type { EventRecord } from './schema';

// SLO
export { recordRedMetrics, recordUseMetrics, classifyError } from './slo';
export type { ErrorClassification } from './slo';

// Propagation
export {
  extractW3cContext,
  parseBaggage,
  bindPropagationContext,
  clearPropagationContext,
  getActivePropagationContext,
} from './propagation';
export type { PropagationContext } from './propagation';

// Runtime reconfiguration
export {
  getRuntimeConfig,
  updateRuntimeConfig,
  reloadRuntimeFromEnv,
  reconfigureTelemetry,
} from './runtime';

// Test utilities
export { resetTelemetryState, resetTraceContext, telemetryTestPlugin } from './testing';

// Shutdown
export { shutdownTelemetry } from './shutdown';
