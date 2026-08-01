// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  testRunner: 'vitest',
  coverageAnalysis: 'perTest',

  // Source files to mutate
  mutate: [
    'src/**/*.ts',
    '!src/index.ts', // re-export barrel — no logic to mutate
    '!src/secret-patterns-generated.ts', // generated from spec/secret_patterns.yaml — kill via spec/ tests, not unit tests
    // otel-dynimport.ts's `return import(pkg)` is the sole remaining literal
    // dynamic-import expression in the peer-dep wiring — Stryker's V8 perTest
    // instrumentor cannot trace which test exercises which mutant through it
    // (every mutant reports covered:0).
    '!src/otel-dynimport.ts',
    // otel.ts / otel-logs.ts: these files are excluded for now because they
    // include transport/protocol setup and edge paths that are intentionally
    // covered by contract and integration tests, not unit-level mutation.
    '!src/otel.ts',
    '!src/otel-logs.ts',
  ],

  // Vitest config for Stryker
  vitest: {
    configFile: 'vitest.config.ts',
  },

  // Thresholds — fail CI if mutation score drops below these.
  // Keep "break" at 95% so noise on non-critical paths can be filtered out.
  // "high" at 98% provides a visible regression target in mutation reports.
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
