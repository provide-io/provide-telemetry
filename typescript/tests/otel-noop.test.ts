// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { registerOtelProviders } from '../src/otel-noop.js';
import { configFromEnv } from '../src/config.js';

describe('otel-noop', () => {
  it('registerOtelProviders resolves without error', async () => {
    const cfg = configFromEnv();
    await expect(registerOtelProviders(cfg)).resolves.toBeUndefined();
  });
});
