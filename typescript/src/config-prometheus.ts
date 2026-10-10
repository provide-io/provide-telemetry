// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Parsing and validation for the Prometheus metrics settings.
 *
 * See the prometheus_metrics section of spec/telemetry-api.yaml. Invalid values
 * throw ConfigurationError, as invalid booleans and rates already do. Mirrors
 * Python provide.telemetry._config_prometheus.
 */

import { ConfigurationError } from './exceptions.js';

export const EXPORTER_OTLP = 'otlp';
export const EXPORTER_PROMETHEUS = 'prometheus';
export const EXPORTER_NONE = 'none';
export const LISTEN_VALUES = ['false', 'true', 'auto'] as const;
export const MAX_PORT = 65535;
export const DEFAULT_HOST = '127.0.0.1';
export const DEFAULT_PORT = 9464;
export const DEFAULT_PATH = '/metrics';
export const TRANSLATION_STRATEGIES = [
  'UnderscoreEscapingWithSuffixes',
  'UnderscoreEscapingWithoutSuffixes',
  'NoUTF8EscapingWithSuffixes',
  'NoTranslation',
] as const;
export const DEFAULT_TRANSLATION = TRANSLATION_STRATEGIES[0];

export type PrometheusListen = (typeof LISTEN_VALUES)[number];
export type TranslationStrategy = (typeof TRANSLATION_STRATEGIES)[number];

/** The config fields these helpers read; a subset of TelemetryConfig. */
export interface PrometheusSettings {
  metricsEnabled: boolean;
  metricsExporters: string[];
  prometheusListen: string;
  prometheusHost: string;
  prometheusPort: number;
  prometheusPath: string;
  prometheusTranslation: string;
  prometheusWebConfig: string;
}

/**
 * Parse OTEL_METRICS_EXPORTER.
 *
 * Entries are split on commas, trimmed and lowercased; empty ones are dropped.
 * Empty input means ['otlp']. 'none' alone means no exporters and may not be
 * combined with another.
 */
export function parseMetricsExporters(raw: string | undefined): string[] {
  const names = (raw ?? '')
    .split(',')
    .map((part) => part.trim().toLowerCase())
    .filter((part) => part !== '');
  const unknown = names.find(
    (n) => n !== EXPORTER_OTLP && n !== EXPORTER_PROMETHEUS && n !== EXPORTER_NONE,
  );
  if (unknown !== undefined) {
    throw new ConfigurationError(
      `OTEL_METRICS_EXPORTER: unknown exporter ${JSON.stringify(unknown)}`,
    );
  }
  const exporters = names.filter((n) => n !== EXPORTER_NONE);
  if (names.includes(EXPORTER_NONE)) {
    if (exporters.length > 0) {
      throw new ConfigurationError(
        'OTEL_METRICS_EXPORTER: none cannot be combined with other exporters',
      );
    }
    return [];
  }
  return exporters.length > 0 ? exporters : [EXPORTER_OTLP];
}

/** Reject an exporter list built in code with a name the env parser would refuse. */
export function validateExporters(exporters: string[]): void {
  const unknown = exporters.find((e) => e !== EXPORTER_OTLP && e !== EXPORTER_PROMETHEUS);
  if (unknown !== undefined) {
    throw new ConfigurationError(`metricsExporters: unknown exporter ${JSON.stringify(unknown)}`);
  }
}

/** Parse OTEL_EXPORTER_PROMETHEUS_PORT: an integer in 0-65535, 0 meaning any free port. */
export function parsePort(raw: string | undefined): number {
  const value = (raw ?? '').trim();
  if (value === '') return DEFAULT_PORT;
  if (!/^[+-]?\d+$/.test(value)) {
    throw new ConfigurationError(
      `OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got ${JSON.stringify(value)}`,
    );
  }
  const port = Number(value);
  validatePort(port);
  return port;
}

export function validatePort(port: number): void {
  if (!Number.isInteger(port) || port < 0 || port > MAX_PORT) {
    throw new ConfigurationError(
      `OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got ${String(port)}`,
    );
  }
}

export function validateListen(listen: string): void {
  if (!(LISTEN_VALUES as readonly string[]).includes(listen)) {
    throw new ConfigurationError(
      `PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got ${JSON.stringify(listen)}`,
    );
  }
}

export function validatePath(path: string): void {
  if (!path.startsWith('/') || path.includes('?') || path.includes('#')) {
    throw new ConfigurationError(
      `PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got ${JSON.stringify(path)}`,
    );
  }
}

export function validateTranslation(translation: string): void {
  if (!(TRANSLATION_STRATEGIES as readonly string[]).includes(translation)) {
    throw new ConfigurationError(
      `PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy ${JSON.stringify(translation)}`,
    );
  }
}

/** Validate every Prometheus field of a candidate config. */
export function validatePrometheusSettings(cfg: PrometheusSettings): void {
  validateExporters(cfg.metricsExporters);
  validateListen(cfg.prometheusListen);
  validatePort(cfg.prometheusPort);
  validatePath(cfg.prometheusPath);
  validateTranslation(cfg.prometheusTranslation);
}

/** A trimmed string setting; empty or unset means the default. */
export function envStr(raw: string | undefined, fallback: string): string {
  const value = (raw ?? '').trim();
  return value === '' ? fallback : value;
}

/** Whether the standalone Prometheus listener should run. */
export function prometheusListenerEnabled(cfg: PrometheusSettings): boolean {
  if (!cfg.metricsEnabled) return false;
  if (cfg.prometheusListen === 'true') return true;
  return cfg.prometheusListen === 'auto' && cfg.metricsExporters.includes(EXPORTER_PROMETHEUS);
}

/** Whether the Prometheus pull reader is attached; asking for the listener implies it. */
export function prometheusReaderEnabled(cfg: PrometheusSettings): boolean {
  return (
    cfg.metricsEnabled &&
    (cfg.metricsExporters.includes(EXPORTER_PROMETHEUS) || prometheusListenerEnabled(cfg))
  );
}

/** Whether the OTLP metrics reader is selected (it still needs an endpoint). */
export function otlpMetricsReaderEnabled(cfg: PrometheusSettings): boolean {
  return cfg.metricsEnabled && cfg.metricsExporters.includes(EXPORTER_OTLP);
}
