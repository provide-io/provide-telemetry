# Changelog

Releases of the npm package `@provide-io/telemetry`. The root `CHANGELOG.md`
covers all five languages; this file covers only what shipped to npm.

Two things to know when reading it:

- Entries marked _(reconstructed)_ were written after the fact from git history,
  by diffing each version-bump commit against the previous one. They describe
  what changed, not what the author would have chosen to highlight.
- **0.4.0, 0.4.1 and 0.4.2 were never published to npm.** They predate 0.2.2 in
  time — the project rewound its version number in April 2026 — and are kept
  here in version order, out of chronological order, because that is what a
  changelog is read in. `npm view @provide-io/telemetry versions` is the
  authority on what a consumer can actually install.

## [Unreleased]

### Breaking

- **The callsite fields are renamed and the code attributes move to current
  semantic conventions.** `caller_file` → `filename`, `caller_line` → `lineno`,
  `code.filepath` → `code.file.path`, `code.lineno` → `code.line.number`.
  `code.namespace` is dropped, having no cross-language meaning, and
  `code.function.name` is new — omitted when the frame resolves no name. A saved
  query filtering on an old name stops matching.

  These are the names Python already emitted; the rename is what makes the four
  SDKs agree, and a cross-language pass in the parity harness now asserts it.

- **`code.file.path` carries the whole path, not the base name.** That is what
  OpenTelemetry defines the attribute as and what Python
  (`record.pathname`) and Go (`runtime.Frame.File`) send. `filename` on the
  record is still a base name.

- **`logCodeAttributes` no longer depends on `logIncludeCaller`.** It used to
  emit nothing unless both were on, because the `code.*` attributes were derived
  from the record fields. Each knob controls only its own output.

### Fixed

- **The callsite named this module instead of the caller in every published
  build.** The stack walk skipped frames whose text contained `logger.ts`, and
  consumers run the compiled `logger.js`, so the walk stopped on this module's
  own frame and every record reported the SDK. Correct in the source tree and in
  the tests, wrong everywhere it mattered.

  The walk now identifies its own frames by the file the capture is in, so no
  list of file names has to keep step with the build. Three consequences:

  - A consumer whose own module is called `logger.ts` is reported, not skipped.
  - A library that logs is reported as the callsite. Skipping every frame under
    `node_modules` attributed its records to whoever called it; pino's frames
    are matched by path segment instead, which also stops skipping a caller
    working under a directory named `pino` or a function named `pinoAdapter`.
  - A bundle, where this module and the application share one file, carries no
    callsite. Nothing there distinguishes the caller, and naming the logger's
    own line is a wrong answer rather than a missing one.

- **A Windows CJS frame published the full path as `filename`.** The base-name
  strip handled forward slashes only, so `C:\srv\app\routes.ts` was reported
  whole — the build machine's layout, on the platform where CJS output is still
  common.

- **A host owning `Error.prepareStackTrace` no longer costs a log record.**
  Source-map and tracing libraries install their own formatter, and `.stack` is
  then not a string; reading it threw. In Node pino's stream wrapper swallowed
  the throw and the record vanished, and in a browser it reached the
  application's log call. The capture yields no callsite instead.

- **A nested-eval frame no longer produces a malformed filename.** It carries
  two locations in one set of parentheses, which the path group swallowed whole;
  such a frame now yields no callsite.

## [0.8.1] — 2026-08-22

### Breaking

- **`PROVIDE_CONSENT_LEVEL` is read at setup and on the lazy logger path.**
  `loadConsentFromEnv()` was exported but never called, so an operator opt-out
  of `NONE` left the SDK collecting at `FULL`. `setupTelemetry()`,
  `setupTelemetryAsync()` and the first `getLogger()` in a process that never
  called setup now apply it. An unset or blank variable leaves the current
  level alone — it used to reset consent to `FULL`, discarding a
  `setConsentLevel()` made in code — and a level set after setup is never
  overwritten.
- **Truncate mode counts Unicode code points and defaults to 8.** A rule
  registered without `truncateTo` keeps 8 code points (was 8 already, but the
  limit is now shared with the other SDKs as one contract); `0` keeps nothing
  but the suffix and a negative limit clamps to `0`. Counting and slicing moved
  from `String.prototype.slice` to code points, so a limit can no longer split
  a surrogate pair and leave half an emoji in a log record.
