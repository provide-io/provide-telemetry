// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { validateOtlpEndpoint } from '../src/endpoint';

describe('validateOtlpEndpoint', () => {
  it('accepts valid http endpoint', () => {
    expect(validateOtlpEndpoint('http://localhost:4318')).toBe('http://localhost:4318');
  });
  it('accepts valid https endpoint', () => {
    expect(validateOtlpEndpoint('https://collector.example.com')).toBe(
      'https://collector.example.com',
    );
  });
  it('accepts endpoint with path', () => {
    expect(validateOtlpEndpoint('http://host:4318/v1/traces')).toBe('http://host:4318/v1/traces');
  });
  it('accepts endpoint without port', () => {
    expect(validateOtlpEndpoint('http://host/v1/traces')).toBe('http://host/v1/traces');
  });
  it('rejects missing scheme', () => {
    expect(() => validateOtlpEndpoint('host:4318')).toThrow(/invalid OTLP endpoint/);
  });
  it('rejects ftp scheme', () => {
    expect(() => validateOtlpEndpoint('ftp://host:4318')).toThrow(/invalid OTLP endpoint/);
  });
  it('rejects empty string', () => {
    expect(() => validateOtlpEndpoint('')).toThrow(/invalid OTLP endpoint/);
  });
  it('rejects non-numeric port', () => {
    expect(() => validateOtlpEndpoint('http://host:bad')).toThrow(/invalid OTLP endpoint/);
  });
  it('rejects empty port', () => {
    expect(() => validateOtlpEndpoint('http://host:')).toThrow(/invalid OTLP endpoint/);
  });
});
