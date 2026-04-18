# Java SDK — Design

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc

## Problem

The `provide-telemetry` polyglot SDK ships behavioral-parity implementations in
Python, TypeScript, Go, and Rust. A Java port is the highest-ROI next language
because server-side enterprise workloads overwhelmingly target the JVM, the
OpenTelemetry Java ecosystem is mature, and the SDK's core concerns (structured
logging, W3C propagation, request-context isolation, optional OTel export) map
cleanly onto idiomatic Java 21 primitives.

The Java SDK must reach full behavioral parity with the four existing languages:
all required exports in `spec/telemetry-api.yaml`, all runtime probe cases in
`spec/runtime_probe_fixtures.yaml`, all contract cases in
`spec/contract_fixtures.yaml`, canonical log-envelope field parity, and the
project's standard quality gates (100% branch coverage, 100% mutation kill,
500 LOC per file cap, SPDX headers, cross-platform CI matrix).

## Decision

Add a single-module Gradle (Kotlin DSL) project at `java/`, targeting Java 21
(LTS, GA — no preview features). Publish to GitHub Packages. OTel is an
optional runtime dependency detected via `Class.forName` reflection, matching
the pattern Python, Rust, and TypeScript use for their optional OTel layers.

## Rules That Apply To This Spec

1. **Latest versions for all dependencies.** Every library chosen below is
   specified at its most recent stable version. If a version conflict arises
   during implementation (e.g., two transitive deps pinning incompatible
   ranges of a third), the implementer pauses and asks the user rather than
   downgrading silently.
2. **No preview Java features.** `ScopedValue`, Structured Concurrency, and
   String Templates are all preview in Java 21 and can change. The SDK must
   build and run without `--enable-preview`.
3. **No inline CI scripts longer than 3 lines.** Per the repo's CLAUDE.md,
   substantial CI logic lives in `ci/` scripts, not YAML `run:` blocks.
4. **Integration tests hit real services.** Testcontainers-backed OpenObserve
   is the E2E strategy. Unit tests may use Mockito for behavior verification;
   integration/E2E tests may not.

## Files Changed

### Created

```
java/
├── build.gradle.kts
├── settings.gradle.kts
├── gradle.properties
├── gradle/wrapper/
│   ├── gradle-wrapper.jar
│   └── gradle-wrapper.properties
├── gradlew, gradlew.bat
├── VERSION
├── README.md
├── CHANGELOG.md
├── LICENSE
├── src/main/java/io/provide/telemetry/
│   ├── Telemetry.java
│   ├── TelemetryConfig.java
│   ├── package-info.java                    # @NullMarked at package level
│   ├── setup/SetupManager.java
│   ├── logger/
│   │   ├── StructuredLogger.java
│   │   ├── LogContext.java
│   │   └── processors/
│   │       ├── HardenInput.java
│   │       ├── InjectDarsFields.java
│   │       ├── InjectLoggerName.java
│   │       ├── AddStandardFields.java
│   │       ├── ErrorFingerprint.java
│   │       ├── EnforceEventSchema.java
│   │       ├── SanitizePii.java
│   │       └── MergeRuntimeContext.java
│   ├── tracing/
│   │   ├── TracingContext.java
│   │   ├── TracerFacade.java
│   │   └── SpanBuilder.java
│   ├── metrics/
│   │   ├── MetricsFacade.java
│   │   ├── Counter.java
│   │   ├── Gauge.java
│   │   └── Histogram.java
│   ├── propagation/
│   │   ├── W3CPropagator.java
│   │   └── Baggage.java
│   ├── sampling/SamplingPolicy.java
│   ├── backpressure/QueuePolicy.java
│   ├── resilience/
│   │   ├── ExporterPolicy.java
│   │   ├── CircuitBreaker.java
│   │   └── RetryExecutor.java
│   ├── pii/
│   │   ├── PIIRule.java
│   │   └── SecretDetector.java
│   ├── cardinality/CardinalityGuard.java
│   ├── schema/
│   │   ├── Event.java
│   │   └── SchemaValidator.java
│   ├── health/HealthSnapshot.java
│   ├── runtime/RuntimeConfig.java
│   ├── otel/
│   │   ├── OtelDetector.java
│   │   └── OtelProviders.java
│   └── exceptions/
│       ├── TelemetryError.java
│       ├── ConfigurationError.java
│       └── EventSchemaError.java
├── src/test/java/io/provide/telemetry/
│   └── (mirrors main layout)
└── src/jmh/java/io/provide/telemetry/perf/
    └── (JMH benchmarks)

spec/probes/runtime_probe_java/
├── RuntimeProbeMain.java
└── LogOutputProbe.java

spec/probes/contract_probe_java/
└── ContractProbeMain.java

.github/workflows/
└── ci-java.yml

ci/
├── java-format-check.sh
├── java-lint.sh
├── java-test.sh
├── java-mutation.sh
└── java-spdx-check.sh
```

