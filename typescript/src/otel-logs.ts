// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*
 * Mutation-testing note (mirrored in typescript/stryker.config.mjs):
 *
 * This file is excluded from Stryker's `mutate` array because it uses
 * `await import('pkg' as string)` so Stryker's V8 perTest coverage
 * instrumentor cannot trace which test exercises which mutant — every mutant
 * reports covered:0 and is labelled "no coverage" rather than being killed.
 * Switching to static imports is out of scope: the dynamic pattern is the
 * load-bearing mechanism that keeps all OTel peer deps tree-shakeable for
 * bundler users who set otelEnabled:false.
 *
 * TRADEOFF: mutations in this file are not killed by unit tests.
 * The risk is accepted because:
 *   1. Integration tests in tests/integration/otel-providers-registration.test.ts
 *      exercise every branch of setupOtelLogProvider() with real OTel SDK
 *      objects, giving strong behavioural confidence.
 *   2. The emitLogRecord() function uses only static imports and is called
 *      from the Pino write-hook; its attribute-truncation and severity-mapping
 *      logic is exercised by the pipeline integration test suite.
 *   3. The resilience-policy mutations that matter most are covered at 100%
 *      in resilient-exporter.ts, which uses static imports.
 *
 * If a future Stryker version can track V8 coverage through dynamic imports,
 * remove the `!src/otel-logs.ts` exemption in stryker.config.mjs and add
 * targeted unit tests.
 */

/**
 * Optional OTEL SDK log wiring — activated when registerOtelProviders() runs.
 *
 * Peer deps required:
 *   @opentelemetry/sdk-logs                  — LoggerProvider, BatchLogRecordProcessor
 *   @opentelemetry/exporter-logs-otlp-http   — OTLPLogExporter
 *   @opentelemetry/api-logs                  — logs global, SeverityNumber
 *
 * Mirrors Python provide.telemetry.logger.core OTLPLogExporter wiring.
 */

import type { TelemetryConfig } from './config';
import { getConfig } from './config';
import { validateOtlpEndpoint } from './endpoint';
import { wrapResilientExporter } from './resilient-exporter';
import type { ShutdownableProvider } from './runtime';

/** Pino level number → OTel SeverityNumber (from @opentelemetry/api-logs). */
const SEVERITY_MAP: Record<number, number> = {
  10: 1, // TRACE
  20: 5, // DEBUG
  30: 9, // INFO
  40: 13, // WARN
  50: 17, // ERROR
  60: 21, // FATAL
};
const SEVERITY_TEXT: Record<number, string> = {
  10: 'TRACE',
  20: 'DEBUG',
  30: 'INFO',
  40: 'WARN',
  50: 'ERROR',
  60: 'FATAL',
};
const DEFAULT_SEVERITY = 9; // INFO

/** Internal singleton — set by setupOtelLogProvider, read by emitLogRecord. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _loggerProvider: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _otelLogger: any = null;

function normalizeEndpoint(endpoint: string | undefined): string | undefined {
  const trimmed = endpoint?.trim();
  return trimmed ? trimmed : undefined;
}

/**
 * Construct an OTLPLogExporter + LoggerProvider and register it globally.
 * Returns a ShutdownableProvider so the caller can flush/shutdown it.
 * Throws if any peer dep is missing (caught by the caller in otel.ts).
 */
