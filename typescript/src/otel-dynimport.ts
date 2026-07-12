// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Indirection point for every optional-peer-dependency import in this package.
 *
 * Bundlers (esbuild, webpack, rollup) statically resolve `import('literal')`
 * even when the literal is cast `as string` — the TS cast is erased at compile
 * time, so the emitted JS still carries a plain string specifier. Consumers
 * that pull this package's full export surface into their graph (e.g. an
 * `export *` re-export) without installing the @opentelemetry/* peer deps
 * then fail to build with "Could not resolve @opentelemetry/...".
 *
 * Routing every optional import through this function's `pkg` *parameter* —
 * never a literal at the call site — defeats that static analysis: bundlers
 * cannot constant-fold a variable, so `import(pkg)` is left as a genuine
 * runtime dynamic import instead of being added to the build graph. The
 * peer deps stay truly optional for bundler users, matching
 * peerDependenciesMeta.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function dynImportOtel(pkg: string): Promise<any> {
  return import(pkg);
}