- **`hash` mode digests the RFC 8785 canonical JSON of a non-string value** —
  the same text `canonicalJson` produces for receipts — instead of
  `String(value)`. An object therefore hashes its key-sorted JSON rather than
  `"[object Object]"`, and every SDK produces the same digest for the same
  value. Strings and integers are unchanged. `canonicalJson` moved to its own
  module (`src/canonical-json.ts`) and is still re-exported from `receipts`.

### Changed

- **`PROVIDE_CONSENT_LEVEL` fails closed on a value it does not recognise.**
  A set, non-empty value other than `FULL`, `FUNCTIONAL`, `MINIMAL` or `NONE`
  (trimmed, case-insensitive) sets consent to `NONE` — overriding any level
  chosen in code — and warns once per process through `console.warn`, naming
  the raw value. The warning deliberately bypasses the SDK's own logger, so
  the `NONE` it just applied cannot drop it. Unset and blank (empty or
  whitespace-only) remain no-ops, so `PROVIDE_CONSENT_LEVEL=` in a compose
  file still changes nothing. An unrecognised value used to be ignored, which
  left a misspelled opt-out (`PROVIDE_CONSENT_LEVEL=NOEN`) collecting at
  `FULL`. `resetConsentForTests()` also re-arms the once-per-process warning.

## [0.8.0] — 2026-08-19

### Breaking

- **`log` is now a required member of the exported `Logger` interface.** Any
  consumer that implements `Logger` — a test double, a fake, an adapter —
  fails to compile with `TS2741: Property 'log' is missing`. Take the logger
  from `getLogger()` instead, or add a `log` member. It is required rather than
  optional so `logger.log(level, obj, msg)` needs no `?.` guard at the call
  site, which is the whole point of the method.

- **The `level` field on a record is a canonical string, not a pino number.**
  Records carried `40`, `50`, `60`; they now carry `"WARN"`, `"ERROR"`,
  `"CRITICAL"`, matching the other four ports. Anything reading the numeric
  level must be updated.

### Added

- `LogSeverity`, `parseLevel`, `tryParseLevel`, `levelOrder`, `severityName`,
  `pinoLevelName`, `toPinoLevel` and `severityFromPino`.
- `Logger.log(level, obj, msg?)`, on both `getLogger()` loggers and the
  module-level `logger`.

### Fixed

- **`PROVIDE_LOG_LEVEL=WARNING` crashed at logger construction.** The raw value
  was lowercased and handed to pino, whose vocabulary is
  `trace|debug|info|warn|error|fatal`, so `WARNING` and `CRITICAL` — both
  listed as applicable to TypeScript in `spec/telemetry-api.yaml` — threw
  `default level:warning must be included in custom levels`.
  `PROVIDE_LOG_MODULE_LEVELS` had the same fault at a second site.
- **TRACE records no longer go through `console.trace()`**, which prepends
  `"Trace: "` and appends a stack dump, leaving the line unparsable as JSON.
  They use `console.debug`.

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

### Changed

- **BREAKING: receipts are canonically hashed and actually HMAC-signed.**
  The signature was `sha256("key|payload")` — a length-extendable keyed
  digest, not an HMAC — and could not reproduce any cross-language vector.
  It is now real HMAC-SHA256 (RFC 2104, checked against RFC 4231 vectors),
  and `original_hash` is SHA-256 over RFC 8785 canonical JSON, so every
  previously issued receipt verifies differently. `HealthSnapshot` gains
  `receiptFailures` (25 → 26 fields), and enabling receipts without a sink
  throws `MissingReceiptSinkError` instead of silently discarding the audit
  trail.
- **BREAKING: `reconfigureTelemetry` throws when telemetry is not set up.**
  It previously fell back to the environment and performed an implicit
  first-time setup — reporting `setupDone` with no providers registered, the
  exact state `requireActiveConfig()` already refused for
  `updateRuntimeConfig`.

### Fixed

