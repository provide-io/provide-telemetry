# C# Package Artifact Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove both NuGet packages work as *installed artifacts* — packed, restored from a clean local feed at an exact version, built, and run — rather than as project references into the source tree.

**Architecture:** The two consumer projects that exist today (`csharp/consumer/Provide.Telemetry.ConsumerSmoke`, `csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer`) both use `<ProjectReference>` and neither is invoked by `ci-csharp.yml`. A `ProjectReference` compiles against the source tree, so it proves nothing about what `dotnet pack` produced: a missing `PackageReference`, a wrong `TargetFramework`, a file left out of the nuspec, or a broken dependency group are all invisible to it. Replace that with a script that packs into a throwaway feed, restores from **only** that feed, and runs the resulting binaries.

**Tech Stack:** .NET 10 (`net10.0`), `dotnet pack` / `restore` / `build` / `run`, bash. Package IDs are `Provide.Telemetry` and `Provide.Telemetry.OpenTelemetry`, both at `0.8.0` (`csharp/src/*/*.csproj:9,14`).

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2) — workstream D.

## Global Constraints

- **Never put inline scripts in workflow YAML.** Anything over 3 lines goes in `ci/`. Model the new script on `ci/verify-npm-consumer-package.sh`, which solves the same problem for npm.
- **No `ProjectReference` anywhere in the consumer projects.** That is the whole point. A `ProjectReference` reintroduces the defect silently.
- **Clear nuget.org from the consumer's sources.** If the public feed stays configured, a package that failed to pack can be satisfied from the registry and the test passes on the wrong artifact.
- **Install exact versions** (`[0.8.0]` bracket notation), never floating ranges.
- Consumers must **run**, not merely restore or build. A package that restores and produces a binary that throws on first call is still broken.
- Do **not** remove or weaken the credentialed OpenObserve tests; they remain live-backend verification in addition to this.
- **777 LOC max per file**; **SPDX headers required**.
- No hardcoded machine paths — derive from the script location with an env override.

## File Structure

- Create: `ci/verify-csharp-consumer-packages.sh` — pack, feed, restore, build, run.
- Rewrite: `csharp/consumer/Provide.Telemetry.ConsumerSmoke/` — `PackageReference`, core-only boundary assertions.
- Rewrite: `csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer/` — `PackageReference`, backend-activation assertion.
- Create: `csharp/consumer/nuget.config` — local feed only.
- Modify: `.github/workflows/ci-csharp.yml` — a `package-consumers` job.
- Modify: `docs/guide/capability-matrix.md` — cite the wire tests (shared with plan 4; do it in whichever lands first and skip the duplicate).

---

### Task 1: Prove the current consumers do not test the packages

**Files:** none modified — this task produces evidence.

- [ ] **Step 1: Show the project references**

```bash
grep -rn "ProjectReference\|PackageReference" csharp/consumer/*/*.csproj
```
Expected: two `ProjectReference` lines, zero `PackageReference` lines. That is the
defect: both consumers compile the source tree.

- [ ] **Step 2: Show they are not in CI**

```bash
grep -n "consumer\|dotnet pack\|nupkg" .github/workflows/ci-csharp.yml
```
Expected: no hits. The consumers are not built or run by any job.

- [ ] **Step 3: Record both results in the checklist**

Paste them under recommendation 8 in
`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md`. This
is the baseline the rest of the plan is measured against.

---

### Task 2: Core-only consumer that proves the BCL boundary

**Files:**
- Modify: `csharp/consumer/Provide.Telemetry.ConsumerSmoke/Provide.Telemetry.ConsumerSmoke.csproj`
- Modify: `csharp/consumer/Provide.Telemetry.ConsumerSmoke/Program.cs`

**Interfaces:**
- Consumes: the `Provide.Telemetry` package at exactly `0.8.0` from the local feed.
- Produces: exit 0 when the core package works and pulls in no OpenTelemetry assembly; non-zero otherwise.

- [ ] **Step 1: Replace the project reference with a package reference**

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <!-- Version is supplied by ci/verify-csharp-consumer-packages.sh so the
         script and the csproj cannot drift apart at release time. -->
    <ProvideTelemetryVersion Condition="'$(ProvideTelemetryVersion)' == ''">0.8.0</ProvideTelemetryVersion>
  </PropertyGroup>

  <ItemGroup>
    <!-- Bracket notation pins the exact version: a floating range would let a
         published package satisfy a restore that the freshly-packed one could
         not. NO ProjectReference here — that would compile the source tree and
         prove nothing about the artifact. -->
    <PackageReference Include="Provide.Telemetry" Version="[$(ProvideTelemetryVersion)]" />
  </ItemGroup>

