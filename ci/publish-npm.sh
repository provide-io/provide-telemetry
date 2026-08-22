#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Publish the packed npm tarball, idempotently — without making the job
# unfailable.
#
# The job used to carry `continue-on-error: true` so a re-triggered release
# would not fail on an already-published version. That suppressed every other
# failure too: bad credentials, a broken tarball, a rejected provenance
# attestation and a registry outage all reported success. This asks the registry
# a specific question instead, and treats only a confirmed already-published
# version as a no-op.
set -euo pipefail

readonly PACKAGE_DIR="${PACKAGE_DIR:-npm-pack/package}"

if [[ ! -f "${PACKAGE_DIR}/package.json" ]]; then
  echo "publish-npm: no package.json under ${PACKAGE_DIR}" >&2
  exit 1
fi

cd "${PACKAGE_DIR}"

name="$(node -p 'require("./package.json").name')"
version="$(node -p 'require("./package.json").version')"
if [[ -z "${name}" || -z "${version}" ]]; then
  echo "publish-npm: package.json is missing a name or version" >&2
  exit 1
fi
echo "publish-npm: ${name}@${version}"

# Ask for the exact version. A hit is proof it exists; a non-zero exit is the
# normal "not published yet" answer. Anything else — a hit reporting a DIFFERENT
# version — means the query did not mean what we assumed, so stop rather than
# guess.
set +e
existing="$(npm view "${name}@${version}" version 2>/dev/null)"
view_status=$?
set -e

if [[ ${view_status} -eq 0 ]]; then
  if [[ "${existing}" == "${version}" ]]; then
    echo "publish-npm: already-published ${name}@${version}; nothing to do"
    exit 0
  fi
  echo "publish-npm: registry answered '${existing}' for ${name}@${version}; refusing to guess" >&2
  exit 1
fi

# Every failure from here is fatal: auth, network, packaging, provenance.
npm publish --access public --provenance --ignore-scripts

# Postcondition. A publish that exits 0 without the version appearing is a
# failure we would otherwise ship as a release.
#
# Retried, because the registry is not read-your-writes: the 0.8.1 publish
# succeeded, printed its provenance attestation, and still answered an empty
# string when asked about itself a second later. One immediate query turns that
# lag into a red release for a package that is already live, which is worse
# than waiting.
readonly CONFIRM_ATTEMPTS="${PUBLISH_NPM_CONFIRM_ATTEMPTS:-10}"
readonly CONFIRM_DELAY_SECONDS="${PUBLISH_NPM_CONFIRM_DELAY_SECONDS:-6}"
confirmed=""
for (( attempt = 1; attempt <= CONFIRM_ATTEMPTS; attempt++ )); do
  confirmed="$(npm view "${name}@${version}" version 2>/dev/null || true)"
  if [[ "${confirmed}" == "${version}" ]]; then
    break
  fi
  if (( attempt < CONFIRM_ATTEMPTS )); then
    echo "publish-npm: ${name}@${version} not visible yet (saw '${confirmed}'), retrying in ${CONFIRM_DELAY_SECONDS}s"
    sleep "${CONFIRM_DELAY_SECONDS}"
  fi
done
if [[ "${confirmed}" != "${version}" ]]; then
  echo "publish-npm: ${name}@${version} not present after publish (saw '${confirmed}')" >&2
  exit 1
fi
echo "publish-npm: published ${name}@${version}"
