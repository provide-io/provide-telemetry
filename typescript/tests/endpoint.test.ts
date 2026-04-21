// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import YAML from 'yaml';
import { validateOtlpEndpoint } from '../src/endpoint';
import { ConfigurationError } from '../src/exceptions';

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

  // Boundary tests — kill EqualityOperator mutants on the port range check.
  it('accepts port 1 (lowest valid)', () => {
    expect(validateOtlpEndpoint('http://host:1')).toBe('http://host:1');
  });
  it('accepts port 65535 (highest valid)', () => {
    expect(validateOtlpEndpoint('http://host:65535')).toBe('http://host:65535');
  });
  it('rejects port 0 as out of range', () => {
    // URL constructor accepts :0 (parses to port="0"); our range check catches it.
    expect(() => validateOtlpEndpoint('http://host:0')).toThrow(/invalid OTLP endpoint port/);
  });
  it('rejects port above 65535 (URL constructor already throws)', () => {
    // URL() rejects :65536 itself → catch block reports generic "invalid OTLP endpoint".
    expect(() => validateOtlpEndpoint('http://host:65536')).toThrow(/invalid OTLP endpoint/);
  });

  // Error type + message pins — kill StringLiteral and BlockStatement mutants.
  it('throws ConfigurationError (not generic Error) with specific message for invalid URL', () => {
    expect(() => validateOtlpEndpoint('not-a-url')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('not-a-url')).toThrow(/invalid OTLP endpoint/);
  });
  it('throws ConfigurationError with specific message for wrong scheme', () => {
    expect(() => validateOtlpEndpoint('ftp://host:4318')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('ftp://host:4318')).toThrow(/invalid OTLP endpoint/);
  });
  it('throws ConfigurationError with port-specific message for port=0 (URL accepts, range rejects)', () => {
    expect(() => validateOtlpEndpoint('http://host:0')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('http://host:0')).toThrow(/invalid OTLP endpoint port/);
  });
  it('throws ConfigurationError with generic message for empty explicit port', () => {
    expect(() => validateOtlpEndpoint('http://host:')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('http://host:')).toThrow(/invalid OTLP endpoint/);
  });
});

// ---------------------------------------------------------------------------
// Fixture-driven parity tests — shared across all language implementations
// ---------------------------------------------------------------------------

interface EndpointCase {
  endpoint: string;
  description: string;
}

interface EndpointFixtures {
  valid: EndpointCase[];
  invalid: EndpointCase[];
}

const fixturesPath = resolve(__dirname, '../../spec/behavioral_fixtures.yaml');
const allFixtures = YAML.parse(readFileSync(fixturesPath, 'utf-8')) as {
  endpoint_validation: EndpointFixtures;
};
const endpointFixtures = allFixtures.endpoint_validation;

describe('endpoint validation parity (shared fixtures)', () => {
  it.each(endpointFixtures.valid.map((c) => [c.description, c.endpoint] as [string, string]))(
    'accepts valid: %s',
    (_desc, endpoint) => {
      expect(validateOtlpEndpoint(endpoint)).toBe(endpoint);
    },
  );

  // Fixture loop pins both the error type (ConfigurationError) and that the
  // message starts with "invalid OTLP endpoint" — the bare `.toThrow()` form
  // let block-swap and string-literal mutants survive because any thrown
  // error passed the check.
  it.each(endpointFixtures.invalid.map((c) => [c.description, c.endpoint] as [string, string]))(
    'rejects invalid: %s',
    (_desc, endpoint) => {
      expect(() => validateOtlpEndpoint(endpoint)).toThrow(ConfigurationError);
      expect(() => validateOtlpEndpoint(endpoint)).toThrow(/invalid OTLP endpoint/);
    },
  );
});