</Project>
```

- [ ] **Step 2: Write the boundary assertions**

```csharp
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Core-only consumer. Installs Provide.Telemetry from a clean local feed with
// no OpenTelemetry package present, exercises the public surface, and asserts
// the BCL-only boundary: the core assembly must not drag in an OpenTelemetry
// dependency, because that is the promise the two-package split makes.

using System.Reflection;
using Provide.Telemetry;

Setup.SetupTelemetry();

var logger = Logger.GetLogger("consumer.core");
logger.Info("consumer.core.startup.ok");

var record = Schema.Event("consumer", "core", "ok");
if (record.Event != "consumer.core.ok")
{
    Console.Error.WriteLine($"FAIL: Schema.Event returned {record.Event}");
    return 1;
}

// The boundary. GetReferencedAssemblies reflects what the compiler baked into
// the shipped assembly, so an OpenTelemetry reference that crept into the core
// package shows up here even though nothing in this program mentions it.
var core = typeof(Setup).Assembly;
var otelReferences = core
    .GetReferencedAssemblies()
    .Where(a => a.Name is not null && a.Name.StartsWith("OpenTelemetry", StringComparison.Ordinal))
    .Select(a => a.Name!)
    .ToArray();
if (otelReferences.Length > 0)
{
    Console.Error.WriteLine($"FAIL: core package references {string.Join(", ", otelReferences)}");
    return 1;
}

// And nothing OpenTelemetry may be loadable at all in this consumer.
var loaded = AppDomain.CurrentDomain
    .GetAssemblies()
    .Where(a => a.GetName().Name?.StartsWith("OpenTelemetry", StringComparison.Ordinal) == true)
    .ToArray();
if (loaded.Length > 0)
{
    Console.Error.WriteLine($"FAIL: OpenTelemetry assembly loaded in a core-only consumer");
    return 1;
}

Setup.ShutdownTelemetry();
Console.WriteLine("core-only consumer OK");
return 0;
```

Read `csharp/src/Provide.Telemetry/PublicApi.cs` for the real entry-point names
before writing this — `Setup.SetupTelemetry` / `Logger.GetLogger` are the shapes
the probes under `csharp/probes/` use, but confirm rather than assume, and do not
add a public API to make the consumer compile.

- [ ] **Step 3: Do not build it yet**

It cannot restore until Task 4 creates the feed. Move on.

---

### Task 3: OTel consumer that proves the backend activates

**Files:**
- Modify: `csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer/Provide.Telemetry.OpenTelemetryConsumer.csproj`
- Modify: `csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer/Program.cs`

**Interfaces:**
- Consumes: `Provide.Telemetry.OpenTelemetry` at exactly `0.8.0`, which must transitively bring `Provide.Telemetry`.
- Produces: exit 0 when registration activates the backend.

- [ ] **Step 1: Package reference only**

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <AssemblyName>Provide.Telemetry.OpenTelemetryConsumer</AssemblyName>
    <ProvideTelemetryVersion Condition="'$(ProvideTelemetryVersion)' == ''">0.8.0</ProvideTelemetryVersion>
  </PropertyGroup>

  <ItemGroup>
    <!-- Only the integration package is named. Provide.Telemetry must arrive
         transitively — if it does not, the integration package's dependency
         group is wrong and this restore fails, which is the point. -->
    <PackageReference Include="Provide.Telemetry.OpenTelemetry" Version="[$(ProvideTelemetryVersion)]" />
  </ItemGroup>

</Project>
```

- [ ] **Step 2: Assert activation, not just compilation**

```csharp
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// OTel consumer. Installs only Provide.Telemetry.OpenTelemetry from a clean
// local feed and asserts that installing the integration package plus calling
// Register() actually activates the backend — the claim the capability matrix
// makes on behalf of these packages.

using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

// Before registration the backend must be inactive, so a passing assertion
// afterwards means registration did something rather than the state having
// been true all along.
if (Health.GetHealthSnapshot().Providers.Traces)
{
    Console.Error.WriteLine("FAIL: traces provider active before registration");
    return 1;
}

OpenTelemetryBackendRegistration.Register();

var config = TelemetryConfig.Default();
config.ServiceName = "consumer-otel";
config.Tracing.Enabled = true;
config.Tracing.OtlpEndpoint = "http://127.0.0.1:4318";
Setup.SetupTelemetry(config);

var snapshot = Health.GetHealthSnapshot();
if (!snapshot.Providers.Traces)
{
    Console.Error.WriteLine("FAIL: traces provider inactive after registration and setup");
    return 1;
}

Setup.ShutdownTelemetry();
Console.WriteLine("otel consumer OK");
return 0;
```

Read `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/WireDeliveryTests.cs` for
the exact registration and config API — it already drives this surface, so copy
its shapes rather than inventing them. The endpoint here is never connected to;
the assertion is about provider installation, not delivery, which
`WireDeliveryTests` already covers.

