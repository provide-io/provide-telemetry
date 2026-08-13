# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
All packages — PyPI `provide-telemetry`, npm `@provide-io/telemetry`,
`github.com/provide-io/provide-telemetry/go`, crates.io `provide-telemetry`,
NuGet `Provide.Telemetry` — share a version number.

---

## [Unreleased]

### Added

- **C# — the fifth SDK.** `Provide.Telemetry` is a dependency-free core
  (`dotnet list package --include-transitive` reports none): logging, tracing,
  metrics, W3C propagation, PII/secret redaction, cardinality guards,
  backpressure, resilience, SLO helpers, governance receipts and the 26-field
  health snapshot, at full parity with the other four languages. OTLP export
  lives in a second package, `Provide.Telemetry.OpenTelemetry` — an application
  calls `OpenTelemetryBackendRegistration.Register()` before setup, exactly the
  side-effect-import pattern Go's `go/otel` module uses. Parity is evidence,
  not intent: C# passes spec conformance, every behavioral-fixture category,
  the cross-language contract harness and the shared receipt/JCS vectors, and
  its canonical log envelope is byte-identical to Python's. It ships with its
  own CI workflow, benchmark suite with seeded perf budgets, a Stryker mutation
  gate that was proven able to fail, and release packaging that produces and
  verifies both `.nupkg`s. First NuGet release.
- **tracestate is now validated against the W3C list-member grammar in every
  runtime.** Python was the only one validating beyond length and pair count,
  so the other four kept — and where applicable forwarded — a header whose
  member carried CRLF or other control characters: header injection at the
  next hop. All five now apply the same grammar (OWS, lcalpha/digit-first key
  of ≤256 chars with multi-tenant `@`, `=`, printable-ASCII value minus comma
  and equals), and one bad member discards the whole header. Pinned by a new
  16-case `propagation_tracestate_grammar` fixture category mirrored into all
  five parity suites.
- **`async_blocking_risk` now moves in every runtime that can detect the
  condition.** It is one of the 26 canonical health fields and could not
  increment in three of five SDKs. Rust detects a blocking drain on a Tokio
  worker via `Handle::try_current()` on the caller's thread; TypeScript
  measures the synchronous span of a provider's `forceFlush`/`shutdown`
  against the 50ms long-task threshold; C# fires on a present
  `SynchronizationContext`. Go provably cannot detect it — a goroutine parked
  in a drain costs one goroutine and blocks nothing — so its incrementer is
  deleted and a test pins all three counters at zero, keeping the field only
  as cross-language contract.
- **Propagation fuzzing in all four established runtimes.** W3C headers are
  the only network-supplied input this library takes, and fuzzing was
  config-focused before. Each runtime now fuzzes
  traceparent/tracestate/baggage with the same invariants: no
  panic/raise/throw on any bytes; parsed ids are well-formed hex, never
  all-zero, and all-or-nothing as a pair; baggage keys are RFC 7230 tokens and
  values carry no control characters. Go's existing fuzz targets were
  strengthened to the same invariants and exercised at 3.3M executions.

### Changed

- **BREAKING: receipts are canonical, and enabling them requires a sink — in
  every language.** Four changes land together:
  - `original_hash` is SHA-256 over RFC 8785 canonical JSON (JCS) instead of
    each language's default stringification (`str(value)`,
    `fmt.Sprintf("%v")`, `Value::to_string()`), so the number `1` and the
    string `"1"` no longer share a digest. Every previously issued receipt
    hashes differently now. Seven shared vectors in
    `spec/receipt_fixtures.yaml` reproduce byte-for-byte — canonical JSON,
    hash, payload and signature — in all five SDKs.
  - TypeScript's signature is real HMAC-SHA256 (RFC 2104, checked against
    RFC 4231 vectors). It was `sha256("key|payload")` — a length-extendable
    keyed digest that could not reproduce any cross-language vector.
  - `HealthSnapshot` gains `receipt_failures` (25 → 26 fields; breaks
    exhaustive struct literals in Go and Rust). Sink delivery sits behind a
    panic/exception boundary and failures are counted, never logged — the
    logger produces redactions and redactions produce receipts, so reporting
    a sink failure through the logger is an unbounded cycle.
  - Enabling receipts without a sink is refused everywhere:
    `enable_receipts(True, key, service)` with no `sink=` and no
    `TelemetryConfig.receipt_sink` raises `MissingReceiptSinkError`
    (`ConfigurationError`) instead of succeeding — an audit trail with no
    destination is a silent no-op, and 0.6's implicit debug-log delivery hid
    exactly that misconfiguration. Go and Rust move to option structs
    (`ReceiptOptions`) because the old positional forms could not carry a
    sink or return an error. Migration is one line for a service whose log
    stream really is its receipt destination:
    `enable_receipts(True, key, service, sink=LoggingReceiptSink())` — the
    new public sink delivers each receipt as one stdlib debug log line
    (id/timestamp/field/action/hash/hmac, never the original value).
    Test-mode behavior (the built-in collector) is unchanged.
- **BREAKING: runtime write paths require a live config.** Python's
  `update_runtime_config`, `reload_runtime_from_env` and
  `reconfigure_telemetry`, and TypeScript's `reconfigureTelemetry`, raise
  `ConfigurationError`/throw when telemetry is not set up, where they
  previously performed an implicit first-time setup from whatever the
  environment happened to hold — and reported setup done with no providers
  installed and no shutdown owed. Go always refused this; C# now does; reads
  (`get_runtime_config`, the drain paths) deliberately keep their fallback.
- **BREAKING (Go): `telemetry.Logger` is now `telemetry.Logger()`**, with
  `SetLogger()` as the write half. The variable could not be both publicly
  assignable and race-free — the race detector reported `_configureLogger`
  reassigning it during reconfiguration while `GetLogger` read it, with the
  `go/otel` module writing it from another package. Both halves now share one
  atomic. Relatedly, Go runtime state is published as immutable generations:
  config plus the logger built from it, swapped under one atomic store and
  never written again, which is what removed six `-race` reports from the
  hot-reload path without putting a mutex on every log call.
- **BREAKING (Rust): the facade takes optional arguments.**
  `setup_telemetry(Option<TelemetryConfig>)`,
  `flush_telemetry(Option<f64>)` and `shutdown_telemetry(Option<f64>)` — there
  was previously no way to inject a config or bound a drain from Rust at any
  layer, capabilities Python, TypeScript and Go all had. The caller's deadline
  threads into the bounded drain and overrides the configured one; shutdown
  drains under it before teardown. `enable_receipts` becomes
  `enable_receipts(ReceiptOptions) -> Result<(), ConfigurationError>`, and the
  receipt timestamp is fixed-width UTC instead of `SystemTime`'s debug format.
- **BREAKING: `ReconfigureResult` has one shape.** It differed in all four
  languages; converged on `applied`/`previous`/`current`/`state`/`error`,
  dropping the `status` field that always duplicated `state`. Go's struct
  gains JSON tags so it round-trips with Rust's serde output.
- **Python: the lifecycle is serialized.** Setup, reconfigure, update, reload
  and shutdown run through one coordinator that publishes immutable
  generations under a condition variable — setup and reconfigure previously
  took different locks over the same state, so a reader could observe a torn
  runtime. Config snapshots deep-copy everything except the receipt sink
  (cloning a sink that holds a socket either delivers receipts to a copy the
  caller never sees, or raises outright).

### Fixed

- **Security: a W3C baggage key from an inbound request could forge a log
  record.** All four established runtimes shared the flaw: `harden_input`
  sanitized values but never keys, and the console renderer (the default
  `PROVIDE_LOG_FORMAT`) quotes values while emitting keys bare — so a newline
  inside a baggage key split one log call into two rendered lines, letting a
  remote caller fabricate an arbitrary log record such as a fake
  `[critical] security.breach` line. Fixed at both layers in each language:
  `parse_baggage` now requires RFC 7230 token keys (which the W3C Baggage spec
  already mandates) and strips control characters from values, and
  `harden_input` hardens keys as well as values. Injection suites now cover
  every untrusted surface: log attributes, OTLP endpoint URLs, W3C headers,
  and PII/secret scanning (ReDoS).
