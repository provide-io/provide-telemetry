// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { registerOtelProviders } from '../src/otel-noop';
import { configFromEnv } from '../src/config';

describe('otel-noop', () => {
  it('registerOtelProviders resolves without error', async () => {
    const cfg = configFromEnv();
    await expect(registerOtelProviders(cfg)).resolves.toBeUndefined();
  });
});
