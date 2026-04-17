// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import YAML from 'yaml';
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

describe('validateOtlpEndpoint — empty hostname via mocked URL', () => {
  it('rejects endpoint where URL parses but hostname is empty', () => {
    // The WHATWG URL spec prevents http/https URLs with empty hostnames, so we mock
    // the URL constructor to simulate a URL that parses successfully but has no hostname.
    const OrigURL = globalThis.URL;
    vi.stubGlobal('URL', function (input: string) {
      const u = new OrigURL(input);
      if (input === 'http://fakematch/') {
        Object.defineProperty(u, 'hostname', { get: () => '' });
      }
      return u;
    });
    try {
      expect(() => validateOtlpEndpoint('http://fakematch/')).toThrow(/invalid OTLP endpoint/);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('endpoint validation parity (shared fixtures)', () => {
  it.each(endpointFixtures.valid.map((c) => [c.description, c.endpoint] as [string, string]))(
    'accepts valid: %s',
    (_desc, endpoint) => {
      expect(validateOtlpEndpoint(endpoint)).toBe(endpoint);
    },
  );

  it.each(endpointFixtures.invalid.map((c) => [c.description, c.endpoint] as [string, string]))(
    'rejects invalid: %s',
    (_desc, endpoint) => {
      expect(() => validateOtlpEndpoint(endpoint)).toThrow();
    },
  );
});
