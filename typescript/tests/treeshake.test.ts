// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import pkg from '../package.json';

describe('tree-shaking support', () => {
  it('package.json has sideEffects: false', () => {
    expect(pkg['sideEffects']).toBe(false);
  });

  it('package.json has ESM module type', () => {
    expect(pkg['type']).toBe('module');
  });

  it('React peer dependency is optional for core consumers', () => {
    expect(pkg['peerDependenciesMeta']?.['react']?.['optional']).toBe(true);
  });
});
