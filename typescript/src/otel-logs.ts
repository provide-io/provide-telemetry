// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/* Stryker disable all -- dynamic import('...' as string) prevents Stryker's V8 perTest
   coverage from attributing any coverage to specific tests; all mutations in this file
   show covered:0 even though integration tests exercise every branch. */

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

/**
 * Construct an OTLPLogExporter + LoggerProvider and register it globally.
 * Returns a ShutdownableProvider so the caller can flush/shutdown it.
 * Throws if any peer dep is missing (caught by the caller in otel.ts).
 */
export async function setupOtelLogProvider(cfg: TelemetryConfig): Promise<ShutdownableProvider> {
  const headers = cfg.otlpHeaders ?? {};
  const endpoint = cfg.otlpEndpoint ?? 'http://localhost:4318';

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

  const logExporter = new OTLPLogExporter({ url: `${endpoint}/v1/logs`, headers });
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
  const body = String(o['msg'] ?? o['event'] ?? '');
  const severityNumber = SEVERITY_MAP[level] ?? DEFAULT_SEVERITY;
  const severityText = SEVERITY_TEXT[level] ?? 'INFO';

  // Build attributes: everything except the pino-internal fields already
  // represented by body / severity / timestamp.
  const SKIP = new Set(['msg', 'level', 'time', 'v']);
  const attributes: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (!SKIP.has(k) && v !== undefined) attributes[k] = v;
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
