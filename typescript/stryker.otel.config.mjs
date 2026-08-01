// SPDX-FileCopyrightText: Copyright (c) 2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import base from './stryker.config.mjs';

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  ...base,
  mutate: ['src/otel.ts', 'src/otel-logs.ts'],
  thresholds: {
    high: 90,
    low: 85,
    break: 80,
  },
  jsonReporter: {
    fileName: 'reports/mutation-otel/mutation.json',
  },
  htmlReporter: {
    fileName: 'reports/mutation-otel/index.html',
  },
};
