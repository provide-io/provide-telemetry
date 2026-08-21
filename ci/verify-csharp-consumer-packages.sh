#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Packs both NuGet packages into a throwaway local feed and consumes them the
# way a customer would: exact-version PackageReference, restore from that feed
# alone, build, run.
#
# The consumer projects previously used <ProjectReference>, which compiles the
# source tree. That is green for a package with a missing file, a wrong target
# framework, or a broken dependency group, because none of those exist until
# `dotnet pack` runs. Only installing the artifact catches them.
set -euo pipefail

# pwd -P, not pwd: the physical path, with symlinks resolved.
#
# This repository is also reachable through a symlink, and a bare `pwd` returns
# whichever spelling the caller happened to use. Handing MSBuild the symlinked
# spelling makes it resolve the ProjectReference to the physical path, so the
# referenced project and the built project are two different identities and the
# ProjectReference -> package-dependency conversion silently drops
# Provide.Telemetry from the integration package's nuspec. The package then
# restores cleanly and the consumer fails to compile with a wall of CS0103.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="${PROVIDE_REPO_ROOT:-$(cd "${script_dir}/.." && pwd -P)}"
csharp_dir="${repo_root}/csharp"

if [[ ! -d "${csharp_dir}" ]]; then
  echo "verify-csharp-consumers: no csharp/ directory under ${repo_root}" >&2
  exit 1
fi

version="${PROVIDE_TELEMETRY_VERSION:-$(tr -d '[:space:]' < "${csharp_dir}/VERSION")}"
if [[ -z "${version}" ]]; then
  echo "verify-csharp-consumers: could not determine the package version" >&2
  exit 1
fi
echo "verify-csharp-consumers: version ${version}"

# Persistent MSBuild worker nodes cache project evaluations across invocations
# and are keyed loosely enough that a node started from the symlinked spelling
# of this repository answers for the real one. A reused node produced an
# integration package with no dependency on Provide.Telemetry while the same
# commands in a fresh shell produced a correct one. Every dotnet call here is
# one-shot, so node reuse buys nothing and costs determinism.
export MSBUILDDISABLENODEREUSE=1
export DOTNET_CLI_TELEMETRY_OPTOUT=1

work_dir="$(mktemp -d)"
# PROVIDE_KEEP_WORKDIR=1 leaves the feed, the consumers and the build logs in
# place so a CI failure can be inspected instead of guessed at.
if [[ -z "${PROVIDE_KEEP_WORKDIR:-}" ]]; then
  trap 'rm -rf "${work_dir}"' EXIT
else
  echo "verify-csharp-consumers: keeping ${work_dir}"
fi
feed_dir="${work_dir}/feed"
mkdir -p "${feed_dir}"

# Isolate the global packages folder as well as the feed. Clearing <packageSources>
# alone is NOT enough: NuGet prefers an already-extracted package in
# ~/.nuget/packages over anything a source offers, keyed on id+version only. A
# previous run's artifact therefore satisfies the restore and the freshly packed
# one is never read — which silently pinned a nupkg with a missing dependency
# group here on 2026-08-20 and made the consumer fail to compile. Hermetic or
# it proves nothing.
# Build the integration project first, then pack with --no-build.
#
# Packing it directly, without that build, intermittently produced a nuspec with
# NO dependency on Provide.Telemetry: the ProjectReference -> package-dependency
# conversion is build-state dependent, and when it drops the entry the package
# restores cleanly but the consumer cannot see a single core type. Building
# first makes the graph explicit and produced the correct nuspec on every run.
for project in Provide.Telemetry Provide.Telemetry.OpenTelemetry; do
  dotnet build "${csharp_dir}/src/${project}/${project}.csproj" \
    --configuration Release >"${work_dir}/pack-build-${project}.log" 2>&1 || {
      echo "verify-csharp-consumers: failed to build ${project} before packing" >&2
      cat "${work_dir}/pack-build-${project}.log" >&2
      exit 1
    }
done