export async function setupOtelLogProvider(cfg: TelemetryConfig): Promise<ShutdownableProvider> {
  const headers = cfg.otlpHeaders ?? {};
  const endpoint = normalizeEndpoint(cfg.otlpLogsEndpoint) ?? normalizeEndpoint(cfg.otlpEndpoint);
  if (!endpoint) {
    throw new Error('setupOtelLogProvider called without an OTLP log endpoint configured');
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const sdkLogs: any = await import('@opentelemetry/sdk-logs' as string);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const otlpLogs: any = await import('@opentelemetry/exporter-logs-otlp-http' as string);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const apiLogs: any = await import('@opentelemetry/api-logs' as string);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const res: any = await import('@opentelemetry/resources' as string);

  const { LoggerProvider, BatchLogRecordProcessor } = sdkLogs;
  const { OTLPLogExporter } = otlpLogs;
  const { logs } = apiLogs;
  const { resourceFromAttributes } = res;

  const logsEndpoint = normalizeEndpoint(cfg.otlpLogsEndpoint) ?? `${endpoint}/v1/logs`;
  validateOtlpEndpoint(logsEndpoint);
  const logsHeaders = cfg.otlpLogsHeaders ?? headers;
  const rawLogExporter = new OTLPLogExporter({
    url: logsEndpoint,
    headers: logsHeaders,
    // Fall back to 10s when the caller supplies a TelemetryConfig without the
    // field set (e.g. tests constructing partial configs). Production callers
    // always receive the DEFAULTS-merged config from setupTelemetry().
    timeoutMillis: cfg.exporterLogsTimeoutMs ?? 10000,
  });
  // Wrap so every batch export applies retry/timeout/circuit-breaker policy.
  const logExporter = wrapResilientExporter('logs', rawLogExporter);
  const processor = new BatchLogRecordProcessor(logExporter);
  const provider = new LoggerProvider({
    resource: resourceFromAttributes({
      'service.name': cfg.serviceName,
      'deployment.environment': cfg.environment,
      'service.version': cfg.version,
    }),
    processors: [processor],
  });

  logs.setGlobalLoggerProvider(provider);
  _loggerProvider = provider;
  _otelLogger = logs.getLogger('@provide-io/telemetry');

  return provider as ShutdownableProvider;
}

/**
 * Emit a pino log record to the OTel LoggerProvider.
 * Called from makeWriteHook() on every log line after enrichment and sanitization.
 * No-op when no provider is registered (graceful degradation).
 */
export function emitLogRecord(o: Record<string, unknown>): void {
  if (!_otelLogger) return;

  const level = (o['level'] as number) ?? 30;
  const body = String(o['message'] ?? o['event'] ?? '');
  const severityNumber = SEVERITY_MAP[level] ?? DEFAULT_SEVERITY;
  const severityText = SEVERITY_TEXT[level] ?? 'INFO';

  // Build attributes: everything except the pino-internal fields already
  // represented by body / severity / timestamp.
  const SKIP = new Set(['message', 'level', 'time', 'v']);
  const attributes: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (!SKIP.has(k) && v !== undefined) attributes[k] = v;
  }

  // — Security: truncate long attribute values —
  const cfg = getConfig();
  const maxLen = cfg.securityMaxAttrValueLength;
  for (const [k, v] of Object.entries(attributes)) {
    if (typeof v === 'string' && v.length > maxLen) {
      attributes[k] = v.slice(0, maxLen) + '...';
    }
  }

  // — Security: limit attribute count —
  const maxCount = cfg.securityMaxAttrCount;
  const keys = Object.keys(attributes);
  if (keys.length > maxCount) {
    for (const k of keys.slice(maxCount)) {
      delete attributes[k];
    }
  }

  // — Code attributes: map provide-telemetry fields to OTel semantic conventions —
  if (cfg.logCodeAttributes) {
    if (attributes['caller_file']) {
      attributes['code.filepath'] = attributes['caller_file'];
    }
    if (attributes['caller_line']) {
      attributes['code.lineno'] = attributes['caller_line'];
    }
    if (attributes['name']) {
      attributes['code.namespace'] = attributes['name'];
    }
  }

  _otelLogger.emit({
    body,
    severityNumber,
    severityText,
    attributes,
    timestamp: typeof o['time'] === 'number' ? o['time'] : Date.now(),
  });
}

/** Exposed for tests and resetTelemetryState(). */
export function _resetOtelLogProviderForTests(): void {
  _loggerProvider = null;
  _otelLogger = null;
}

/** Exposed for integration tests to inspect state. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function _getOtelLogProvider(): any {
  return _loggerProvider;
}
