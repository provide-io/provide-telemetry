// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// All propagation tests have been split into:
//   propagation.parse.test.ts   — W3C parsing, header guards, parseBaggage, OTel context wiring
//   propagation.context.test.ts — bind/clear, baggage injection, fallback/warning, trace context

import { describe, it } from 'vitest';

describe('propagation (split)', () => {
  it.todo('see propagation.parse.test.ts, propagation.context.test.ts');
});
