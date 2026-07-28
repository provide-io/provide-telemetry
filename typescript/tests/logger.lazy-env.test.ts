// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig } from '../src/config.js';
import { _resetRootLogger, getLogger } from '../src/logger.js';
import { getSamplingPolicy, _resetSamplingForTests } from '../src/sampling.js';

describe('lazy logger env policy', () => {
  afterEach(() => {
    _resetRootLogger();
    _resetConfig();
    _resetSamplingForTests();
    vi.unstubAllEnvs();
  });

  it('applies env log sampling policy before setupTelemetry', () => {
    vi.stubEnv('PROVIDE_SAMPLING_LOGS_RATE', '0');

    getLogger('lazy.env.sampling');

    expect(getSamplingPolicy('logs').defaultRate).toBe(0);
  });
});