- **Go: OTLP-exported log records now pass through the telemetry pipeline.**
  The OTel log bridge was wired as a sibling of the telemetry handler, not
  downstream of it, so every record exported to a backend bypassed consent,
  schema validation, sampling, backpressure, hardening and PII redaction — a
  password masked as `***` in the local log left the process in the clear on
  the bridge. The bridge now receives what the local sink receives. In the
  same family: PII traversal handled only `map[string]any` and `[]any`, so a
  `[]credentials` or a struct carried its `Password` field to the log
  verbatim; hardening now normalizes typed maps, structs, arrays and slices
  reflectively, with cycles and repeated references collapsing to `"***"`.
  `SecurityConfig`'s three caps, previously parsed and read by nothing, now
  actually bound log attributes.
- **TypeScript: concurrent requests shared log context and trace IDs in the
  published ESM package.** `context.ts` and `tracing.ts` acquired
  `AsyncLocalStorage` with a bare `require()` at module scope; the package
  declares `"type": "module"`, so in the shipped artifact the `require` was
  undefined, the surrounding try/catch swallowed it, and both modules fell
  back to a single module-level store. Vitest and tsx load the package as CJS
  and could never see it; a packed-tarball test now pins the ESM behavior.
- **TypeScript: a custom secret pattern with a `g`/`y` flag alternated
  between detecting and leaking** the same secret on consecutive calls
  (`RegExp.test` advances `lastIndex`). Patterns are stored as stateless
  clones.
- **Credentialed OTLP endpoints are accepted.** Python, Rust and TypeScript
  each read the userinfo colon in `https://user:pw@collector.example` as an
  empty-port separator and refused the endpoint (Go and C# were correct).
  All three strip userinfo before the port scan; both URL forms are pinned in
  the shared behavioral fixtures.
- **Python: two JCS number-rendering bugs collapsed distinct receipts.**
  `1e21` and `1e22` both rendered as `"0.1"` — an exponent-branch bound
  excluded values it was claimed to cover — so `0.1`, `1e21` and `1e22`
  shared one canonical form and one SHA-256, strictly worse than the
  stringification that canonicalization replaced. The bound is restated in
  full, and `spec/jcs_number_fixtures.yaml` now pins 21 vectors (one per
  formatter branch, generated by `JSON.stringify`, cross-checked against
  `rfc8785`) executed by all five SDKs.
- **The facade parity sweep.** A max-effort cross-language review of the
  runtime surface found and fixed, among others: Python's documented
  `get_logger()` raised `TypeError` (name became mandatory during the parity
  work); Go's `UpdateConfig` discarded its config, `Reconfigure` dropped
  config/options/context and re-read the environment, and `Flush` collapsed
  one aggregate error onto all three signals; TypeScript's `flush()` reported
  success for signals with no provider installed, `shutdown()` inverted the
  STOPPING/STOPPED order, and `getTracer(name)` discarded the name,
  collapsing every span into one instrumentation scope; Python and TypeScript
  accepted a `shutdown(timeout)` deadline they never forwarded, so a SIGTERM
  handler's budget did not bound the drain; `ProviderImmutableError` is a
  distinct type in Go (it aliased `ConfigurationError`, so a
  restart-on-immutable handler matched ordinary config errors) and Rust now
  actually produces it.
- **Drain outcomes are honest in every language.** Rust's bounded drains no
  longer panic, a zero budget times out instead of hanging, and an
  in-deadline exporter rejection reports `failed` rather than `timed_out`;
  TypeScript reports per-provider flush outcomes, and a synchronously
  throwing `forceFlush` no longer skips that provider's `shutdown()`; Go's
  `Flush` reports `NotOwned` — never `Flushed` — for a backend without a
  flush interface; Python's `shutdown_telemetry` always runs its resets and
  reaches `STOPPED`, then re-raises the first drain error.
- **Hardening agrees across the five SDKs.** Composite values at the depth
  ceiling collapse to `"***"` everywhere (Python handed them back unchanged —
  an unbounded value returned by the hardening pass is not hardening); map
  and attribute keys are hardened at every depth with shared collision
  semantics; canonical JSON serialization guards against cycles by emitting
  `null` (matching Python) while shared acyclic subtrees still serialize;
  Rust strips exactly the C0/C1 controls the others strip and strips before
  truncating; Python appends the cross-SDK `"..."` truncation marker;
  TypeScript passes `NaN`/`±Infinity` through hardening and canonicalization
  spells them `null`; Python validates all six exporter backoff/timeout
  floats as finite and non-negative, matching the rest.

## [0.6.0] — 2026-07-29

### Added

- **`flush_telemetry` / `flushTelemetry` / `FlushTelemetry` / `flush_telemetry`** — drain without teardown, in all four languages. Until now the only way to be sure records were out was `shutdown_telemetry`, which tears the providers down (and, in Python, resets sampling, backpressure, resilience and runtime policy), so a caller that just wanted a drain at a request boundary, a checkpoint or a serverless freeze had to pay for a full re-setup. Flush force-flushes every provider *we* installed and leaves them installed and usable. The deadline is the existing bounded-shutdown one (`PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS`, 5.0s default) and can be overridden per call; unlike shutdown, an expired deadline is reported rather than swallowed — a caller flushing to be sure its records are out needs to learn when they were not. Python/TypeScript return a boolean, Go returns `error`, Rust returns `Result`. Every signal gets its attempt even when an earlier one is abandoned. Covered by the cross-language contract harness (`flush_drains_without_teardown` in `spec/contract_fixtures.yaml`), which asserts all four agree that flush succeeds, is repeatable, and leaves telemetry working.
- **Provider adoption no longer depends on install order** — the fix above landed with two ordering holes, both closed. Go snapshotted the global during `Setup`, so an auto-instrumentation agent or lazily-initialised vendor distro that registered afterwards was never seen; the global is now probed per span, and the facade tracer is resolved per span too (`_effectiveTracer`) so a late provider is actually emitted through rather than merely reported. Python decided "is this a real provider" by comparing the global against a baseline captured inside `setup_tracing`/`setup_metrics` — which meant a host provider installed *before* our setup was itself the baseline and was mistaken for the API placeholder, the common case for `opentelemetry-instrument` and vendor distros that install ahead of application code. The baseline is gone; both languages now duck-type the `force_flush`/`shutdown` pair, matching TypeScript.
- **Go's shutdown no longer switches off a host's instrumentation** — `Shutdown` reset the OTel globals to no-ops unconditionally, so tearing our telemetry down also unregistered a provider the host had installed, silently stopping its own instrumentation. Only globals this backend registered are reset now.
- **Go and Rust now honour a provider a host application installed** — Python and TypeScript have always emitted through a tracer/meter provider found on the OTel globals; Go used one only when it was handed in via `BackendSetupState`, and Rust never. Go now adopts `otel.GetTracerProvider()` / `GetMeterProvider()` for any signal where it installed nothing of its own, duck-typed on the `ForceFlush`/`Shutdown` pair so the API's delegating placeholder is not mistaken for a live provider. Adoption never implies ownership: `ShutdownTelemetry` drops the reference without tearing the host's SDK down, and `FlushTelemetry` does not drain it. Rust cannot detect a foreign provider at all — `opentelemetry 0.31`'s `global::tracer_provider()` returns an opaque `GlobalTracerProvider` with no downcast and no `is_noop` — so the host asserts it instead, via the new `adopt_global_providers(AdoptedProviders { traces, metrics })`. After that assertion `trace()` routes through `global::tracer(..)` (which already resolves the host's provider) rather than the no-op path, the host's sampler becomes the sampling authority, and `get_runtime_status()` reports the signal as installed. `shutdown_telemetry` releases the assertion without touching the host's providers.
- **Go `WithConfig(*TelemetryConfig)`** — `SetupTelemetry(WithConfig(cfg))` accepts an in-memory config instead of reading process environment. Prefer this for hosts that re-exec or fork and must not mutate `os.Environ` to configure telemetry.

### Fixed

