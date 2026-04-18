// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { redactConfig } from '../src/config';
import type { TelemetryConfig } from '../src/config';

describe('redactConfig', () => {
  it('masks OTLP header values (long value)', () => {
    const cfg = {
      otlpHeaders: { Authorization: 'Bearer super-secret-token' }, // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('super-secret-token');
    const headers = result.otlpHeaders as Record<string, string>;
    expect(headers.Authorization).toBe('Bear****');
  });

  it('masks OTLP header values (short value — fully masked)', () => {
    const cfg = {
      otlpHeaders: { 'X-Key': 'short' },
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('short');
    const headers = result.otlpHeaders as Record<string, string>;
    expect(headers['X-Key']).toBe('****');
  });

  it('masks endpoint credentials in URL userinfo', () => {
    const cfg = {
      otlpEndpoint: 'https://user:p4ssw0rd@otel.example.com', // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('p4ssw0rd');
    expect(result.otlpEndpoint as string).toContain('****');
    expect(result.otlpEndpoint as string).toContain('user');
    expect(result.otlpEndpoint as string).toContain('otel.example.com');
  });

  it('leaves endpoint unchanged when no password present', () => {
    const cfg = {
      otlpEndpoint: 'https://otel.example.com/v1/traces',
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(result.otlpEndpoint).toBe('https://otel.example.com/v1/traces');
  });

  it('leaves endpoint unchanged when it is not a valid URL', () => {
    const cfg = {
      otlpEndpoint: 'not-a-url',
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(result.otlpEndpoint).toBe('not-a-url');
  });

  it('is safe with no secrets', () => {
    const cfg = { serviceName: 'my-app' } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(result.serviceName).toBe('my-app');
  });

  it('does not modify otlpHeaders when the field is absent', () => {
    const cfg = { serviceName: 'svc' } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect('otlpHeaders' in result).toBe(false);
  });

  it('does not modify otlpEndpoint when the field is absent', () => {
    const cfg = { serviceName: 'svc' } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    // otlpEndpoint is optional; when not in cfg it should not appear in result
    expect(result.otlpEndpoint).toBeUndefined();
  });

  it('does not modify empty otlpHeaders object', () => {
    const cfg = {
      otlpHeaders: {},
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    // empty headers object passes through unchanged (no keys to mask)
    expect(result.otlpHeaders).toEqual({});
  });

  it('masks exactly 8-char header value — shows first 4', () => {
    const cfg = {
      otlpHeaders: { 'X-Key': '12345678' },
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    const headers = result.otlpHeaders as Record<string, string>;
    expect(headers['X-Key']).toBe('1234****');
  });

  it('masks per-signal logs headers', () => {
    const cfg = {
      otlpLogsHeaders: { Authorization: 'Bearer secret-logs-token' }, // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('secret-logs-token');
    const headers = result.otlpLogsHeaders as Record<string, string>;
    expect(headers.Authorization).toBe('Bear****');
  });

  it('masks per-signal traces headers', () => {
    const cfg = {
      otlpTracesHeaders: { 'X-Api-Key': 'traces-secret-key' }, // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('traces-secret-key');
    const headers = result.otlpTracesHeaders as Record<string, string>;
    expect(headers['X-Api-Key']).toBe('trac****');
  });

  it('masks per-signal metrics headers', () => {
    const cfg = {
      otlpMetricsHeaders: { Authorization: 'Bearer metrics-token' }, // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('metrics-token');
    const headers = result.otlpMetricsHeaders as Record<string, string>;
    expect(headers.Authorization).toBe('Bear****');
  });

  it('does not mask per-signal headers when field is absent', () => {
    const cfg = { serviceName: 'svc' } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(result.otlpLogsHeaders).toBeUndefined();
    expect(result.otlpTracesHeaders).toBeUndefined();
    expect(result.otlpMetricsHeaders).toBeUndefined();
  });

  it('does not mask per-signal headers when field is empty object', () => {
    const cfg = {
      otlpLogsHeaders: {},
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(result.otlpLogsHeaders).toEqual({});
  });

  it('masks per-signal logs endpoint credentials', () => {
    const cfg = {
      otlpLogsEndpoint: 'https://user:p4ssw0rd@logs.example.com', // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('p4ssw0rd');
    expect(result.otlpLogsEndpoint as string).toContain('****');
  });

  it('masks per-signal traces endpoint credentials', () => {
    const cfg = {
      otlpTracesEndpoint: 'https://user:p4ssw0rd@traces.example.com', // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('p4ssw0rd');
    expect(result.otlpTracesEndpoint as string).toContain('****');
  });

  it('masks per-signal metrics endpoint credentials', () => {
    const cfg = {
      otlpMetricsEndpoint: 'https://user:p4ssw0rd@metrics.example.com', // pragma: allowlist secret
    } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(JSON.stringify(result)).not.toContain('p4ssw0rd');
    expect(result.otlpMetricsEndpoint as string).toContain('****');
  });

  it('does not mask per-signal endpoints when fields are absent', () => {
    const cfg = { serviceName: 'svc' } as Partial<TelemetryConfig> as TelemetryConfig;
    const result = redactConfig(cfg);
    expect(result.otlpLogsEndpoint).toBeUndefined();
    expect(result.otlpTracesEndpoint).toBeUndefined();
    expect(result.otlpMetricsEndpoint).toBeUndefined();
  });
});
