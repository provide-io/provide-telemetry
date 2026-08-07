// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
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
  setupTelemetryAsync,
  applyConfigPolicies,
  getConfig,
  configFromEnv,
  parseOtlpHeaders,
  redactConfig,
  version,
  __version__,
} from './config.js';
export type { TelemetryConfig, LoggingOverrides, RuntimeOverrides } from './config.js';

// Logger
export { getLogger, logger } from './logger.js';
export type { Logger } from './logger.js';

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
} from './context.js';

// Error fingerprinting (mirrors Python add_error_fingerprint processor)
export { computeErrorFingerprint } from './fingerprint.js';

// Pretty ANSI renderer (mirrors Python PrettyRenderer)
export { formatPretty, supportsColor } from './pretty.js';

// Metrics (mirrors Python counter / gauge / histogram)
export {
  counter,
  gauge,
  histogram,
  getMeter,
  CounterInstrument,
  GaugeInstrument,
  HistogramInstrument,
} from './metrics.js';
export type { Counter, Histogram, Meter, MetricOptions, UpDownCounter } from './metrics.js';

// Tracing (mirrors Python @trace decorator)
export {
  withTrace,
  traceDecorator as trace,
  getActiveTraceIds,
  getTracer,
  tracer,
  setTraceContext,
  getTraceContext,
} from './tracing.js';

// OTel SDK wiring (call after setupTelemetry to activate exporters)
export { registerOtelProviders } from './otel.js';

// PII sanitization utilities
export { harden, hardenRecord } from './harden.js';
export type { HardenOptions } from './harden.js';
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
} from './pii.js';
export type { MaskMode, PIIRule, SanitizePayloadOptions, SecretPattern } from './pii.js';

// Exceptions
export { TelemetryError, ConfigurationError } from './exceptions.js';

// Health
export { getHealthSnapshot, setSetupError } from './health.js';
export type { HealthSnapshot } from './health.js';

// Backpressure
export { setQueuePolicy, getQueuePolicy, tryAcquire, release } from './backpressure.js';
export type { QueuePolicy, QueueTicket } from './backpressure.js';

// Cardinality
export {
  OVERFLOW_VALUE,
  registerCardinalityLimit,
  getCardinalityLimits,
  clearCardinalityLimits,
  guardAttributes,
} from './cardinality.js';
export type { CardinalityLimit } from './cardinality.js';

// Sampling
export { setSamplingPolicy, getSamplingPolicy, shouldSample } from './sampling.js';
export type { SamplingPolicy } from './sampling.js';

// Resilience
export {
  setExporterPolicy,
  getExporterPolicy,
  runWithResilience,
  getCircuitState,
  TelemetryTimeoutError,
} from './resilience.js';
export type { ExporterPolicy, CircuitState } from './resilience.js';

// Schema
export {
  EventSchemaError,
  event,
  eventName,
  getStrictSchema,
  setStrictSchema,
  validateEventName,
  validateRequiredKeys,
} from './schema.js';
export type { EventRecord } from './schema.js';

// SLO
export { recordRedMetrics, recordUseMetrics, classifyError } from './slo.js';
export type { ErrorClassification } from './slo.js';

// Propagation
export {
  extractW3cContext,
  parseBaggage,
  bindPropagationContext,
  clearPropagationContext,
  getActivePropagationContext,
  awaitPropagationInit,
  isPropagationInitDone,
  isFallbackMode,
} from './propagation.js';
export type { PropagationContext } from './propagation.js';

// Runtime reconfiguration
export {
  getRuntimeConfig,
  getRuntimeStatus,
  updateRuntimeConfig,
  reloadRuntimeFromEnv,
  reconfigureTelemetry,
  ProviderMode,
  RuntimeState,
  TelemetryRuntime,
} from './runtime.js';
export type {
  RuntimeStatus,
  SignalFlushResult,
  FlushResult,
  ReconfigureResult,
  telemetryRuntime,
  telemetryConfig,
  runtimeStatus,
  runtimeState,
  providerMode,
  signalFlushResult,
  flushResult,
  reconfigureResult,
} from './runtime.js';
export { ProviderImmutableError } from './exceptions.js';
export type { providerImmutableError } from './exceptions.js';

// Test utilities
export { resetTelemetryState, resetTraceContext, telemetryTestPlugin } from './testing.js';

// Governance modules
export type { ConsentLevel } from './consent.js';
export {
  setConsentLevel,
  getConsentLevel,
  shouldAllow,
  loadConsentFromEnv,
  resetConsentForTests,
} from './consent.js';

// Governance modules
export type { DataClass, ClassificationRule, ClassificationPolicy } from './classification.js';
export {
  classifyKey,
  registerClassificationRule,
  registerClassificationRules,
  setClassificationPolicy,
  getClassificationPolicy,
  resetClassificationForTests,
} from './classification.js';

// Governance modules
export type { EnableReceiptsOptions, ReceiptSink, RedactionReceipt } from './receipts.js';
export {
  canonicalJson,
  emitReceipt,
  enableReceipts,
  getEmittedReceiptsForTests,
  MissingReceiptSinkError,
  receiptPayload,
  resetReceiptsForTests,
  signReceipt,
  TEST_RECEIPT_CAPACITY,
  TestReceiptCollector,
} from './receipts.js';

// Shutdown
export { flushTelemetry, shutdownTelemetry } from './shutdown.js';