### Modified

```
spec/parity_probe_support.py            # register Java ProbeRunner
spec/contract_probe_harness.py          # register Java contract runner
scripts/check_version_sync.py           # read java/build.gradle.kts
scripts/check_max_loc.py                # confirm .java included
scripts/check_spdx_headers.py           # Java // comment style
.pre-commit-config.yaml                 # java-format / java-lint / java-tests hooks
.github/workflows/release.yml           # publish Java on release tags
README.md                               # add Java to the polyglot matrix
CHANGELOG.md
VERSION                                 # unchanged; java/VERSION tracks this
```

## Implementation

### 1. Project Structure and Build

Single Gradle module at `java/`. Top-level `build.gradle.kts` (Kotlin DSL)
configures:

- `java.toolchain.languageVersion = JavaLanguageVersion.of(21)`
- `sourceCompatibility`/`targetCompatibility` = 21
- `java.withSourcesJar()` and `java.withJavadocJar()` for publishing
- JUnit 5 platform, JaCoCo, PIT, Error Prone, NullAway, SpotBugs, PMD,
  Checkstyle, jqwik, ArchUnit, AssertJ, Testcontainers, Awaitility, Mockito,
  JMH — all at their latest stable releases at implementation time.
- Spotless for format enforcement (Google Java Format).
- Publishing to GitHub Packages (`maven.pkg.github.com/provide-io/provide-telemetry`).

### 2. Public API (full parity with `spec/telemetry-api.yaml`)

