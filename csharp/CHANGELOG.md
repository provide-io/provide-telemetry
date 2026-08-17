# C# Changelog

Releases of the NuGet packages `Provide.Telemetry` and
`Provide.Telemetry.OpenTelemetry`. The root `CHANGELOG.md` covers all five
languages; this file covers only what shipped to NuGet.

---

## [0.7.2] — 2026-08-16

### Fixed

- **Secret redaction kept only the first match in a value.** A string
  carrying two credentials lost the first and emitted the second intact.
  A filesystem path earlier in the string could also shield a genuine
  credential behind it, because the path exemption was applied to the
  first match and then abandoned the whole value. Every pattern now runs
  across the whole value, each match is judged on its own token, and the
  surviving spans are merged and replaced right to left.

## [0.7.0] — 2026-08-14

First release.

- **`Provide.Telemetry`** is a dependency-free core —
  `dotnet list package --include-transitive` reports none. Logging with
  console, JSON and ANSI pretty renderers (severity-colored, TTY-detected,
  matching the other four languages' layout), tracing,
  metrics, W3C propagation with full tracestate grammar validation,
  PII/secret redaction with recursive hardening, cardinality guards,
  backpressure, resilience (retries, timeouts, circuit breaker), SLO helpers,
  canonical governance receipts (RFC 8785 canonical JSON, HMAC-SHA256) and
  the 26-field health snapshot.
- **`Provide.Telemetry.OpenTelemetry`** carries the OTLP export path and the
  OpenTelemetry SDK dependencies. An application calls
  `OpenTelemetryBackendRegistration.Register()` before setup — without it,
  the core degrades gracefully to no-op providers, the same
  optional-backend pattern the Go module uses.
- **Parity is tested, not asserted.** The package passes spec conformance,
  every behavioral-fixture category, the cross-language contract harness and
  the shared receipt/JCS number vectors; its canonical log envelope is
  byte-identical to Python's. It ships with a benchmark suite under seeded
  perf budgets and a Stryker mutation gate that was proven able to fail.
- **Published via trusted publishing.** A `csharp/vX.Y.Z` tag builds, tests
  and packs both packages, then exchanges the GitHub OIDC token for a
  short-lived NuGet.org API key — no stored publish credential exists. Both
  packages are owned by the `provide.io` organization; see
  `docs/operations/release.md` for the full path.