- **A disabled signal is never reported or treated as having a provider** — the live-provider probes answered "is one in play" without the disablement check the emit paths make first. In Python that let `@trace` skip facade sampling for spans `get_tracer()` then served from a no-op tracer: nothing exported, but counted as emitted and holding a backpressure ticket, so health showed 100% of calls emitted at a configured 1% rate. Go's variant was worse-shaped — enablement was snapshotted inside the OTel backend's `Setup`, which `_setupBackendLocked` skips entirely on the endpoint-less (pure-adoption) path, so the flags went stale in both directions and adoption died permanently after one shutdown/re-setup cycle. Enablement is now read live from the runtime config that owns it (`telemetry.TracingEnabled`/`MetricsEnabled`), and TypeScript's `getRuntimeStatus` gates on it too.
- **Flush reports failure honestly in every language** — three different mistakes, one per language. Python's `flush_telemetry` evaluated its signals left to right, so an exporter raising in the first aborted the other two drains and escaped a function documented to return `bool`; each signal is now attempted independently and a raised error is logged with its signal name and reported as a failed drain. Go shared one context deadline across all three `ForceFlush` calls in sequence, so a stalled traces exporter consumed the whole budget and metrics and logs returned `DeadlineExceeded` without exporting anything; the three now drain concurrently, each with the caller's full budget. Rust discarded `force_flush()` results with `let _ =`, so a drain that failed promptly still returned `Ok(())` — the exact misreport the API exists to prevent.
- **Repeated flushes cannot exhaust the process's threads** — the bounded-drain helper abandons its worker at the deadline, which is fine for `shutdown_telemetry` (once per process) and not for `flush_telemetry` (documented for per-request use). Against an unreachable collector every call stranded another thread in the exporter's retry loop until interpreter exit. Workers still running past their deadline are now capped at 8, and past that a *flush* declines immediately and reports failure rather than adding to the pile. Only abandoned workers count against the budget — drains still inside their deadline are running normally and give their slot back — and `shutdown_telemetry` is never declined, because it runs once at exit and is the last chance to get queued records out.
- **Go: no data race on the per-span provider lookup, and no lock held across a flush** — resolving the tracer per span moved reads of the setup-time globals onto the hot path while setup and shutdown wrote them under `_setupMu`. The instrumentation-scope name is now atomic and the OTel backend's provider globals have their own `RWMutex`. Separately, `FlushTelemetry` held `_setupMu` for the whole drain, and every `Trace()` and metric call takes that same mutex — a slow collector stalled the entire process for the deadline. It now snapshots under the lock and drains outside it.
- **Go: `FlushTelemetry`'s godoc is its own** — the declaration sat directly under `ShutdownTelemetry`'s comment block with no blank line, so `go doc` attributed shutdown's contract (which suppresses an expired deadline) to flush (which deliberately does not), and left `ShutdownTelemetry` undocumented.
- **SDK-level trace sampling is real across all four languages** — the default OTel `TracerProvider` is now built with `ParentBased(TraceIdRatioBased(effective_rate))` where `effective_rate = min(sampling.traces_rate, tracing.sample_rate)`. Previously the rate only gated the library facade (`Trace` / `withTrace` / `should_sample`) while the global tracer and instrumentations (e.g. gRPC) always sampled at 100%. Rate `0` drops root spans; rate `1` samples all. When a live provider is installed the facade skips its probabilistic gate so spans are not double-sampled.
- **Python: the sampling bypass and runtime status ask the same question the tracer does** — `_has_live_tracing_provider()` / `_has_live_meter_provider()` answer "did *we* install one". That is the right question for the reconfiguration guard and the wrong one everywhere else: `get_tracer()` / `get_meter()` already resolve a provider a host application installed on the OTel global, so spans and measurements flowed through it while `@trace` still applied the facade's probabilistic gate on top (facade_rate x sdk_rate) and `get_runtime_status()` reported the signal as running in fallback. Both consumers now use `_has_effective_tracing_provider()` / `_has_effective_meter_provider()`, which delegate to the very predicate the tracer and meter gate on, so they cannot disagree. `providers["logs"]` stays install-scoped: our records reach OTel through the handler *we* attach, so a foreign logger provider is genuinely not in our path.
- **TypeScript: "a live provider is installed" is now probed, not remembered** — the double-sampling guard above read a flag that only `registerOtelProviders` ever set, so it answered "did *we* install a provider", not "is one installed". A host application whose own SDK owns the OTel globals got `facadeRate x sdkRate` and `getRuntimeStatus()` reported traces as running in fallback while spans were exporting. `withTrace` and `getRuntimeStatus` now probe the global tracer provider instead; `getRuntimeStatus` probes the global meter provider the same way (status only — metrics have no SDK-side sampler to double up with).
- **`providers` and `signals` in runtime status now mean two different things, identically in all four languages** — `providers.*` answers "would a record emitted right now reach a real SDK provider", which is what the emit paths ask, so a provider a host application installed on the OTel globals counts and a signal reads as fallback only once a *loaded* config switches it off. `signals.*` answers "what did the operator configure", from the effective config (the active config once setup has run, the environment before that). The three facades had drifted: before setup, TypeScript gated the provider probes on the environment while its own `withTrace` did not, and Rust ignored enablement entirely — a host that adopted a provider and then set up with tracing disabled still saw `providers.traces: true`. The rule is now spec'd as `behavioral_parity.provider_adoption_reporting` and enforced across all four by the `host_provider_adoption` runtime-probe case. `providers.logs` stays install-scoped everywhere.
- **Go adopts a host application's provider before `SetupTelemetry` has run** — gating adoption on the runtime config meant the gate was shut until setup, so an app that installed its own SDK on the OTel globals and never called `SetupTelemetry` had every span started on the no-op tracer while `GetRuntimeStatus()` counted them as emitted. The gates now default open and close only when a loaded config switches the signal off, which is what `Trace()` has always done.
- **Go's `ShutdownTelemetry` drains the three signals concurrently** — they shared one context deadline in sequence, so a stalled traces exporter consumed the whole budget and queued metrics and log records were dropped without an export attempt. This is the same fix `FlushTelemetry` already had; both now run through one drain path, so they cannot diverge again.
- **Python reports an incomplete flush as a failure** — OTel's `force_flush()` returns `False` when it gave up with records still queued, and the return value was discarded, so `flush_telemetry()` reported success for a lossy drain. That is the exact failure a caller flushing before a serverless freeze is asking about, and it disagreed with Rust, where the same drain already returned false.
- **Go: an expired flush deadline survives an `==` comparison** — `FlushTelemetry`'s godoc promises `context.DeadlineExceeded`, but the OTel backend joined its per-signal errors unconditionally and `errors.Join` wraps even a single error, so `err == context.DeadlineExceeded` silently stopped matching. A lone failure is now returned untouched; only genuinely multiple failures are joined.
- **TypeScript OTLP log export never happened.** `BatchLogRecordProcessor` takes an options object — `{ exporter }` — and it was handed the exporter positionally, so `options.exporter` was `undefined` and the processor discarded every record. Silently: no throw, no warning, `getRuntimeStatus().providers.logs` still reported `true`, the provider was registered on the OTel global, and `emit()` returned normally. Traces and metrics were unaffected (`BatchSpanProcessor` is still positional; `PeriodicExportingMetricReader` already used the options form), so TypeScript looked healthy on every signal but the one that was dead — a real parity break against Python, Go and Rust for as long as it was present. Two things let it hide: the collector-backed integration test asserted only `providers.traces`, and the two unit tests covering this wiring asserted the *positional* call against a mocked SDK, pinning the bug instead of catching it. All three now assert the real contract. The cross-language parity harness could not have caught it either — its contract probes carry no SDK dependency by design, so they check facade behaviour, not bytes reaching a collector.

### Removed

- **`go/tracer`** — a standalone parallel copy of the tracer machinery (`DefaultTracer`, `GetTracer`, `Trace`, a no-op tracer) that nothing imported, carrying its own unsynchronized exported global. Its CI test and mutation steps were guarded on `hashFiles('go/tracer/go.mod')` and that module file never existed, so they had never run; `check_version_sync` likewise read a `go/tracer/VERSION` that was not there. Use the root `telemetry` package.

### Changed

- **Go: `DefaultTracer` is no longer an exported variable** — the binding is read from every traced call and written during setup and shutdown, and a two-word interface value read while it is being written can tear. It is now an atomic behind `GetTracer(name)` (read) and the new exported `SetDefaultTracer(t)` (replace), which is both race-free and ~20ns/span cheaper than the mutex that guarding an assignable exported var would have required. The spec's "tracer instance" symbol is satisfied by the exported `Tracer` type, as before.