---

### Task 4: The pack-and-consume script

**Files:**
- Create: `ci/verify-csharp-consumer-packages.sh`
- Create: `csharp/consumer/nuget.config`

**Interfaces:**
- Consumes: env `PROVIDE_TELEMETRY_VERSION` (defaults to the version in `csharp/VERSION`).
- Produces: exit 0 only when both packages pack, restore from the local feed alone, build, and run successfully.

- [ ] **Step 1: Write the consumer feed config**

```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- Local feed ONLY. Clearing the inherited sources is load-bearing: with
     nuget.org configured, a package that failed to pack could be satisfied
     from the public registry and the consumer test would pass against an
     artifact this build did not produce. -->
<configuration>
  <packageSources>
    <clear />
    <add key="local" value="%PROVIDE_LOCAL_FEED%" />
  </packageSources>
</configuration>
```

NuGet expands `%VAR%` on all platforms in `nuget.config` source values. Verify
that in Step 4; if it does not expand on Linux for your SDK version, have the
script write the `nuget.config` into the temporary consumer directory with the
absolute feed path substituted, rather than committing a template.

- [ ] **Step 2: Write the script**

```bash
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

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="${PROVIDE_REPO_ROOT:-$(cd "${script_dir}/.." && pwd)}"
csharp_dir="${repo_root}/csharp"

version="${PROVIDE_TELEMETRY_VERSION:-$(tr -d '[:space:]' < "${csharp_dir}/VERSION")}"
if [[ -z "${version}" ]]; then
  echo "verify-csharp-consumers: could not determine the package version" >&2
  exit 1
fi
echo "verify-csharp-consumers: version ${version}"

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT
feed_dir="${work_dir}/feed"
mkdir -p "${feed_dir}"

# Pack Release, matching what a release build publishes. Debug is the SDK's
# default and would test a configuration nobody ships.
for project in Provide.Telemetry Provide.Telemetry.OpenTelemetry; do
  dotnet pack "${csharp_dir}/src/${project}/${project}.csproj" \
    --configuration Release --output "${feed_dir}"
done

for project in Provide.Telemetry Provide.Telemetry.OpenTelemetry; do
  if [[ ! -f "${feed_dir}/${project}.${version}.nupkg" ]]; then
    echo "verify-csharp-consumers: ${project}.${version}.nupkg was not produced" >&2
    ls -la "${feed_dir}" >&2
    exit 1
  fi
done

run_consumer() {
  local name="$1"
  local consumer_src="${csharp_dir}/consumer/${name}"
  local consumer_dir="${work_dir}/${name}"
  cp -R "${consumer_src}" "${consumer_dir}"

  # Local feed only — see csharp/consumer/nuget.config for why <clear/> matters.
  cat >"${consumer_dir}/nuget.config" <<XML
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="local" value="${feed_dir}" />
  </packageSources>
</configuration>
XML

  if grep -q "ProjectReference" "${consumer_dir}"/*.csproj; then
    echo "verify-csharp-consumers: ${name} still has a ProjectReference" >&2
    exit 1
  fi

  # --no-restore is deliberately absent: restoring from the throwaway feed is
  # half of what is being tested.
  dotnet build "${consumer_dir}" --configuration Release \
    -p:ProvideTelemetryVersion="${version}"
  dotnet run --project "${consumer_dir}" --configuration Release --no-build
}

run_consumer Provide.Telemetry.ConsumerSmoke
run_consumer Provide.Telemetry.OpenTelemetryConsumer

echo "verify-csharp-consumers: both packages install, build and run"
```

- [ ] **Step 3: Make it executable and run it**

Run: `chmod +x ci/verify-csharp-consumer-packages.sh && ./ci/verify-csharp-consumer-packages.sh`
Expected: two `.nupkg` files produced, both consumers print their OK line, exit 0.

Common first failures and what they mean — fix the package, not the test:
- `Unable to find package Provide.Telemetry` in the OTel consumer → the
  integration package's dependency group does not declare the core package.
- `NU1202 … is not compatible with net10.0` → a `TargetFramework` mismatch in the
  packed nuspec.
- A runtime `TypeLoadException` → a file the nuspec did not include.

- [ ] **Step 4: Prove the guard against `ProjectReference` fires**

Temporarily add a `<ProjectReference>` back into
`csharp/consumer/Provide.Telemetry.ConsumerSmoke/Provide.Telemetry.ConsumerSmoke.csproj`,
run the script, confirm it exits non-zero naming the project, then remove it.
Record the output — this is what stops the defect being reintroduced.

- [ ] **Step 5: Prove the clean-feed isolation is real**

