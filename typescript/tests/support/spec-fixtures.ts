// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Locate a file under the repository's `spec/` directory.
 *
 * Resolving `../../spec/x.yaml` from `__dirname` works under a plain vitest run
 * and breaks under Stryker, which copies the TypeScript project into
 * `.stryker-tmp/sandbox-N/` before mutating it. `spec/` lives above that project
 * root, so it is never copied, and the resolved path points at a sandbox
 * directory that does not exist.
 *
 * The failure is silent in the way that matters: the fixture read throws at
 * module load, the whole fixture-driven file drops out of the run, and Stryker
 * reports a clean score for mutants those fixtures would have killed. That is
 * how a mutant deleting the userinfo strip in `endpoint.ts` survived a run whose
 * own test suite fails against it.
 *
 * Walking up from `__dirname` finds the real `spec/` from either location: the
 * sandbox sits inside `typescript/`, so the walk passes through it to the
 * repository root.
 */

import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

export function specFixturePath(name: string): string {
  let directory = __dirname;
  for (;;) {
    const candidate = resolve(directory, 'spec', name);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(directory);
    if (parent === directory) {
      throw new Error(`could not locate spec/${name} in any parent of ${__dirname}`);
    }
    directory = parent;
  }
}
