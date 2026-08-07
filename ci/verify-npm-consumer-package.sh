#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Packs the TypeScript package, installs the tarball into a throwaway
# consumer project, and imports every published entry point from Node.
#
# This exists because `tsc` and `vitest` both pass on a package Node cannot
# load. Vitest resolves specifiers the way a bundler does, so an emitted
# `import './config'` — extensionless, and therefore invalid in an ESM
# package — is green all the way through the suite and only fails in a real
# consumer. Nothing but an actual `node import()` of the packed artifact
# catches that class of break, so that is what this does.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_dir="$(cd "${script_dir}/../typescript" && pwd)"

probe_dir="$(mktemp -d)"
trap 'rm -rf "${probe_dir}"' EXIT

# Pack what would actually be published, not the working tree: `files` in
# package.json decides what ships, so a missing dist/ is a break this catches.
tarball="$(cd "${package_dir}" && npm pack --silent --pack-destination "${probe_dir}")"

cd "${probe_dir}"
npm init --yes >/dev/null
npm pkg set type=module >/dev/null
# react is an optional peer, but the `./react` entry point imports it eagerly,
# so the probe must supply it to reach that subpath at all.
npm install --silent --no-audit --no-fund "./${tarball}" react

cat >probe.mjs <<'EOF'
// Each entry point must load and expose the surface a consumer imports it for.
const checks = [
  ['@provide-io/telemetry', 'getLogger'],
  ['@provide-io/telemetry/otel', null],
  ['@provide-io/telemetry/react', null],
];

for (const [specifier, expectedExport] of checks) {
  const module = await import(specifier);
  if (Object.keys(module).length === 0) {
    throw new Error(`${specifier} loaded but exported nothing`);
  }
  if (expectedExport !== null && typeof module[expectedExport] !== 'function') {
    throw new Error(`${specifier} is missing the ${expectedExport} export`);
  }
  console.log(`OK: ${specifier} (${Object.keys(module).length} exports)`);
}

// Exercising it proves the module graph is whole; a broken transitive
// specifier can hide behind a top-level import that never touches it.
const { getLogger } = await import('@provide-io/telemetry');
getLogger('release.probe').info('consumer probe');
EOF

node probe.mjs

# Behavior, not just loadability. AsyncLocalStorage acquisition differs between
# the CJS module system every test runner uses and the ESM package that ships,
# so scoped-context isolation has to be asserted against the installed tarball
# or it is not asserted at all. See typescript/tests/packed-esm-context.mjs.
cp "${package_dir}/tests/packed-esm-context.mjs" .
node packed-esm-context.mjs

printf 'OK: npm consumer probe succeeded for %s\n' "${tarball}"
