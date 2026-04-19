// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// All logger tests have been split into:
//   logger.hook.test.ts   — write hook, getLogger, logger singleton, LEVEL_MAP, OTLP export
//   logger.schema.test.ts — schema validation, logIncludeCaller, logModuleLevels, sanitize, timestamp
//   logger.gates.test.ts  — logsEmitted health counter, sampling gate, consent gate, backpressure gate

import { describe, it } from 'vitest';

describe('logger (split)', () => {
  it.todo('see logger.hook.test.ts, logger.schema.test.ts, logger.gates.test.ts');
});