### Dependencies

All four languages moved to the latest versions their constraints allow, plus
these direct-dependency majors: Rust `thiserror` 1→2, `base64` 0.22→0.23,
`criterion` 0.5→0.8, `rstest` 0.25→0.26; TypeScript `@types/node` 25→26 and the
OTLP exporters 0.220→0.221; Go module dependencies refreshed (`go get -u` +
`go mod tidy`, which also dropped `go.opentelemetry.io/otel/trace` from the root
module — its only importer was the deleted `go/tracer`).

Four upgrades were attempted and deliberately held back, each a real migration
rather than a version bump:

- **Rust `opentelemetry` 0.31 → 0.32** (and the `-otlp` / `_sdk` /
  `-semantic-conventions` / `tracing-opentelemetry` family that must move with
  it). The processor traits changed the signatures of `shutdown`,
  `shutdown_with_timeout` and `force_flush`, and `Protocol::HttpJson` no longer
  exists. Six compile errors; needs a migration, not a bump.
- **Rust `hmac` 0.13 / `sha2` 0.11.** The RustCrypto next-generation release
  swaps `generic-array` for `hybrid-array`, so `Hmac::new_from_slice` is gone
  and the digest output no longer implements `LowerHex`.
- **TypeScript 7.** The native compiler port relocates the compiler API that
  `tests/propagation.module-scope-await.test.ts` uses to assert no module-scope
  `await`; every `ts.*` AST helper resolves to the wrong module.
- **Vite 8.1.** Fails to transform `tests/tracing.test.ts` with a bare
  `SyntaxError: Invalid or unexpected token`, while `tsc` and ESLint both accept
  the file. Pinned to `~8.0.16`.

One known advisory remains: `qs` (moderate, DoS) reaches the tree through
`@stryker-mutator/core` → `typed-rest-client`. Dev-only, never shipped, and not
resolvable by `npm audit fix` — it needs an upstream Stryker release.


---

## [typescript/0.5.3] — 2026-07-28

TypeScript only. Python, Go and Rust remain on 0.5.1 — language patch versions
drift independently (see `release.yml`; only major.minor must match `VERSION`).

### Fixed

- **The published package is loadable from Node** — `dist` was emitted with `moduleResolution: "bundler"` into a package declaring `"type": "module"`, and `tsc` never rewrites specifiers on emit, so it shipped `import './config'` with no extension. Every Node consumer failed at the first import with `ERR_MODULE_NOT_FOUND`; only bundlers could resolve it. The compiler is now `nodenext` and all 137 relative specifiers in `src` carry an explicit `.js`.

### Added

- **`ci/verify-npm-consumer-package.sh`** — packs the tarball, installs it into a throwaway project and imports every entry point from a real Node process. Nothing already in the pipeline could catch the above: lint, typecheck and the 1666-test vitest suite all resolve like a bundler and were green throughout. Runs in `ci-typescript.yml` and in `release.yml`'s `build-npm`, before the tarball can be uploaded.

## [typescript/0.5.2] — 2026-07-12

TypeScript only.

### Fixed

- **Optional OTel dynamic imports resolve for bundler consumers.**

---

## [0.5.1] — 2026-07-10

### Added

- **Go coverage-guided fuzz targets** — `go/fuzz_test.go` fuzzes OTLP header parsing, endpoint URL masking, sample-rate validation (including NaN/Inf rejection), and signal endpoint URL validation. Local continuous fuzz via `make -C go fuzz` and GitHub Actions `ci-go-fuzz.yml`. Local OSS-Fuzz libFuzzer builds via `./scripts/oss-fuzz-local.sh` (Google cloud onboarding shelved).

### Fixed

- **Go `validateRate` rejects NaN and Inf** — previously a bare range check accepted NaN (`NaN < 0` and `NaN > 1` are both false), so a `PROVIDE_*_SAMPLE_RATE=NaN` env value could pass config load. Matches the library's cross-language "rate in [0,1]" contract.

## [0.5.0] — 2026-07-05

### Added

- **OTel `Resource` attribute provenance — `OTEL_RESOURCE_ATTRIBUTES` / `OTEL_SERVICE_NAME` honored across all four languages** — every emitted trace, metric, and log now carries a resource built on a single, cross-language precedence ladder: **framework default < `OTEL_*` env < explicit config**. An identity attribute (`service.name` / `deployment.environment` / `service.version`) joins the top layer only when its configured value differs from the framework default, so an explicitly named service is never hijacked by an ambient `OTEL_RESOURCE_ATTRIBUTES` (e.g. a platform-injected `service.name`), while `OTEL_SERVICE_NAME` still fills an *unset* service name. Additive env keys (`host.name`, `service.instance.id`, `k8s.*`, …) always merge, so callers can attach deployment metadata without a custom provider. Previously Go and TypeScript ignored these env vars entirely (the resource was built from config only); Python and Rust honored env but with different precedence. The shared contract is pinned by the `resource_precedence` fixture in `spec/behavioral_fixtures.yaml`. See `docs/CONFIGURATION.md` → *Resource Attributes*.

### Changed

- **`deployment.environment` resource key unified across languages** — Rust previously emitted the newer, experimental `deployment.environment.name`; it now emits `deployment.environment`, matching Go, Python, and TypeScript. A cross-language query on `deployment.environment` now covers every service. **Dashboards/alerts filtering Rust telemetry on `deployment.environment.name` must switch to `deployment.environment`.**
- **Python providers now emit `deployment.environment`** — the trace and metric providers previously set only `service.name` and `service.version`; the deployment environment is now included, at parity with the other languages.
- **OpenObserve dev/E2E image → `v0.91.1`** (from `v0.14.5`) across `docker-compose.yml`, `scripts/start-openobserve.sh`, and the `setup-openobserve` CI action. The start script now uses a named Docker volume (avoids a Docker Desktop for macOS bind-mount failure) and waits on `/healthz`. Note: OpenObserve ≥ v0.91 enforces root-password complexity (lowercase + uppercase + digit + special).

---

## [0.4.8] — 2026-06-10

### Added

- **`provide.telemetry.span()` — block-level span context manager** — `with span("area.verb", **attrs): ...` opens a span around an arbitrary code block, the counterpart to the `@trace` decorator for code that isn't a whole function. It shares the *exact same* lifecycle as `@trace` via a single internal helper (`_open_span`): consent → sampling → backpressure → health counting → OTel↔contextvars correlation (so logs emitted inside the block carry the span's trace/span IDs) → context restore + ticket release. A plain `with` works inside `async def` — the cross-context detach is handled by the runtime context from setup, not by the context manager's shape. Attributes are coerced (`None` dropped, primitives and sequences of primitives passed through, everything else stringified). Companions **`set_attrs(span, **attrs)`** (set attributes mid-block once values are known) and **`record_exception(span, exc)`** (record a failure and mark the span ERROR without re-raising) are exported alongside it. All three no-op safely when tracing is disabled.

### Fixed

- **OpenTelemetry "Failed to detach context" storm in async services** — a span whose `start_as_current_span` lifetime straddles an async-context boundary (an async generator `aclose()`d from another task, a cancelled or garbage-collected coroutine) detaches its contextvars Token in a different `Context` than it was created in, so `opentelemetry.context.detach` logged a full traceback *per occurrence* (long-running async servers saw thousands). `setup_tracing()` now installs `_SafeContextVarsRuntimeContext`, a runtime context whose `detach` swallows *only* that benign cross-context `ValueError` (the owning context is already being abandoned, so there is nothing to reset) and behaves identically otherwise. Applies to every span — decorator, manual, or library-created — with no consumer code change.
- **OTel 1.42 `LogExportResult` deprecation** — the resilient log-exporter wrapper resolved `LogExportResult` by static import; OpenTelemetry 1.42 deprecated it in favour of `LogRecordExportResult`. It is now resolved via the SDK module namespace (new name preferred, old name as fallback), preserving the `opentelemetry-sdk>=1.27` floor while silencing the deprecation on newer SDKs.

### Dependencies