The top-level façade `io.provide.telemetry.Telemetry` exposes all required
exports as `public static` methods. Naming follows `camelCase` (Java standard,
matches TypeScript's surface). Every required symbol from the spec is
implemented with no `language_overrides[java]` entries in
`spec/validate_conformance.py`.

**Lifecycle:** `setupTelemetry()`, `setupTelemetry(TelemetryConfig)`,
`shutdownTelemetry()`, `reconfigureTelemetry()`, `reloadRuntimeFromEnv()`.

**Logging:** `getLogger()`, `getLogger(String)`, `logger` (static field),
`bindContext(Map)`, `unbindContext(Collection<String>)`, `clearContext()`,
`bindSessionContext(...)`, `getSessionId()`, `clearSessionContext()`.

**Tracing:** `getTracer()`, `tracer`, `trace(String, Runnable)`,
`getTraceContext()`, `setTraceContext(String, String)`.

**Metrics:** `getMeter()`, `counter(String, String, String)`,
`gauge(String, String, String)`, `histogram(String, String, String)`.

**Propagation:** `extractW3CContext(Map)`, `bindPropagationContext(...)`,
`clearPropagationContext()`.

**Policy:** `getSamplingPolicy()`, `setSamplingPolicy()`,
`shouldSample(Signal)`, `getQueuePolicy()`, `setQueuePolicy()`,
`getExporterPolicy()`, `setExporterPolicy()`.

**Cardinality / PII / Health:** `guardAttributes(...)`,
`registerPIIRule(PIIRule)`, `getHealthSnapshot()`.

**Schema:** `event(String, String, String, String)` returning an `Event`
record, `setStrictSchema(boolean)`, `getStrictSchema()`.

**Runtime:** `getRuntimeConfig()`, `updateRuntimeConfig(RuntimeOverrides)`.

**Governance (optional, strippable):** `registerClassificationRules(...)`,
`setConsentLevel(...)`, `enableReceipts(boolean)`.

### 3. Immutable Types (`record`)

All DTOs are Java records for correct-by-construction `equals`/`hashCode`/
`toString` and genuine immutability:

```java
public record TelemetryConfig(
    String serviceName, String serviceEnv, String serviceVersion,
    String logLevel, String logFormat,
    boolean traceEnabled, double traceSampleRate, boolean metricsEnabled,
    @Nullable String otlpEndpoint, Map<String, String> otlpHeaders,
    ExporterPolicy exporterPolicy, SamplingPolicy samplingPolicy,
    QueuePolicy queuePolicy, boolean strictSchema
) {
    public static TelemetryConfig fromEnv() { /* ... */ }
}
```

Similarly: `SamplingPolicy`, `QueuePolicy`, `ExporterPolicy`, `PIIRule`,
`HealthSnapshot`, `CardinalityLimit`, `RuntimeOverrides`, `Event`.

### 4. Context Isolation

Per-request state lives in `ThreadLocal<Map<String, Object>>` instances. On
Java 21 server frameworks that spawn a virtual thread per request (Spring Boot
3.2+, Helidon Níma, Quarkus), each virtual thread gets its own ThreadLocal
copy automatically — no request-mixing risk. On platform-thread frameworks,
request-scoped state is bound at request-entry and cleared at request-exit by
the framework integration layer (not part of v1; users call
`bindContext` / `clearContext` themselves).

Unlike TypeScript's `AsyncLocalStorage`, `ThreadLocal` is a language primitive
that cannot be bundler-stripped — no startup guard is needed.

### 5. Null Safety

Package-level `@NullMarked` (JSpecify) on every package. References are
non-null by default; explicit `@Nullable` on the few fields that can be null
(e.g., `TelemetryConfig.otlpEndpoint`). NullAway runs as an Error Prone plugin
on every `compileJava` invocation and fails the build on null-safety
violations. Public return types prefer `Optional<T>` over nullable returns.

### 6. Thread Safety

- `SetupManager` uses a `ReentrantLock` (not `synchronized`) for idempotent
  init, matching Python's `threading.Lock`.
- Active config is an `AtomicReference<TelemetryConfig>` swapped atomically
  on hot-reload.
- Policy reads return immutable record snapshots; no shared mutable state in
  the hot path.
- `OtelDetector.STACK_PRESENT` is a `static final boolean` — computed once at
  class-init, no synchronization overhead on read.

### 7. OTel Integration

**Compile-time:** All OTel dependencies are declared `compileOnly` in
`build.gradle.kts`. The SDK compiles against OTel APIs but does not ship OTel
JARs transitively. Consumers who want real OTLP export add the OTel SDK
dependencies themselves.

**Runtime detection:**

```java
public final class OtelDetector {
    private OtelDetector() {}

    private static final boolean STACK_PRESENT = checkStack();

    public static boolean hasOtelStack() { return STACK_PRESENT; }

    private static boolean checkStack() {
        try {
            Class.forName("io.opentelemetry.api.OpenTelemetry");
            Class.forName("io.opentelemetry.sdk.OpenTelemetrySdk");
            Class.forName("io.opentelemetry.exporter.otlp.trace.OtlpGrpcSpanExporter");
            return true;
        } catch (ClassNotFoundException e) {
            return false;
        }
    }
}
```

**Provider wiring** (`OtelProviders.install(TelemetryConfig)`):

1. Build `Resource` from `serviceName`/`serviceEnv`/`serviceVersion` +
   `OTEL_RESOURCE_ATTRIBUTES`.
2. Per-signal OTLP exporters via `OtlpHttpSpanExporter.builder()`, etc.
   (HTTP/protobuf default).
3. Wrap each exporter in the SDK's `ExporterPolicy` (retry, timeout,
   circuit breaker, fail-open) — mirrors Rust's `ExporterPolicyConfig`.
4. Store providers in `AtomicReference<Object>` to keep OTel types out of
   the core compile path.

**Fail-open:** Per-signal; on exporter init failure with `failOpen = true`,
stderr-warn and fall back to no-op for that signal only.

**Hot emit path:** `counter.add(...)`, `histogram.record(...)`, `trace(...)`,
`logger.info(...)` check `hasOtelStack()` + provider presence, then either
emit to OTel or to the in-process fallback.