# Pack Release, matching what a release build publishes. Debug is the SDK's
# default and would test a configuration nobody ships.
for project in Provide.Telemetry Provide.Telemetry.OpenTelemetry; do
  dotnet pack "${csharp_dir}/src/${project}/${project}.csproj" \
    --configuration Release --no-build --output "${feed_dir}" >/dev/null
done

for project in Provide.Telemetry Provide.Telemetry.OpenTelemetry; do
  if [[ ! -f "${feed_dir}/${project}.${version}.nupkg" ]]; then
    echo "verify-csharp-consumers: ${project}.${version}.nupkg was not produced" >&2
    ls -la "${feed_dir}" >&2
    exit 1
  fi
done
echo "verify-csharp-consumers: packed $(ls "${feed_dir}" | tr '\n' ' ')"

# Assert the dependency group, not just that a file appeared. A
# Provide.Telemetry.OpenTelemetry package that does not depend on
# Provide.Telemetry restores without a warning and then fails to compile in the
# consumer with a wall of CS0103 — the artifact is broken, and this is the only
# place that says so plainly.
nuspec_dir="${work_dir}/nuspec"
mkdir -p "${nuspec_dir}"
unzip -o -q "${feed_dir}/Provide.Telemetry.OpenTelemetry.${version}.nupkg" -d "${nuspec_dir}"
if ! grep -q "dependency id=\"Provide.Telemetry\"" \
     "${nuspec_dir}/Provide.Telemetry.OpenTelemetry.nuspec"; then
  echo "verify-csharp-consumers: the packed integration package declares no dependency on Provide.Telemetry" >&2
  grep "dependency id" "${nuspec_dir}/Provide.Telemetry.OpenTelemetry.nuspec" >&2 || true
  exit 1
fi
echo "verify-csharp-consumers: integration package depends on Provide.Telemetry ${version}"



export NUGET_PACKAGES="${work_dir}/packages"
mkdir -p "${NUGET_PACKAGES}"

run_consumer() {
  local name="$1"
  local consumer_dir="${work_dir}/${name}"
  cp -R "${csharp_dir}/consumer/${name}" "${consumer_dir}"
  # Drop any build output carried over from a source-tree build: a stale obj/
  # holds the previous restore's assets and would let the consumer resolve
  # against something other than the throwaway feed.
  rm -rf "${consumer_dir}/bin" "${consumer_dir}/obj"

  # nuget.org is needed for the third-party graph (OpenTelemetry,
  # Microsoft.Extensions.*), so it cannot simply be cleared. Instead
  # packageSourceMapping confines OUR package ids to the throwaway feed: a
  # Provide.* package can only ever come from what this run packed, while
  # everything else resolves normally. Without the mapping the published 0.8.0
  # on nuget.org would satisfy the restore and a broken local artifact would
  # pass unnoticed — the exact failure this script exists to catch.
  cat >"${consumer_dir}/nuget.config" <<XML
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="local" value="${feed_dir}" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <packageSourceMapping>
    <packageSource key="local">
      <package pattern="Provide.Telemetry*" />
    </packageSource>
    <packageSource key="nuget.org">
      <package pattern="*" />
    </packageSource>
  </packageSourceMapping>
</configuration>
XML

  if grep -q "<ProjectReference" "${consumer_dir}"/*.csproj; then
    echo "verify-csharp-consumers: ${name} still has a ProjectReference" >&2
    exit 1
  fi

  # --no-restore is deliberately absent: restoring from the throwaway feed is
  # half of what is being tested. Build output is captured rather than
  # discarded — a compile error here is the finding, not noise.
  if ! dotnet build "${consumer_dir}" --configuration Release \
      -p:ProvideTelemetryVersion="${version}" >"${work_dir}/${name}-build.log" 2>&1; then
    echo "verify-csharp-consumers: ${name} failed to build against the packed artifacts" >&2
    cat "${work_dir}/${name}-build.log" >&2
    exit 1
  fi
  dotnet run --project "${consumer_dir}" --configuration Release --no-build \
    -p:ProvideTelemetryVersion="${version}"
}

run_consumer Provide.Telemetry.ConsumerSmoke
run_consumer Provide.Telemetry.OpenTelemetryConsumer

echo "verify-csharp-consumers: both packages install, build and run"