- **Cross-language dependency refresh** — all four language packages updated to the latest versions permitted by their existing constraints. Python (`opentelemetry` 1.41.1 → 1.42.1, `structlog` 25.5 → 26.1, plus tooling); Go (`go.opentelemetry.io/otel` 1.43 → 1.44, `otel/log` 0.19 → 0.20, `grpc`/`golang.org/x/*`); Rust (`tonic`, `tower-http`, `wasm-bindgen`, `serde_json`, et al. via `cargo update`); TypeScript (within-range `npm update`).

---

## [0.4.7] — 2026-05-24

_Reconstructed from git history — this release shipped without a changelog entry._

### Fixed

- **Go: a library-applied `DeadlineExceeded` is swallowed on shutdown** — the bounded shutdown path treated its own deadline as a caller-visible error.

The TypeScript and Rust packages moved for version parity only.

---

## [0.4.4] — 2026-05-03

### Release pipeline fixes

- **TypeScript: realign peer dep ranges with installed versions** — `@opentelemetry/api-logs` and `@opentelemetry/sdk-logs` peerDependencies bumped from `^0.214.0` to `^0.216.0` (was unsatisfiable because for 0.x semver `^0.214.0` excludes 0.215.x and 0.216.x). The mismatch broke `npm ls` which `Generate-TypeScript-SBOM` depends on, blocking the PyPI publish job. All `@opentelemetry/*` deps now align with the latest 0.216.0 / 2.7.1 minors.
- **crates.io trusted publishing wired correctly** — `release.yml` `publish-rust` now uses `rust-lang/crates-io-auth-action@v1.0.4` to exchange the GitHub OIDC token for a short-lived `CARGO_REGISTRY_TOKEN`. The previous step ran `cargo publish` without any token-exchange step.
- **Go consumer probe now runs `go mod tidy`** — `ci/verify-go-consumer-module.sh` populates the consumer probe's `go.sum` with transitive deps (e.g., `go.opentelemetry.io/otel/trace` imported by `go/tracer`) before `go test`. Previously failed for `go/v*` tags with "missing go.sum entry".

### Dependency refresh (latest within current ranges)

- **TypeScript**: `@opentelemetry/{api-logs,sdk-logs,exporter-*-otlp-http}` 0.215.0 → 0.216.0; `@opentelemetry/{context-async-hooks,resources,sdk-metrics,sdk-trace-base}` 2.6.1 → 2.7.1; `@types/node` 25.5.2 → 25.6.0; `vitest` 4.1.2 → 4.1.5; `eslint` 10.2.0 → 10.3.0; `typescript` 6.0.2 → 6.0.3.
- **Python**: `opentelemetry-{api,sdk,exporter-otlp-proto-http,proto}` 1.41.0 → 1.41.1; `opentelemetry-instrumentation-logging` 0.62b0 → 0.62b1; `pre-commit` 4.5.1 → 4.6.0; `ruff` 0.15.11 → 0.15.12; `ty` 0.0.32 → 0.0.34; plus minor updates across `mypy`, `playwright`, `textual`, `virtualenv`, `pip`, `wcwidth`.
- **Go (otel submodule)**: `otelslog` 0.17.0 → 0.18.0; `otlplog/otlploghttp` 0.18.0 → 0.19.0; `otel/log` 0.18.0 → 0.19.0; `otel/sdk/log` 0.18.0 → 0.19.0; `golang.org/x/{net,sys,text}` 0.52/0.42/0.35 → 0.53/0.43/0.36; `grpc-gateway/v2` 2.28.0 → 2.29.0; `genproto/googleapis/{api,rpc}` advanced.
- **Rust**: `cargo update` advanced numerous transitive deps to latest semver-compatible (wasm-bindgen 0.2.117 → 0.2.120, web-sys 0.3.94 → 0.3.97, etc.).

### Verification

- TypeScript: 1638 tests pass, 2 skipped, 2 todo
- Python: 2315 tests pass, 1 skipped, 100% branch coverage
- Go (root + otel submodule): all packages green
- Rust: workspace-wide tests green

---

## [0.4.3] — 2026-05-03

### API Alignment

- **Go: ticket-based backpressure API** — `TryAcquire(signal)` returns a `*QueueTicket`; pass that ticket to `Release(ticket)` so acquisition and release share one opaque queue handle.
- **TypeScript: canonical sanitizer export** — `sanitize` is exported from the package root and implemented by the PII module; no separate sanitizer module is shipped.

### Reliability

- **All: OTLP shared endpoint expansion** — `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` resolves to `/v1/traces`, `/v1/metrics`, and `/v1/logs` consistently across implementations.
- **Rust: probabilistic sampling** — fractional sampling rates now perform a fresh uniform random draw per call; keys only select override rates.
- **Go: disabled signal gates** — disabled tracing and metrics no longer install providers or emit through local instrument wrappers.
- **Python: tracing failure cleanup** — tracing decorators now release backpressure tickets and restore local context if span entry fails.
- **TypeScript: PII path specificity** — exact custom rules no longer exempt unrelated default-sensitive keys.
- **Go/TypeScript/Rust: lazy logger sampling** — log sampling from environment is applied consistently before explicit setup.

### Quality

- **Cross-language tests** — added focused regression tests for sampling, OTLP endpoint resolution, disabled-signal gates, lazy logging, backpressure release, tracing cleanup, and PII rule specificity.
- **End-state cleanup** — removed duplicate sanitizer and backpressure surfaces so the public API matches the canonical implementation from the start.

---

## [0.3.0] — 2026-04-12

_Reconstructed from git history — this release shipped without a changelog entry.
Note this is the April 0.3.0, after the version rewind; it is unrelated to the
March 0.3.x line covered by "0.3.16 and earlier" below._

### Added

- **`guard_attributes`, `set_strict_schema` / `get_strict_schema`** — added to the spec and implemented in all four languages.
- **Governance modules are mandatory** — classification, consent, and receipts are required and always present across language builds.
- **Rust: SLO metrics and a secret-pattern API**, plus examples rewritten onto the public `setup_telemetry()` surface.

### Fixed

- **Go: PII engines unified**, the slice drop mode corrected, and a backpressure TOCTOU closed.

---

## [0.2.6] — 2026-04-10

_Reconstructed from git history — this release shipped without a changelog entry._

### Fixed

- **Go: logger global state is guarded by an `RWMutex`** — concurrent reconfiguration and logging raced on the same globals.

The TypeScript package moved for version parity only.

---

## [0.2.4] — 2026-04-08

### Features

- **All: `register_secret_pattern` API** — register custom secret detection patterns for PII sanitization; name-based deduplication, thread-safe, near-zero overhead
- **All: cross-language benchmark suite** — `scripts/bench.sh` with normalized output across Python, TypeScript, Go; `make bench` targets
- **All: stress test parity** — 6 scenarios (logging, sampling, PII, backpressure, metrics, tracing) across all three languages

### Performance

- **Python: hot-path optimization** — `event_name` 22x faster (cached deferred import), `counter.add` 3.3x faster (unchecked fast paths, no per-call health tracking), `shouldSample` 2.8x faster (lock-free read), `getHealthSnapshot` 1.7x faster (NamedTuple)
- **Python: `_resolve_otel` caching** — cache "no OTel provider" result to avoid repeated deferred imports (963ns → 20ns per call)

### Bug Fixes

- **Go: health tracking double-count** — `TryAcquire` no longer increments `emitted_*` (was double-counting with `ShouldSample`)
- **Go: `export_latency_ms` always 0** — wired `_recordExportLatencyForSignal` into `RunWithResilience` on success
- **TypeScript: `emitted_*`/`dropped_*` always 0** — added health counter calls to `shouldSample` and `tryAcquire`
- **TypeScript: browser crash on import** — `receipts.ts` replaced Node.js `crypto` with pure-JS `hash.ts` (SHA-256, randomHex)
- **Spec: removed stale Go W3C propagation divergence note** — Go already discards oversized headers
- **Docs: 13 inaccuracies fixed** — spec env var names, circuit state hyphen, HealthSnapshot type, export counts, field names, processor pipeline

### Quality

- **Python: 100% mutation kill** (3022 mutants, 0 survivors)
- **TypeScript: 100% mutation kill** (1762 mutants, 0 survivors — was 93.81%)
- **Spec: `health_counters` behavioral parity section** — defines when emitted/dropped/retries/failures/latency counters fire

