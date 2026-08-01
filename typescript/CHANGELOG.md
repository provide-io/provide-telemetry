# Changelog

Releases of the npm package `@provide-io/telemetry`. The root `CHANGELOG.md`
covers all four languages; this file covers only what shipped to npm.

Two things to know when reading it:

- Entries marked _(reconstructed)_ were written after the fact from git history,
  by diffing each version-bump commit against the previous one. They describe
  what changed, not what the author would have chosen to highlight.
- **0.4.0, 0.4.1 and 0.4.2 were never published to npm.** They predate 0.2.2 in
  time — the project rewound its version number in April 2026 — and are kept
  here in version order, out of chronological order, because that is what a
  changelog is read in. `npm view @provide-io/telemetry versions` is the
  authority on what a consumer can actually install.

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
