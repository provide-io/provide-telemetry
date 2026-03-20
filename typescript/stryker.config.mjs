// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  testRunner: 'vitest',
  coverageAnalysis: 'perTest',

  // Source files to mutate
  mutate: [
    'src/**/*.ts',
    '!src/index.ts',   // re-export barrel — no logic to mutate
    '!src/otel.ts',    // OTEL SDK wiring — excluded from coverage too
    '!src/sanitize.ts', // re-export shim
  ],

  // Vitest config for Stryker
  vitest: {
    configFile: 'vitest.config.ts',
  },

  // Thresholds — fail CI if mutation score drops below these
  thresholds: {
    high: 90,
    low: 80,
    break: 70,
  },

  // Reporters
  reporters: ['progress', 'html', 'clear-text'],
  htmlReporter: {
    fileName: 'reports/mutation/index.html',
  },

  // Ignore patterns that are definitionally hard to mutate
  ignorePatterns: ['dist', 'node_modules', 'reports', 'coverage'],

  // Only mutate lines that are reachable (exclude defensive unreachable branches)
  ignoreStatic: true,
};
