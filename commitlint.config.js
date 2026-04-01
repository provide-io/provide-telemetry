// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'test', 'ci', 'docs', 'refactor', 'style', 'chore', 'perf', 'build'],
    ],
    'subject-case': [0],
    'body-max-line-length': [0],
  },
};
