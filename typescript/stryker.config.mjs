// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  testRunner: 'vitest',
  coverageAnalysis: 'perTest',

  // Source files to mutate
  mutate: [
    'src/**/*.ts',
    '!src/index.ts',                    // re-export barrel — no logic to mutate
    '!src/sanitize.ts',                 // deprecated re-export shim (see src/sanitize.ts)
    '!src/secret-patterns-generated.ts', // generated from spec/secret_patterns.yaml — kill via spec/ tests, not unit tests
    // otel.ts / otel-logs.ts use `await import('pkg' as string)` so Stryker's
    // V8 perTest instrumentor cannot trace which test exercises which mutant
    // (every mutant reports covered:0). Dynamic imports are load-bearing for
    // tree-shakeable peer-dep wiring — switching to static imports is out of
    // scope. Integration tests in tests/integration/otel-providers-*.test.ts
    // exercise every branch with real OTel SDK objects.
    '!src/otel.ts',
    '!src/otel-logs.ts',
  ],

  // Vitest config for Stryker
  vitest: {
    configFile: 'vitest.config.ts',
  },

  // Thresholds — fail CI if mutation score drops below these.
  // Current measured score is 96.07% (see docs) — keeping a 95% break
  // threshold so a small churn in survivors doesn't trip CI, and lifting
  // the "high" target to 98 so the reports highlight any regression.
  thresholds: {
    high: 98,
    low: 95,
    break: 95,
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