**Reconfigure:** If providers are already installed,
`reconfigureTelemetry()` throws `TelemetryError("providers already installed;
shutdown first")`. Full re-setup requires `shutdownTelemetry()` first.

### 8. Test Stack (2026 current)

| Tool | Version | Role |
|---|---|---|
| JUnit Jupiter | 5.11+ | Test runner |
| AssertJ | 3.26+ | Fluent assertions |
| jqwik | 1.9+ | Property-based tests |
| ArchUnit | 1.3+ | Architecture constraints |
| Mockito | 5.14+ | Unit-test behavior verification |
| Testcontainers | 1.20+ | Integration/E2E with real OpenObserve |
| Awaitility | 4.2+ | Async assertions |
| JMH | 1.37+ | Microbenchmarks |
| JaCoCo | 0.8.12+ | Branch coverage (100% required) |
| PIT (Pitest) | 1.17+ | Mutation testing (100% kill required) |

**Mockito** is used in unit tests for behavior verification (e.g., "the OTel
span builder received these attributes", "the retry executor invoked the
callable N times"). **Testcontainers** is used for integration and E2E tests;
these never use Mockito.

**ArchUnit rules** enforce architectural boundaries:
- `io.provide.telemetry.logger.*` may not directly import `io.opentelemetry.*`
- `io.provide.telemetry.exceptions.*` may only be imported by other
  `io.provide.telemetry.*` packages
- No package outside `io.provide.telemetry.otel.*` may call
  `OtelDetector.hasOtelStack()` (the fallback-path check)

### 9. Static Analysis

All of the following run in CI and must pass:

| Tool | Version | Role |
|---|---|---|
| Error Prone | latest | Compiler-time bug detection |
| NullAway | latest | Null-safety enforcement |
| SpotBugs | latest | Bytecode bug analysis |
| PMD | latest | Rule-based code quality |
| Checkstyle | latest | Google Java Style |
| Spotless | latest | Format enforcement (`./gradlew spotlessCheck`) |
| OWASP Dependency-Check | latest | Known-vulnerability scan |

### 10. Parity Harness Integration

**Runner registration** (`spec/parity_probe_support.py`):

```python
ProbeRunner(
    name="java",
    label="Java",
    cmd=[
        "java",
        "-cp", str(repo / "java/build/classes/java/main") + ":" +
               str(repo / "java/build/classes/java/probes"),
        "io.provide.telemetry.probe.RuntimeProbeMain",
    ],
    cwd=repo,
    env_extra={},
),
```

On first harness run, the Python side invokes
`./gradlew :compileJava :compileTestJava :probesJar` to ensure classes are
built. Subsequent runs reuse the compiled classes until Java sources change.

**Runtime probe** (`spec/probes/runtime_probe_java/RuntimeProbeMain.java`):
One `case*()` method per case ID, dispatched off
`System.getenv("PROVIDE_PARITY_PROBE_CASE")`. JSON output built with
`StringBuilder` (no Jackson dependency on the probe itself). Covers all 10
runtime probe cases: `lazy_init_logger`, `strict_schema_rejection`,
`strict_event_name_only`, `required_keys_rejection`, `invalid_config`,
`fail_open_exporter_init`, `signal_enablement`, `per_signal_logs_endpoint`,
`provider_identity_reconfigure`, `shutdown_re_setup`.

**Contract harness** (`spec/contract_probe_harness.py`):
Similar registration. `ContractProbeMain.java` handles the step-based DSL from
`spec/contract_fixtures.yaml`.

**Output probe** (`LogOutputProbe.java`): Emits a canonical log line so
`run_behavioral_parity.py --check-output` can compare
`message`/`level`/`service`/`env`/`version`/`logger_name`/`trace_id`/`span_id`
cross-language.

### 11. CI

`.github/workflows/ci-java.yml`:

- Triggers on `java/**`, `VERSION`, and the workflow file itself.
- Matrix: `ubuntu-24.04`, `macos-15`, `windows-2025` × Java 21.
- `actions/setup-java@v5` with `temurin` distribution.
- `gradle/actions/setup-gradle@v5` with build cache.
- Steps call `ci/java-*.sh` scripts; no inline logic over 3 lines.

Gates (all must pass):
1. `ci/java-format-check.sh` — Spotless/Google Java Format
2. `ci/java-lint.sh` — Error Prone + NullAway + SpotBugs + PMD + Checkstyle
3. `ci/java-test.sh` — JUnit 5 + JaCoCo 100% branch coverage
4. `ci/java-mutation.sh` — PIT 100% mutation kill
5. `ci/java-spdx-check.sh` — shared logic; wraps `scripts/check_spdx_headers.py`
6. OWASP Dependency-Check task (non-blocking until baseline established)

### 12. Publishing — GitHub Packages

`build.gradle.kts` declares a `MavenPublication`:

```kotlin
publishing {
    repositories {
        maven {
            name = "GitHubPackages"
            url = uri("https://maven.pkg.github.com/provide-io/provide-telemetry")
            credentials {
                username = System.getenv("GITHUB_ACTOR")
                password = System.getenv("GITHUB_TOKEN")
            }
        }
    }
    publications {
        create<MavenPublication>("gpr") {
            from(components["java"])
            groupId = "io.provide"
            artifactId = "telemetry"
            version = project.version.toString()
        }
    }
}
```

`.github/workflows/release.yml` gains a `publish-java` job triggered on
release tags that runs `./gradlew publish` with the repo's `GITHUB_TOKEN`.

### 13. Version Sync

`scripts/check_version_sync.py` parses `java/build.gradle.kts` for the
`version = "X.Y.Z"` declaration and asserts the major.minor matches root
`VERSION`. Java tracks patch versions independently (same pattern as the
other languages).

### 14. Repo-Wide Scripts

- `scripts/check_max_loc.py` — confirm `.java` is included; add if missing.
- `scripts/check_spdx_headers.py` — add Java `// SPDX-...` comment-style
  recognition.
- `.pre-commit-config.yaml` — new `java-format`, `java-lint`,
  `java-tests` hooks that invoke `./gradlew spotlessCheck`, `./gradlew check`,
  and `./gradlew test` respectively (can be slow — consider tagging `manual`
  stage for `java-tests`).

## Error Handling

- All public methods on `Telemetry` are defensive against null inputs via
  `Objects.requireNonNull(...)` with a clear message.
- `setupTelemetry()` never panics: config errors become `ConfigurationError`;
  OTel install errors become stderr warnings under `failOpen = true` and
  `TelemetryError` under `failOpen = false`.
- `shutdownTelemetry()` swallows exceptions from individual provider shutdowns
  and continues; final state is always "providers cleared, setup undone".

## What Does Not Change

- Other language SDKs — no behavioral changes.
- `spec/telemetry-api.yaml` — Java conforms to the existing spec without
  additions.
- `spec/validate_conformance.py` — no `language_overrides[java]` needed at
  v1 (full parity is the bar).
- Root `README.md` content structure — only the polyglot matrix gets a Java
  row.

## Scope

Single spec. One Gradle module, full API parity, full parity-harness
integration, full CI + mutation + coverage gates, GitHub Packages publish.
Framework-integration examples (Spring Boot auto-config, Micronaut, Quarkus,
ASGI-analog for JAX-RS/Servlet filters) are **out of scope** for v1 — they
are independent follow-up work analogous to the "frameworks" examples that
Python and Go have.

## Verification / Definition of Done

1. `./gradlew build` passes on Linux/macOS/Windows with Java 21.
2. `./gradlew check` runs all static analysis and reports zero violations.
3. `./gradlew jacocoTestCoverageVerification` passes at 100% branch coverage.
4. `./gradlew pitest` passes at 100% mutation kill score.
5. `spec/run_behavioral_parity.py --lang java --check-output --check-contracts`
   passes.
6. `spec/validate_conformance.py` passes with no `language_overrides[java]`.
7. `scripts/check_version_sync.py` passes.
8. `scripts/check_max_loc.py --max-lines 500` passes for all `.java` files.
9. `scripts/check_spdx_headers.py` passes for all Java source files.
10. `./gradlew publish` succeeds from the release workflow with a real
    `GITHUB_TOKEN`.
11. Root `README.md` polyglot matrix includes Java with the same feature
    checklist as the other languages.