---

## [0.2.3] — 2026-04-06

### Features

- **All: `StrictSchema` in `RuntimeOverrides`** — `strict_schema` / `StrictSchema` / `strictSchema` is now hot-reloadable via `update_runtime_config` / `UpdateRuntimeConfig` / `updateRuntimeConfig`

### Improvements

- **Python: PII `deepcopy` removed** — `sanitize_payload` no longer calls `copy.deepcopy` for nested rules; traversal already builds new nodes, so a shallow top-level copy is sufficient
- **TypeScript: `updateRuntimeConfig` validation** — rates, sizes, retries, and timeouts validated on call; rejects NaN, negatives, and out-of-range rates
- **Go: `UpdateRuntimeConfig` validation** — input validation added matching Python/TypeScript behaviour
- **React: `useTelemetryContext` key ownership** — documented that sibling components must not bind the same key in browser environments

### Bug Fixes

- **CI: Go workflow** — renamed to `🐹 CI — Go`; gosec excludes `cmd/e2e_cross_language_client` (separate Go 1.26 module) to fix Dependabot PR failures

---

## [0.2.2] — 2026-04-06

### Features

- **Go: control-plane integrity** — `RuntimeOverrides` type; `UpdateRuntimeConfig` accepts hot-field-only overrides; `ReloadRuntimeFromEnv` warns on cold-field drift; `ReconfigureTelemetry` for full restart
- **Go: data governance** — `ClassificationPolicy`, `ConsentLevel`/`ShouldAllow`, cryptographic redaction receipts with HMAC signing.
- **Go: config masking** — `TelemetryConfig.String()` masks OTLP header values and endpoint passwords
- **Go: PII depth** — `PROVIDE_LOG_PII_MAX_DEPTH` env var; default max depth 8; depth limit applied across all rule types
- **All: canonical 25-field `HealthSnapshot`** — per-signal fields aligned across Go, TypeScript, and Python

### Improvements

- **Go: golangci-lint v2** — full linter suite now runs in CI against Go 1.25
- **Go: parity alignment** — sampling signal validation, backpressure unlimited default, cardinality clamping, OTLP header `+` preservation, event name strict mode
- **CI: npm publish** — `@provide-io/telemetry` now publishes to npm on GitHub release via `NPM_TOKEN`

### Bug Fixes

- Go: `UpdateRuntimeConfig` TOCTOU race in frozen idempotent path
- Go: `golangci-lint` v1/v2 config format mismatch (switched to v2 module path)
- Go: gosec `#nosec` directive format corrected in OpenObserve example
- Go: `_receiptsEnabled` unused field removed; `consent.go` exhaustive switch; `ReloadRuntimeFromEnv` cyclomatic complexity reduced

---

## [0.4.2] — 2026-03-29

### Features

