// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { getConsentLevel, resetConsentForTests, setConsentLevel } from '../src/consent.js';
import { _resetRootLogger, getLogger } from '../src/logger.js';
import { getSamplingPolicy, _resetSamplingForTests } from '../src/sampling.js';

describe('lazy logger env policy', () => {
  afterEach(() => {
    _resetRootLogger();
    _resetConfig();
    _resetSamplingForTests();
    resetConsentForTests();
    vi.unstubAllEnvs();
  });

  it('applies env log sampling policy before setupTelemetry', () => {
    vi.stubEnv('PROVIDE_SAMPLING_LOGS_RATE', '0');

    getLogger('lazy.env.sampling');

    expect(getSamplingPolicy('logs').defaultRate).toBe(0);
  });

  it('applies PROVIDE_CONSENT_LEVEL before setupTelemetry', () => {
    vi.stubEnv('PROVIDE_CONSENT_LEVEL', 'NONE');

    getLogger('lazy.env.consent');

    expect(getConsentLevel()).toBe('NONE');
  });

  it('lazy path: env wins over a programmatic level set before any setup', () => {
    setConsentLevel('MINIMAL');
    vi.stubEnv('PROVIDE_CONSENT_LEVEL', 'none');

    getLogger('lazy.env.consent.precedence');

    expect(getConsentLevel()).toBe('NONE');
  });

  it('lazy path with env unset leaves a programmatic level untouched', () => {
    setConsentLevel('MINIMAL');

    getLogger('lazy.env.consent.unset');

    expect(getConsentLevel()).toBe('MINIMAL');
  });

  it('does not clobber a programmatic level set after setup on a logger rebuild', () => {
    vi.stubEnv('PROVIDE_CONSENT_LEVEL', 'NONE');
    setupTelemetry({ serviceName: 'svc' });
    expect(getConsentLevel()).toBe('NONE');

    setConsentLevel('FULL');
    _resetRootLogger();
    getLogger('post.setup.rebuild');

    expect(getConsentLevel()).toBe('FULL');
  });
});