- **Concurrent requests shared log context and trace IDs in the published
  ESM package.** `context.ts` and `tracing.ts` acquired `AsyncLocalStorage`
  with a bare `require()` at module scope; the package declares
  `"type": "module"`, so in the shipped artifact the `require` was
  undefined, the try/catch swallowed the `ReferenceError`, and both modules
  fell back to one module-level store. Vitest and tsx load the package as
  CJS and could never see it; a packed-tarball test now pins the ESM
  behavior.
- **A custom secret pattern with a `g`/`y` flag alternated between detecting
  and leaking** the same secret on consecutive calls (`RegExp.test` advances
  `lastIndex`). Patterns are stored as stateless clones.
- **Baggage keys are RFC 7230 tokens.** A newline inside an inbound baggage
  key split one console log line into two, letting a remote caller fabricate
  a log record. `parseBaggage` rejects non-token keys and strips control
  characters from values; `hardenInput` hardens keys as well as values.
- **`tracestate` is validated against the W3C list-member grammar**; one bad
  member discards the whole header instead of forwarding CRLF to the next
  hop.
- **Facade defects:** `flush()` reported success for signals with no
  provider installed (`[].every()` is vacuously true) and now reports
  per-provider outcomes; a synchronously throwing `forceFlush` no longer
  skips that provider's `shutdown()`; `shutdown()` set STOPPING/STOPPED in
  the inverted order; `getTracer(name)` discarded the name, collapsing every
  span into one instrumentation scope; `shutdown(timeoutMs)` now forwards
  the deadline it accepted; `getLogger`/`getMeter` accept the documented
  no-argument form again.
- **Credentialed OTLP endpoints are accepted** — the userinfo colon in
  `https://user:pw@collector.example` was read as an empty-port separator
  and the endpoint refused.

### Added

- **`async_blocking_risk` counters move.** The synchronous span of a
  provider's `forceFlush`/`shutdown` is measured against the 50ms long-task
  threshold; time a returned Promise spends pending is socket wait and is
  not counted.
- **Propagation fuzzing** via fast-check over traceparent/tracestate/baggage
  with the shared cross-language invariants (no throw on any bytes, hex
  all-or-nothing ids, token keys, control-free values).

## [0.6.0] — 2026-07-29

### Added

- **`flushTelemetry(timeoutMs?)`** — drain without teardown. `shutdownTelemetry()` was the only way to force records out, and it disables the OTel globals and clears provider state on the way. `flushTelemetry` force-flushes each registered provider under the same bounded deadline (`exporterLogsShutdownTimeoutMs`, overridable per call) and leaves everything installed, so it is safe to call at a request boundary or before a serverless freeze. Resolves `false` when any provider missed the deadline; rejects if a `forceFlush` that arrived in time rejected, rather than reporting a broken exporter as drained.

### Fixed

- **`getRuntimeStatus()` reports providers from the config the emit paths read** — it gated the provider probes on the env-resolved config while `withTrace` reads `getConfig()`, which is still the built-in defaults until `setupTelemetry()` loads the environment. With `PROVIDE_TRACE_ENABLED=false` set but no setup call, status claimed traces were in fallback while `withTrace` went on exporting through a host application's provider. `providers.*` now answers "what would the emit path do" and `signals.*` answers "what was configured" — the same split Python and Go use, spec'd as `behavioral_parity.provider_adoption_reporting`.
- **OTLP log export never happened.** `BatchLogRecordProcessor` takes `{ exporter }`; it was given the exporter positionally, leaving the processor with no exporter and discarding every record — no throw, no warning, and `providers.logs` still reporting `true`. Traces and metrics were unaffected, so the package looked healthy on every signal but the dead one. The integration test asserted only `providers.traces`, and the two unit tests asserted the positional call against a mocked SDK; all three now pin the real contract.
- **Trace sampling defers to any live provider, not only ours** — `withTrace` skipped its own probabilistic gate when a "traces provider installed" flag was set, but the flag was set in exactly one place: `registerOtelProviders()`. It therefore meant "we installed a provider", not "a provider is installed". A host application running its own NodeSDK owns the OTel globals without ever calling `registerOtelProviders()`, so `trace.getTracer()` resolved that foreign provider and exported spans while the flag stayed `false` — the facade's sampler then stacked on top of the SDK's, giving `facadeRate x sdkRate` instead of the configured rate, with nothing to indicate it. Latent at the default rate of `1.0`; it dropped spans as soon as `PROVIDE_TRACE_SAMPLE_RATE` was lowered. `withTrace` now probes the global tracer provider (`src/otel-probe.ts`), so a provider anyone installed counts.
- **`getRuntimeStatus()` reports traces and metrics from the globals, not from install flags** — same root cause on both signals: with a host-owned provider, health output reported the signal as running in fallback while it was exporting. Metrics never had a sampling consequence (OTel metrics carry no SDK-side sampler, and `counter()`/`histogram()` already resolved their meter off the global API), so this was a pure misreport there. `providers.logs` remains install-flag-derived: the logs API lives in the optional `@opentelemetry/api-logs` peer, which cannot be imported synchronously to probe.