* **react:** add `useTelemetryContext` hook and `TelemetryErrorBoundary` with render-prop fallback and reset ([c824108](https://github.com/provide-io/provide-telemetry/commit/c824108))

### Bug Fixes

* fix: use absolute GitHub URLs in README for PyPI/TestPyPI rendering ([bc8196b](https://github.com/provide-io/provide-telemetry/commit/bc8196b))
* fix: move pragma: no mutate to depth parameter line in `_apply_rule` signature ([ea7400d](https://github.com/provide-io/provide-telemetry/commit/ea7400d))

### CI/CD

* gate production PyPI behind release event, tag only triggers TestPyPI ([9b8e05e](https://github.com/provide-io/provide-telemetry/commit/9b8e05e))
* decouple mutation testing into separate non-blocking workflow ([d72564d](https://github.com/provide-io/provide-telemetry/commit/d72564d))
* upgrade setup-uv v7→v8, remove redundant setup-python, update codeql + sigstore SHAs ([ea10928](https://github.com/provide-io/provide-telemetry/commit/ea10928))

### Tests

* kill remaining pii/propagation mutation survivors ([b9de97f](https://github.com/provide-io/provide-telemetry/commit/b9de97f))
* kill all surviving Python and TypeScript mutations ([3d89ed2](https://github.com/provide-io/provide-telemetry/commit/3d89ed2))

---

## [0.4.1] — 2026-03-28

### Features

* **typescript:** add error fingerprinting and session correlation with 100% coverage ([6769ed7](https://github.com/provide-io/provide-telemetry/commit/6769ed7))
* **typescript:** add pretty ANSI log renderer with color support and TTY detection ([add0cc2](https://github.com/provide-io/provide-telemetry/commit/add0cc2))
* **typescript:** add conditional exports for browser/edge OTel no-op stub ([c0f0879](https://github.com/provide-io/provide-telemetry/commit/c0f0879))
* add SecurityConfig dataclass with attr/depth limits ([1cd3677](https://github.com/provide-io/provide-telemetry/commit/1cd3677))
* add secret pattern detection and depth guards to PII sanitizer ([78565e1](https://github.com/provide-io/provide-telemetry/commit/78565e1))
* add protocol size guards to W3C context extraction ([96661c4](https://github.com/provide-io/provide-telemetry/commit/96661c4))

### Bug Fixes

* W3C baggage property stripping, BaseException fingerprinting, session context leak prevention ([f3d4eed](https://github.com/provide-io/provide-telemetry/commit/f3d4eed))
* replace executor after circuit breaker trips to prevent ghost thread accumulation ([3dc405d](https://github.com/provide-io/provide-telemetry/commit/3dc405d))
* add ASIA prefix to AWS key detection, wire max_depth through sanitize processor ([72a59ca](https://github.com/provide-io/provide-telemetry/commit/72a59ca))
* add TYPE_CHECKING imports for lazy SLO exports (IDE autocomplete) ([a7632b2](https://github.com/provide-io/provide-telemetry/commit/a7632b2))
* **deps:** upgrade cryptography 46.0.5→46.0.6, requests 2.32.5→2.33.0 (security) ([1b826f7](https://github.com/provide-io/provide-telemetry/commit/1b826f7))

### CI/CD

* add TestPyPI staging + verification before production PyPI publish ([40676f1](https://github.com/provide-io/provide-telemetry/commit/40676f1))
* add Windows testing to Python and TypeScript quality jobs ([86272ab](https://github.com/provide-io/provide-telemetry/commit/86272ab))
* pin all runners to specific versions, add macOS ARM64 (Apple Silicon) testing ([859ceb9](https://github.com/provide-io/provide-telemetry/commit/859ceb9))

---

## [0.4.0](https://github.com/provide-io/provide-telemetry/compare/provide-telemetry-v0.3.0...provide-telemetry-v0.4.0) (2026-03-28)


### Features

* add memray memory profiling infrastructure and optimize hot paths ([648177c](https://github.com/provide-io/provide-telemetry/commit/648177c7394591841cefabdf132304c4a2fdea78))
* **browser-e2e:** add Vite-served browser tracer page and proxy config ([e0bbdc3](https://github.com/provide-io/provide-telemetry/commit/e0bbdc3a5bb6deb3aa75ede51a3e784884f44937))
* enterprise hardening — governance, releases, supply chain, ops ([d42ce5a](https://github.com/provide-io/provide-telemetry/commit/d42ce5a11874e3e25aec184ba43995f7c0feb7a7))
* per-module log level overrides (PROVIDE_LOG_MODULE_LEVELS) ([c4a3b12](https://github.com/provide-io/provide-telemetry/commit/c4a3b12a752ada3fade0021e43dc12683f6e056c))
* per-module log level overrides (PROVIDE_LOG_MODULE_LEVELS) ([c947f41](https://github.com/provide-io/provide-telemetry/commit/c947f4178939efc6f44c3547e512a7565b76bc77))
* polyglot spec infrastructure for multi-language support ([a5711af](https://github.com/provide-io/provide-telemetry/commit/a5711af396c9da2517e31815587ce70612b828bd))
* **spec:** add canonical API surface definition for polyglot conformance ([8a70c00](https://github.com/provide-io/provide-telemetry/commit/8a70c008b97ddaa78280b44e0396953c93e40af1))
* **spec:** add conformance validation script for Python and TypeScript ([b74c58f](https://github.com/provide-io/provide-telemetry/commit/b74c58f54e816a78c94f1080359125cb93dd47ce))
* **typescript:** add TypeScript package with 100% mutation score ([d70527f](https://github.com/provide-io/provide-telemetry/commit/d70527f8136504a0533ddd53271c58af3e443235))
* **typescript:** implement shutdownTelemetry with full OTel provider drain ([0a740f7](https://github.com/provide-io/provide-telemetry/commit/0a740f723e1dcc2bab5321eba3f96e38c3c4ea39))
* **version:** transition to shared major.minor versioning with per-language patch ([48c8728](https://github.com/provide-io/provide-telemetry/commit/48c87284e845ba3cf1df1d5e2d09ce4c0723d28d))


### Bug Fixes

* add e2e/ to ruff per-file-ignores after test promotion ([d1c20a3](https://github.com/provide-io/provide-telemetry/commit/d1c20a3329518b761206e07a41108fb768aa9788))
* address PR review feedback — lock file sync, parser robustness, exception narrowing, license link ([fb6428a](https://github.com/provide-io/provide-telemetry/commit/fb6428a4a2d06a910c977f8eb2a0b2b0904cfee4))
* allow logging config changes without provider restart ([fb3620e](https://github.com/provide-io/provide-telemetry/commit/fb3620ea90e589eaac12f6ad0e34ee3388685560))
* anchor memray test paths to project root via VERSION file ([61dc9a4](https://github.com/provide-io/provide-telemetry/commit/61dc9a412751d21e055c7ed73169947c54c2486e))
* **e2e:** collect console messages properly, retry Vite page load instead of sleep ([dd8fa58](https://github.com/provide-io/provide-telemetry/commit/dd8fa58854f0fa88901e86a84f98b303705390ce))
* exclude memray tests from mutmut stats collection ([7ee1885](https://github.com/provide-io/provide-telemetry/commit/7ee1885ebf2b20ce19449895d59c66b5350c4609))
* exclude node_modules from SPDX header check ([705af03](https://github.com/provide-io/provide-telemetry/commit/705af03a2ea4ad5ac91a723485b067452fc67de9))
* format e2e test, add REUSE annotations for new config files ([c7d67c9](https://github.com/provide-io/provide-telemetry/commit/c7d67c9144efe981ca119a4feaf22c9390af3389))
* lint errors, 100% coverage, exclude stryker sandbox from v8 coverage ([02cfe3b](https://github.com/provide-io/provide-telemetry/commit/02cfe3b90e8bc43504e79eb4058811efa2e567f1))
* mark pytest hook parameters as used for vulture ([b02c01e](https://github.com/provide-io/provide-telemetry/commit/b02c01e6529d76971103e28464952674ad4a4201))
* mark setattr API names as no-mutate, bypass resilience in handler tests for CI stability ([0326c48](https://github.com/provide-io/provide-telemetry/commit/0326c486c447ef12ebcc45636310d5c07ce7c001))
* remove invalid --CI flag from mutmut run ([3d0aa9e](https://github.com/provide-io/provide-telemetry/commit/3d0aa9e5acb0c2bca9f602bcc62ed9ae51df4be1))
* remove stale eslint-disable directives, bump perf threshold for CI, update happy-dom ([dc1bbdf](https://github.com/provide-io/provide-telemetry/commit/dc1bbdfa9a0f32c88cb1bd1630568ba0223a05e2))
* rename unused loop variable to satisfy ruff B007 ([cd07499](https://github.com/provide-io/provide-telemetry/commit/cd07499e2e1ee3c1e40d88f869657697a1917828))
* reset sampling policy between tests; correct config.py docs ([5f92e32](https://github.com/provide-io/provide-telemetry/commit/5f92e32b954d181843b6bfba978bd8186daf7e04))
* resolve pre-existing ruff and mypy errors in test files ([f8daaff](https://github.com/provide-io/provide-telemetry/commit/f8daaff7a1e2d54d4ec0d27b461e3db85d3572ec))
* resolve ty type-checker errors in processors and test overrides ([942bb15](https://github.com/provide-io/provide-telemetry/commit/942bb1553bfb004dd1d1f97a02858ec8a9e666cf))
* resolve ty type-checker errors with setattr/getattr for dynamic attributes ([6b6888a](https://github.com/provide-io/provide-telemetry/commit/6b6888a79ad5d39dfc498da16a0a7f754bad4677))
* restore 25μs perf threshold for CI runners, remove flaky marker ([bfd9e62](https://github.com/provide-io/provide-telemetry/commit/bfd9e623106b4eb399db3d47ebf594e89b2b6526))
* **spec:** address review issues in conformance validation ([6ce01f7](https://github.com/provide-io/provide-telemetry/commit/6ce01f7452050a23a0ccc3ab90d91c9fc4abe857))
* **test:** accept 2-segment version after major.minor transition ([c41a517](https://github.com/provide-io/provide-telemetry/commit/c41a5179092b6cd7ab65b1bccc89387ada4ee868))
* three bugs in telemetry logger — static isBrowser, stale cfg, Node.js write hook ([59e076d](https://github.com/provide-io/provide-telemetry/commit/59e076d0cd4ee159873c4c98484c5b8733583bd8))


### Tests

* add circuit breaker lifecycle test ([2e33f78](https://github.com/provide-io/provide-telemetry/commit/2e33f7804ee5d385092fcd8195c2cc9d24524c8e))
* add cross-signal isolation test ([c6082be](https://github.com/provide-io/provide-telemetry/commit/c6082be9756c8f92da6a199b1671ca84b79bee95))
* add ghost thread accumulation test ([db62d0c](https://github.com/provide-io/provide-telemetry/commit/db62d0cf587f37ef591d988163606ffaf4af6e44))
* add pytest-rerunfailures for flaky performance tests ([debace7](https://github.com/provide-io/provide-telemetry/commit/debace798eb5420123b9583853d13cc31bd8aec3))
* **e2e:** browser distributed trace linkage via Playwright + Vite proxy ([0075d5a](https://github.com/provide-io/provide-telemetry/commit/0075d5af8ee75a62b6cd464bf9e749f1e4a2d9c9))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([61611c8](https://github.com/provide-io/provide-telemetry/commit/61611c859d8c09df8ff2835d6ca85fe26facb5af))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([1bada42](https://github.com/provide-io/provide-telemetry/commit/1bada42f39e7b7bd422aa640b8341e3bf5329ffd))
* fix scaffold lint issues and defensive teardown ([fea1b3d](https://github.com/provide-io/provide-telemetry/commit/fea1b3dcf0b20237da1b048ec0b8dc2ab96aa4af))
* harden assertions, add cross-signal isolation, fix OTel markers and docs ([47bda6d](https://github.com/provide-io/provide-telemetry/commit/47bda6d044ac0f7c7bec68e47a46e6c8ace7d63a))
* kill 34 no_tests mutation survivors in otel component loaders ([3186330](https://github.com/provide-io/provide-telemetry/commit/318633086364184cc484588a8b35287d8676d7d8))
* kill 7 mutation survivors in _otel and provider guard conditions ([1c4f863](https://github.com/provide-io/provide-telemetry/commit/1c4f863a5b3a471477ce39a01b47cfa05c5a2823))
* kill final 2 no_tests mutation survivors in provider component guards ([e15cb97](https://github.com/provide-io/provide-telemetry/commit/e15cb97dea8a0cf15b873a0caa3a919ca7cc9545))
* scaffold executor saturation test file with fixtures and helpers ([ce77b28](https://github.com/provide-io/provide-telemetry/commit/ce77b2816a5093e70e4847abe91a2014c89aade4))
* **ts:** add full coverage and mutation tests for otel.ts ([e5187eb](https://github.com/provide-io/provide-telemetry/commit/e5187ebb273453097c746e5125a08bd17429d408))
* **ts:** kill window typeof-check mutation survivors in node env ([125f561](https://github.com/provide-io/provide-telemetry/commit/125f561fab0099fdf33e69959fa04c3fde0a69ee))
* **typescript:** kill config.ts logFormat string mutation with empty-string test ([4a765cf](https://github.com/provide-io/provide-telemetry/commit/4a765cf83c798fe10835ec21826e657c95734d6f))
* **typescript:** kill surviving mutants in backpressure, cardinality, resilience ([eb8ee9b](https://github.com/provide-io/provide-telemetry/commit/eb8ee9ba6ecb7557c5276f5ca677e07214c7c536))
* use &lt;= for thread drain assertion (safer under parallel runners) ([c11afff](https://github.com/provide-io/provide-telemetry/commit/c11afff62ecfae4c3411c63a2defd8d852a9e542))


### CI/CD

* add changed-files mutation gate for Python PRs ([a2a680e](https://github.com/provide-io/provide-telemetry/commit/a2a680eb5620deef7ff332893228d699ddfa2c43))
* add changed-files mutation gate for TypeScript PRs ([6f42454](https://github.com/provide-io/provide-telemetry/commit/6f424545eb2bef79c4a000053297d1af4f454ac7))
* add CODEOWNERS for code review assignment ([f3bdae2](https://github.com/provide-io/provide-telemetry/commit/f3bdae2eac6104090aff8a8d92df364b3e321fd4))
* add CodeQL SAST scanning for Python and TypeScript ([2ca88df](https://github.com/provide-io/provide-telemetry/commit/2ca88df015b145248b73e0b28913b257a1461dc6))
* add commitlint for conventional commit enforcement ([4b218d4](https://github.com/provide-io/provide-telemetry/commit/4b218d4912d85219999435c04cb4dfe17a93b147))
* add CycloneDX SBOM generation to release pipeline ([81b0f72](https://github.com/provide-io/provide-telemetry/commit/81b0f72908c3a8bedb81de228ccaa739efe7a9fb))
* add Dependabot for automated dependency updates ([fe93b0d](https://github.com/provide-io/provide-telemetry/commit/fe93b0dcc7581e5ae0254166406a5b2b4746e72c))
* add numbered emoji prefixes to workflow names for sorted display ([f2704a6](https://github.com/provide-io/provide-telemetry/commit/f2704a660073ec11e152cdf2a4f15a1363da57ff))
* add playwright chromium install to openobserve-e2e job ([7bde5e4](https://github.com/provide-io/provide-telemetry/commit/7bde5e4514ef031b342d912e7bccfcdac85b5ed5))
* add pull request template ([7cc5e24](https://github.com/provide-io/provide-telemetry/commit/7cc5e24d60fa79ac9ce019538497cbbbd451619c))
* add Sigstore artifact signing to release pipeline ([219bbaf](https://github.com/provide-io/provide-telemetry/commit/219bbaf1155c3b3d46381d0a2b5f7b934f81729e))
* add spec conformance and version sync workflow ([a11de50](https://github.com/provide-io/provide-telemetry/commit/a11de50f1e92faf132753c914c3e6ac298eaf47d))
* configure release-please for automated releases ([ab3b8af](https://github.com/provide-io/provide-telemetry/commit/ab3b8af8cda50c06d265635437dadc1f00e907e4))
* log surviving mutant names on mutation gate failure ([810c740](https://github.com/provide-io/provide-telemetry/commit/810c7406af3a01874731a92733bd08569b8bddbe))
* pin all GitHub Actions to SHA for supply chain security ([8bd28e8](https://github.com/provide-io/provide-telemetry/commit/8bd28e880c80759d04b97bb7572abc43d39bd872))
* run mutation-gate, otlp-integration, performance-smoke, and TS mutation on every PR ([bf3219b](https://github.com/provide-io/provide-telemetry/commit/bf3219b2f6755cbeef7eec2ccd2bb9c0310aa020))
* split monolithic CI into language-specific workflows with path filters ([b184204](https://github.com/provide-io/provide-telemetry/commit/b1842042d0b46d600a5ef71f8c05584e7e7c4cca))
* update all GitHub Actions to latest major versions ([881b467](https://github.com/provide-io/provide-telemetry/commit/881b467f46b2ef3f1b02f3a50d0da1a419183488))


### Documentation

* add branch protection configuration guide ([5c17102](https://github.com/provide-io/provide-telemetry/commit/5c1710241975fc210e88d0e890d95310d45eee6f))
* add enterprise hardening design spec ([e5c24f2](https://github.com/provide-io/provide-telemetry/commit/e5c24f2353eda731f44da053e7355a5971e77aa7))
* add enterprise hardening implementation plan ([49d2920](https://github.com/provide-io/provide-telemetry/commit/49d2920a2ebee5269bb297d134e58da69cc00f6f))
* add executor saturation load test design spec ([a768008](https://github.com/provide-io/provide-telemetry/commit/a768008beb55e0f53ddd64f2686657c1192c7203))
* add executor saturation load test implementation plan ([d2e3113](https://github.com/provide-io/provide-telemetry/commit/d2e3113589aee1a5aa32f0bb02e6d4822ba1a3bf))
* add polyglot structure section to CLAUDE.md ([1b5d6fc](https://github.com/provide-io/provide-telemetry/commit/1b5d6fc14cb89db4620ef03524525a88b832e475))
* remove stale migration language, stub references, and history comments ([68b6317](https://github.com/provide-io/provide-telemetry/commit/68b631700096b72297887dc986c4e65c20c27f79))
* rewrite README for polyglot end-state with badges and TypeScript ([2f65d9f](https://github.com/provide-io/provide-telemetry/commit/2f65d9f86067635e35de4e0a3ea416985d92d498))


### Refactoring

* **e2e:** promote cross-language E2E tests to repo root ([3481b0c](https://github.com/provide-io/provide-telemetry/commit/3481b0c1a0986aaff54d1c3961b1336fbfae8fe1))

## [0.3.18] — 2026-03-27

### Added
- **TypeScript: `shutdownTelemetry()`** — flushes and drains all registered OTel providers
  using `Promise.allSettled`; safe to call before process exit or on hot-reload.
- **TypeScript: `registerOtelProviders()` provider registry** — providers created by
  `registerOtelProviders` are now stored in `runtime.ts` so `shutdownTelemetry` can drain them.
- **Cross-language distributed tracing E2E test** — pytest test spawns a TypeScript OTel client
  and a Python HTTP backend as subprocesses; verifies both spans share the same W3C `trace_id`
  in OpenObserve.
- **TypeScript CI jobs** — `typescript-quality` (lint + format + typecheck + 100% coverage) runs
  on every push/PR; `typescript-mutation-gate` (Stryker 100% kill) runs on schedule/dispatch.
- **npm publish pipeline** — `release.yml` builds and publishes `@provide-io/telemetry` to npm on
  GitHub release via `NPM_TOKEN`.
- **TypeScript package metadata** — `author`, `homepage`, `repository`, `keywords`,
  `sideEffects: false`, `engines: { "node": ">=18" }`, `prepublishOnly` guard.

### Changed
- **TypeScript version aligned to Python** — `@provide-io/telemetry` is now `0.3.18` (was `0.1.0`).
- **Stryker mutation threshold raised to 100** — `break: 100` enforced in CI (was 70).
- **`src/otel.ts` included in strict type-checking** — removed from `tsconfig.json` exclude list;
  all 20 TypeScript source files are now fully type-checked under `strict: true`.
- **Python development status** — classifier updated from `3 - Alpha` to `4 - Beta`.
- **TypeScript upgraded to v6**, all npm dependencies updated to latest.

### Fixed
- Removed stale `provide-telemetry → repo-root` symlink that caused pytest to loop infinitely
  when discovering tests from a background shell.

---

## [0.3.17] — 2026-03-25

### Added
- **Hardened test assertions** — replaced `assert x is not None` patterns with typed/value
  checks across 15 test files (trace/span ID format, QueueTicket isinstance, counter/gauge
  behavioral checks, etc.).
- **Cross-signal isolation tests** (`tests/resilience/test_cross_signal_isolation.py`) —
  verifies that queue, sampling, and health-counter state is fully independent per signal.
- **OTel pytest markers** — `pytest.mark.otel` added to `test_otel_loader.py`,
  `test_provider_helpers.py`, and `test_otlp_integration.py`.
- **Executor saturation load tests** (`tests/resilience/test_executor_saturation.py`) —
  covers ghost thread accumulation, circuit breaker lifecycle, and cross-signal isolation
  under sustained export failures.

### Fixed
- Sampling policy now resets between tests; corrected `config.py` docstring.

---

## [0.3.16] and earlier

Earlier versions are not individually documented. See the git log for details:

```bash
git log --oneline v0.3.16..HEAD
```
