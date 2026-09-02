# C# Changelog

Releases of the NuGet packages `Provide.Telemetry` and
`Provide.Telemetry.OpenTelemetry`. The root `CHANGELOG.md` covers all five
languages; this file covers only what shipped to NuGet.

---

## [Unreleased]

### Breaking

- **The nine public log methods take two more parameters.** `Trace`, `Debug`,
  `Info`, `Warn`, `Warning`, `Critical`, both `Error` overloads and `Log` each
  end in `[CallerFilePath] string callerFile = ""` and
  `[CallerLineNumber] int callerLine = 0`, which the compiler supplies. This is
  what makes `PROVIDE_LOG_INCLUDE_CALLER` do anything here.

  Binary-breaking: an assembly built against 0.8.x raises
  `MissingMethodException` on its first log call and must be rebuilt.

  Source-breaking in two shapes that compiled on 0.8.x:

  - `log.Error("m", null)` and `log.Error("m", null, null)` become **CS0121**,
    ambiguous between the two `Error` overloads. Resolution used to break the
    tie by preferring the candidate omitting fewer optional parameters; both now
    omit the same two, so neither `null → IReadOnlyDictionary?` nor
    `null → Exception` wins. Name the argument — `fields: null` — or cast it.
  - `Action<string, IReadOnlyDictionary<string, object?>?> h = log.Info;`
    becomes **CS0123**. A method-group conversion needs exact arity, and `Info`
    went from two parameters to four. Wrap it in a lambda.

  `dynamic` dispatch and `MethodInfo.Invoke` bypass the compiler, so both emit a
  record with no callsite rather than a wrong one. Reflection that looks a log
  method up by its two-parameter signature finds nothing and must pass four.

- **`LoggingConfig.LogCodeAttributes` is removed.** It was settable and cloned
  and nothing else: no environment variable parsed it and no emitter read it.
  `spec/telemetry-api.yaml` lists `PROVIDE_LOG_CODE_ATTRIBUTES` for Python,
  TypeScript and Go, so the property named a knob this package does not have —
  the same reason `PrettyKeyColor` and its siblings are absent.

### Added

- **`PROVIDE_LOG_INCLUDE_CALLER` attaches `filename` and `lineno`.** `filename`
  is the base name of the calling source file — never the whole path, which
  `[CallerFilePath]` bakes in from the machine that compiled the assembly — and
  `lineno` is its 1-based line. The pair is attached after redaction, on the
  same seam as `_schema_error`, and overwrites a caller field of either name.

  A cross-language pass in the behavioural parity harness asserts this SDK names
  its caller's file, alongside Python, TypeScript and Go.

## [0.8.1] — 2026-08-22

### Breaking

- **`PROVIDE_CONSENT_LEVEL` fails closed on a value it does not recognise.**
  A set, non-empty value other than `FULL`, `FUNCTIONAL`, `MINIMAL` or `NONE`
  (trimmed, case-insensitive) sets consent to `None` on every load and writes
  one warning per process to `Console.Error`, naming the raw value —
  deliberately outside the SDK logger, which the `None` it just applied would
  silence. An unrecognised value used to be ignored, so a misspelled opt-out
  (`PROVIDE_CONSENT_LEVEL=NOEN`) in an otherwise untouched process kept
  collecting at `Full`. Unset and blank still leave the current level alone;
  `SetupTelemetry` and the lazy `GetLogger` path read the variable the same
  way and fail closed the same way. `Testing.ResetForTests()` re-arms the
  warning.
- **`PIIRule.TruncateTo` defaults to 8, and a limit of 0 keeps only the
  suffix.** An unset limit used to be 0, and 0 meant "no limit" — a truncate
  rule registered without `TruncateTo` passed the whole value through, which
  no other SDK does. Unset now means the cross-SDK default of 8, zero yields
  exactly `"..."`, and a negative limit is clamped to zero. The limit counts
  Unicode scalar values rather than UTF-16 code units, so an emoji is never
  cut in half. `Pii.DefaultTruncateTo` names the default.
- **`Pii.HashValue` hashes the RFC 8785 canonical JSON of non-string
  values** — the same text the receipts hash — instead of their `ToString()`
  rendering. `true` therefore digests as `"true"` (was `"True"`) and `null` as
  `"null"` (was `""`), matching every other SDK; strings and integers are
  unchanged.

## [0.8.0] — 2026-08-19

> **First release to actually reach NuGet.** Trusted Publishing had rejected
> the token exchange on every prior attempt because the `provide.io`
> organization had no confirmed email address; once confirmed, the existing
> `publish-nuget` job pushed both packages unchanged. `Provide.Telemetry` goes
> 0.7.2 → 0.8.0, and `Provide.Telemetry.OpenTelemetry` appears on the registry
> for the first time.

### Breaking

- **`PROVIDE_LOG_LEVEL=FATAL` now admits only `CRITICAL` records.** It
  previously admitted everything from `INFO` up, because `FATAL` was absent
  from `Logger.Rank` and fell through to the default of 20 — which is `INFO`.
  C# validates no log level, so anyone who set `FATAL` expecting near-silence
  was getting nearly everything, and was never told. Probed against the build:

  ```
  configured=FATAL    admits=[CRITICAL]                    # was [INFO,WARN,ERROR,CRITICAL]
  configured=CRITICAL admits=[CRITICAL]                    # unchanged
  configured=bogus    admits=[INFO,WARN,ERROR,CRITICAL]    # unchanged
  ```

### Added

- `LogSeverity` and `Levels.Parse` / `TryParse` / `Name` / `Order`.
- `Logger.Log(LogSeverity level, string message, fields)` — for adapters that
  receive a level as data and would otherwise re-implement a dispatch chain
  whose arms only run when that severity actually occurs.

  Not named `LogLevel`: `Microsoft.Extensions.Logging.LogLevel` is near
  universal in .NET and the collision raises CS0104 on every unqualified use in
  any file importing both namespaces — including this package's own
  `OpenTelemetryBackend.cs`.

### Fixed

- `Logger.Rank` and `Governance.LogLevelOrder` were separate tables that
  disagreed on an unrecognised level (INFO vs TRACE) and neither knew `FATAL`,
  so the most severe record in the ladder was dropped by the consent gates as
  if it were the least. Both resolve through `Levels` now.
- `OpenTelemetryBackend.MapLevel` understands `FATAL`.

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