---

## [0.5.3] — 2026-07-28

### Fixed

- **The published package is loadable from Node** — `dist` was emitted with `moduleResolution: "bundler"` into a package declaring `"type": "module"`, so it shipped extensionless relative specifiers and every Node consumer failed at the first import with `ERR_MODULE_NOT_FOUND`. Now compiled with `nodenext`, with explicit `.js` on all 137 relative specifiers in `src`.

### Added

- **`ci/verify-npm-consumer-package.sh`** — imports the packed tarball from a real Node process, in both CI and the release path. Lint, typecheck and the full vitest suite resolve like a bundler and cannot catch this class of break.

---

## [0.5.2] — 2026-07-12 _(reconstructed)_

### Fixed

- **Optional OTel imports are no longer statically resolved by bundlers** — the dynamic imports guarding optional OpenTelemetry packages were being followed at build time, so a consumer that had not installed them got a resolution failure instead of the no-op path.

---

## [0.5.1] — 2026-07-10 _(reconstructed)_

### Fixed

- **SDK-level trace sampling is real** — the default `TracerProvider` is built with `ParentBased(TraceIdRatioBased(effective_rate))`. Previously the configured rate gated only the library facade (`withTrace` / `shouldSample`) while the global tracer and any instrumentation sampled at 100%.

### Changed

- React dev stack moved to 19 (`react`, `react-dom`, `@types/react`).
- `vite` pinned below 8.1 — its decorator-transform regression broke the build.

---

## [0.5.0] — 2026-07-05 _(reconstructed)_

### Added

- **`OTEL_RESOURCE_ATTRIBUTES` and `OTEL_SERVICE_NAME` are honored** when building the OTel resource, matching the Go implementation.
- **Provenance-layered resource precedence** — resource attributes carry where they came from, and later layers override earlier ones by a documented ladder rather than by merge order.

### Tests

- A cross-language parity test locks the resource-precedence ladder so the layering cannot drift between Go and TypeScript.

---

## [0.4.8] — 2026-06-10 _(reconstructed)_

### Changed

- Version bump and a wholesale dependency refresh (`package-lock.json` regenerated). No source change beyond the exported version constant.

---

## [0.4.7] — 2026-05-24 _(reconstructed)_

### Changed

- Version-parity release for TypeScript: the fix in this version was in the Go package (swallowing a library-applied `DeadlineExceeded` on shutdown). The npm package changed only its version constant and lockfile.

---

## [0.4.4] — 2026-05-03 _(reconstructed)_

### Fixed

- **`npm ci` is reproducible again** — `package-lock.json` had been dropped from the package and was restored.
- Three publish-pipeline fixes landed in the same release.

### Quality

- Coverage gate restored in the TypeScript CI job.
- Stryker survivors killed in `runtime.ts` and elsewhere, via direct array assertions rather than pragmas.
- Dev-dependency refresh across all four languages.

---

## [0.4.3] — 2026-04-24

### API Alignment

- **Canonical sanitizer export** — `sanitize` is exported from the package root and implemented by `pii`; no separate sanitizer module is shipped.

### Reliability

