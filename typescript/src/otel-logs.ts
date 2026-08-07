// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*
 * Peer-dep loading note: all @opentelemetry/* imports below go through
 * dynImportOtel() (src/otel-dynimport.ts) rather than a literal
 * `import('pkg')`. That keeps every OTel peer dep tree-shakeable for
 * bundler users who set otelEnabled:false, AND stops bundlers (esbuild,
 * webpack, rollup) from statically resolving the specifier and failing the
 * build when a consumer hasn't installed the optional peer dep.
 *
 * Mutation-testing note (mirrored in typescript/stryker.config.mjs): this
 * file is still excluded from Stryker's `mutate` array. Routing through
 * dynImportOtel() fixed the old V8-coverage-tracing blind spot, but doing
 * so surfaced pre-existing untested edge cases (attribute truncation
 * boundaries, resilient-exporter signal wiring) that keep the measured
 * score under the 95% break threshold — latent debt, tracked separately
 * from this change.
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

import type { TelemetryConfig } from './config.js';
import { getConfig } from './config.js';
import { validateOtlpEndpoint } from './endpoint.js';
import { hardenRecord } from './harden.js';
import { buildOtelResource } from './otel-resource.js';
import { dynImportOtel } from './otel-dynimport.js';
import { wrapResilientExporter } from './resilient-exporter.js';
import type { ShutdownableProvider } from './runtime.js';

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

function appendSignalPath(endpoint: string, signalPath: string): string {
  return `${endpoint.replace(/\/+$/, '')}${signalPath}`;
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

  const sdkLogs = await dynImportOtel('@opentelemetry/sdk-logs');
  const otlpLogs = await dynImportOtel('@opentelemetry/exporter-logs-otlp-http');
  const apiLogs = await dynImportOtel('@opentelemetry/api-logs');
  const res = await dynImportOtel('@opentelemetry/resources');

  const { LoggerProvider, BatchLogRecordProcessor } = sdkLogs;
  const { OTLPLogExporter } = otlpLogs;
  const { logs } = apiLogs;

  const logsEndpoint =
    normalizeEndpoint(cfg.otlpLogsEndpoint) ?? appendSignalPath(endpoint, '/v1/logs');
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
  // Options object, not a positional exporter: @opentelemetry/sdk-logs takes
  // `{ exporter }` here. Passing it positionally leaves `options.exporter`
  // undefined, and the processor then discards every record in silence — no
  // throw, no warning, and `providers.logs` still reports installed. That is
  // exactly how OTLP log export was dead while every other check stayed green.
  const processor = new BatchLogRecordProcessor({ exporter: logExporter });
  const provider = new LoggerProvider({
    resource: buildOtelResource(res, cfg),
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

  // — Security: recursive hardening —
  // Truncation and the attribute-count cap used to be applied here as two
  // top-level-only passes, so a nested object went to the exporter unbounded
  // and a cyclic one reached its serializer. hardenRecord applies the same
  // caps at every level, and collapses cycles and non-JSON composites.
  const cfg = getConfig();
  hardenRecord(attributes, {
    maxValueLength: cfg.securityMaxAttrValueLength,
    maxAttrCount: cfg.securityMaxAttrCount,
    maxDepth: cfg.piiMaxDepth,
  });

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
