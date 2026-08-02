// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { ConfigurationError, ProviderImmutableError, TelemetryError } from '../src/exceptions.js';

describe('TelemetryError', () => {
  it('is an instance of Error', () => {
    const e = new TelemetryError('oops');
    expect(e).toBeInstanceOf(Error);
    expect(e).toBeInstanceOf(TelemetryError);
    expect(e.message).toBe('oops');
    expect(e.name).toBe('TelemetryError');
  });

  it('works with no message', () => {
    const e = new TelemetryError();
    expect(e.message).toBe('');
    expect(e.name).toBe('TelemetryError');
  });
});

describe('ConfigurationError', () => {
  it('is a TelemetryError and Error', () => {
    const e = new ConfigurationError('bad config');
    expect(e).toBeInstanceOf(Error);
    expect(e).toBeInstanceOf(TelemetryError);
    expect(e).toBeInstanceOf(ConfigurationError);
    expect(e.message).toBe('bad config');
    expect(e.name).toBe('ConfigurationError');
  });

  it('can be caught as TelemetryError', () => {
    const fn = () => {
      throw new ConfigurationError('x');
    };
    expect(fn).toThrow(TelemetryError);
    expect(fn).toThrow(ConfigurationError);
  });
});

describe('ProviderImmutableError', () => {
  it('is a ConfigurationError, TelemetryError, and Error', () => {
    const e = new ProviderImmutableError('providers already installed');
    expect(e).toBeInstanceOf(Error);
    expect(e).toBeInstanceOf(TelemetryError);
    expect(e).toBeInstanceOf(ConfigurationError);
    expect(e).toBeInstanceOf(ProviderImmutableError);
    expect(e.message).toBe('providers already installed');
    expect(e.name).toBe('ProviderImmutableError');
  });

  it('can be caught as ConfigurationError', () => {
    const fn = () => {
      throw new ProviderImmutableError('x');
    };
    expect(fn).toThrow(ConfigurationError);
    expect(fn).toThrow(ProviderImmutableError);
  });
});