Temporarily delete `Provide.Telemetry.OpenTelemetry.${version}.nupkg` from the
feed after packing (add a `rm` before `run_consumer`), run, and confirm the OTel
consumer fails to restore rather than silently pulling the package from
nuget.org. Then remove the `rm`. If it *succeeds*, the `<clear />` is not taking
effect — fix that before continuing, because without it this whole plan tests the
published package rather than the built one.

- [ ] **Step 6: Commit**

```bash
git add ci/verify-csharp-consumer-packages.sh csharp/consumer/
git commit -m "test(csharp): consume both packages as installed artifacts

The consumer projects used ProjectReference, so they compiled the source tree
and proved nothing about what dotnet pack produced. They now install exact
versions from a throwaway feed with nuget.org cleared."
```

---

### Task 5: Wire it into CI

**Files:**
- Modify: `.github/workflows/ci-csharp.yml`

- [ ] **Step 1: Add the job**

```yaml
  # Packs both NuGet packages into a throwaway local feed and consumes them the
  # way a customer would — exact-version PackageReference, no ProjectReference,
  # nuget.org cleared — then builds and runs both consumers.
  package-consumers:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0  # v6
      - uses: actions/setup-dotnet@26b0ec14cb23fa6904739307f278c14f94c95bf1  # v5.4.0
        with:
          dotnet-version: "10.0.x"
      # Packs, restores from the local feed only, builds and runs both consumers.
      - name: Verify NuGet package consumers
        run: ./ci/verify-csharp-consumer-packages.sh
```

Copy the `setup-dotnet` pin and any `dotnet-version` input from the existing
`test` job in the same file rather than writing a new one.

- [ ] **Step 2: Confirm the workflow parses**

Run: `uv run python -c "import yaml,pathlib;yaml.safe_load(pathlib.Path('.github/workflows/ci-csharp.yml').read_text());print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Confirm the credentialed tests are untouched**

Run: `grep -rn "OPENOBSERVE" .github/workflows/ci-csharp.yml csharp/tests/Provide.Telemetry.Tests/OpenObserveIntegrationTests.cs | head`
Expected: the integration test still exists and still self-skips without
credentials. This plan adds evidence; it removes none.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci-csharp.yml
git commit -m "ci(csharp): run the NuGet package consumer verification"
```

---

### Task 6: Correct the capability matrix

**Files:**
- Modify: `docs/guide/capability-matrix.md:61-65`

This overlaps plan 4, Task 4. Do it in whichever plan lands first and skip the
duplicate — but do not leave it undone in both.

- [ ] **Step 1: Confirm the wire tests are credential-free and blocking**

```bash
grep -n "SkippableFact\|OPENOBSERVE" csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/WireDeliveryTests.cs
cd csharp && dotnet test --filter FullyQualifiedName~WireDeliveryTests
```
Expected: no `SkippableFact`, no `OPENOBSERVE`, tests pass without credentials.

- [ ] **Step 2: Rewrite the "no blocking CI evidence" paragraph**

Use the replacement text in plan 4, Task 4, Step 2 verbatim so the two plans
cannot produce different wording.

- [ ] **Step 3: Add a line about artifact evidence**

The matrix should now record both kinds of evidence:

```markdown
  Artifact-level evidence is separate: `ci/verify-csharp-consumer-packages.sh`
  packs both packages into a throwaway feed and installs them at an exact
  version with nuget.org cleared, so a broken nuspec, a wrong target framework
  or a missing dependency group fails CI rather than reaching a consumer.
```

- [ ] **Step 4: Run the docs checker**

Run: `uv run python scripts/check_docs_accuracy.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/guide/capability-matrix.md
git commit -m "docs(csharp): record the wire and artifact evidence for the OTLP rows"
```

---

### Task 7: Full verification and checklist update

- [ ] **Step 1: Run the C# gates**

```bash
cd csharp
dotnet build --configuration Release
dotnet test
cd .. && ./ci/verify-csharp-consumer-packages.sh
```
Expected: all pass.

- [ ] **Step 2: Run the C# mutation gate**

Run: `cd csharp && dotnet stryker`
Expected: within the configured threshold. The consumer programs are test
harnesses, not library code — if Stryker's scope includes them, exclude them in
`csharp/stryker-config.json` with an inline reason, matching how the TypeScript
config documents each exclusion.

- [ ] **Step 3: Run the repository gates**

```bash
uv run python scripts/check_max_loc.py --max-lines 777
uv run python scripts/check_spdx_headers.py
uv run python scripts/check_version_sync.py
git status --short
```
Expected: all pass; clean tree.

- [ ] **Step 4: Update the umbrella checklist**

Tick recommendation 8 in
`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md`,
pasting the pack output, the restore log showing the local feed as the only
source, and both consumers' OK lines. Include the two falsifiability results from
Task 4, Steps 4 and 5 — the `ProjectReference` guard firing and the missing-package
restore failing — since those are what prove the harness works.