- **OTLP shared endpoint expansion** — shared OTLP endpoints resolve to `/v1/traces`, `/v1/metrics`, and `/v1/logs`, with trailing slashes normalized.
- **Lazy logger sampling** — environment log sampling is applied before explicit setup.
- **PII path specificity** — exact custom rules no longer exempt unrelated default-sensitive keys.

### Quality

- Added regression coverage for lazy sampling, PII rule specificity, sanitizer exports, and OTLP endpoint resolution.

---

## [0.4.2] — 2026-03-29 — never published to npm

### Tests

* **ts:** assert exact ANSI codes, SKIP_KEYS completeness, and msg fallback ([8c135eb](https://github.com/provide-io/provide-telemetry/commit/8c135eb))
* **ts:** anchor case-fold test with exact hash to kill toUpperCase mutation ([19affde](https://github.com/provide-io/provide-telemetry/commit/19affde))
* **ts:** assert exact fingerprint values to kill mutation survivors ([9ef4d82](https://github.com/provide-io/provide-telemetry/commit/9ef4d82))
* **ts:** add Stryker disable pragma for otel covered-0 survivors ([d979aba](https://github.com/provide-io/provide-telemetry/commit/d979aba))

---

## [0.4.1] — 2026-03-28 — never published to npm

### Features

* **typescript:** add error fingerprinting and session correlation with 100% coverage ([6769ed7](https://github.com/provide-io/provide-telemetry/commit/6769ed7))
* **typescript:** add pretty ANSI log renderer with color support and TTY detection ([add0cc2](https://github.com/provide-io/provide-telemetry/commit/add0cc2))
* **typescript:** add conditional exports for browser/edge OTel no-op stub ([c0f0879](https://github.com/provide-io/provide-telemetry/commit/c0f0879))

### Bug Fixes

* **typescript:** remove workerd/edge-light from otel no-op (Cloudflare/Vercel support OTel natively) ([880bfee](https://github.com/provide-io/provide-telemetry/commit/880bfee))

### Tests

* **typescript:** add otel-noop coverage test ([2f93d6b](https://github.com/provide-io/provide-telemetry/commit/2f93d6b))
* **typescript:** kill surviving mutants in backpressure, cardinality, resilience ([eb8ee9b](https://github.com/provide-io/provide-telemetry/commit/eb8ee9b))

---

## [0.4.0](https://github.com/provide-io/provide-telemetry/compare/telemetry-v0.3.0...telemetry-v0.4.0) (2026-03-28) — never published to npm


### Features

* add memray memory profiling infrastructure and optimize hot paths ([648177c](https://github.com/provide-io/provide-telemetry/commit/648177c7394591841cefabdf132304c4a2fdea78))
* **browser-e2e:** add Vite-served browser tracer page and proxy config ([e0bbdc3](https://github.com/provide-io/provide-telemetry/commit/e0bbdc3a5bb6deb3aa75ede51a3e784884f44937))
* enterprise hardening — governance, releases, supply chain, ops ([d42ce5a](https://github.com/provide-io/provide-telemetry/commit/d42ce5a11874e3e25aec184ba43995f7c0feb7a7))
* polyglot spec infrastructure for multi-language support ([a5711af](https://github.com/provide-io/provide-telemetry/commit/a5711af396c9da2517e31815587ce70612b828bd))
* **typescript:** add TypeScript package with 100% mutation score ([d70527f](https://github.com/provide-io/provide-telemetry/commit/d70527f8136504a0533ddd53271c58af3e443235))
* **typescript:** implement shutdownTelemetry with full OTel provider drain ([0a740f7](https://github.com/provide-io/provide-telemetry/commit/0a740f723e1dcc2bab5321eba3f96e38c3c4ea39))
* **version:** transition to shared major.minor versioning with per-language patch ([48c8728](https://github.com/provide-io/provide-telemetry/commit/48c87284e845ba3cf1df1d5e2d09ce4c0723d28d))


### Bug Fixes

* address PR review feedback — lock file sync, parser robustness, exception narrowing, license link ([fb6428a](https://github.com/provide-io/provide-telemetry/commit/fb6428a4a2d06a910c977f8eb2a0b2b0904cfee4))
* lint errors, 100% coverage, exclude stryker sandbox from v8 coverage ([02cfe3b](https://github.com/provide-io/provide-telemetry/commit/02cfe3b90e8bc43504e79eb4058811efa2e567f1))
* remove stale eslint-disable directives, bump perf threshold for CI, update happy-dom ([dc1bbdf](https://github.com/provide-io/provide-telemetry/commit/dc1bbdfa9a0f32c88cb1bd1630568ba0223a05e2))
* three bugs in telemetry logger — static isBrowser, stale cfg, Node.js write hook ([59e076d](https://github.com/provide-io/provide-telemetry/commit/59e076d0cd4ee159873c4c98484c5b8733583bd8))


### Tests

* **e2e:** browser distributed trace linkage via Playwright + Vite proxy ([0075d5a](https://github.com/provide-io/provide-telemetry/commit/0075d5af8ee75a62b6cd464bf9e749f1e4a2d9c9))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([61611c8](https://github.com/provide-io/provide-telemetry/commit/61611c859d8c09df8ff2835d6ca85fe26facb5af))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([1bada42](https://github.com/provide-io/provide-telemetry/commit/1bada42f39e7b7bd422aa640b8341e3bf5329ffd))
* **ts:** add full coverage and mutation tests for otel.ts ([e5187eb](https://github.com/provide-io/provide-telemetry/commit/e5187ebb273453097c746e5125a08bd17429d408))
* **ts:** kill window typeof-check mutation survivors in node env ([125f561](https://github.com/provide-io/provide-telemetry/commit/125f561fab0099fdf33e69959fa04c3fde0a69ee))
* **typescript:** kill config.ts logFormat string mutation with empty-string test ([4a765cf](https://github.com/provide-io/provide-telemetry/commit/4a765cf83c798fe10835ec21826e657c95734d6f))
* **typescript:** kill surviving mutants in backpressure, cardinality, resilience ([eb8ee9b](https://github.com/provide-io/provide-telemetry/commit/eb8ee9ba6ecb7557c5276f5ca677e07214c7c536))

---

## [0.3.0] — 2026-04-12 _(reconstructed)_

### Added

- **`guardAttributes` and strict-schema accessors** — `setStrictSchema` / `getStrictSchema`, added to the spec and to all four languages.

### Quality

- Emitted-counter assertions added to the TypeScript CI job.
- Mutation survivors killed and a branch-coverage gap closed.

---

## [0.2.6] — 2026-04-10 _(reconstructed)_

### Changed

- Version-parity release for TypeScript: the fix in this version was in the Go package (an `RWMutex` around logger global state, to eliminate a data race). The npm package changed only its version constant.

---

## [0.2.4] — 2026-04-08

### Features

- **`registerSecretPattern`** — register custom secret detection patterns with name-based deduplication
- **Benchmark suite** — `tests/performance/benchmark.test.ts` with 12 vitest performance tests; `npm run test:bench`
- **Stress tests** — 3 new scripts (sampling, PII, tracing); `npm run stress` runs all 6

### Bug Fixes

- **`emitted_*`/`dropped_*` always 0** — added health counter calls to `shouldSample` and `tryAcquire`
- **Browser crash on import** — `receipts.ts` replaced Node.js `crypto` with pure-JS `hash.ts` (SHA-256, randomHex)
- **macOS v8 coverage** — removed stale `v8 ignore` directives, added test for receipts production-mode path

### Quality

- **100% Stryker mutation kill** (1762 mutants, 0 survivors — was 93.81%)
- 1232 tests, 100% coverage (lines, branches, functions, statements)

---

## [0.2.2] — 2026-04-06 _(reconstructed)_

First version of this package published to npm.

### Added

- **Data governance modules** — classification, consent, receipts, and config masking.
- **`RuntimeOverrides` type**, and config getters that return frozen objects.
- **`randomHex` utility**, plus synthetic trace-ID injection for no-op spans.

### Fixed

- **PII default sensitive keys** aligned to the canonical 17-key list shared with Python.
- AsyncLocalStorage test isolation, and branch-coverage gaps in `tracing`, `config`, `receipts` and `pii`.

### Quality

- 100% Stryker mutation score, with all surviving mutants killed.
