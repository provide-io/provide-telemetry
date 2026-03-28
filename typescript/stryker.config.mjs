// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  testRunner: 'vitest',
  coverageAnalysis: 'perTest',

  // Source files to mutate
  mutate: [
    'src/**/*.ts',
    '!src/index.ts',    // re-export barrel — no logic to mutate
    '!src/sanitize.ts', // re-export shim
  ],

  // Vitest config for Stryker
  vitest: {
    configFile: 'vitest.config.ts',
  },

  // Thresholds — fail CI if mutation score drops below these
  thresholds: {
    high: 100,
    low: 100,
    break: 100,
  },

  // Reporters
  reporters: ['progress', 'html', 'json', 'clear-text'],
  jsonReporter: {
    fileName: 'reports/mutation/mutation.json',
  },
  htmlReporter: {
    fileName: 'reports/mutation/index.html',
  },

  // Ignore patterns that are definitionally hard to mutate
  ignorePatterns: ['dist', 'node_modules', 'reports', 'coverage'],

  // Only mutate lines that are reachable (exclude defensive unreachable branches)
  ignoreStatic: true,
};
