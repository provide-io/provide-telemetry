# Prometheus Metrics Support Design

**Date:** 2026-10-10

**Status:** Draft — no open questions; Rust renders the exposition itself (decision 2)

**Target release:** 0.9

## Purpose

Let every SDK's metrics reach Prometheus without the host building a second
metrics system. Today a pull-based host has to keep Prometheus separate and
switch provide-telemetry's metrics off. litevirt is the reference case: it
sets `PROVIDE_METRICS_ENABLED=false` so the shared OTLP endpoint does not
start an unowned metrics pipeline, keeps roughly 100 metrics on
`prometheus/client_golang`, and re-derives our health snapshot by hand as
`litevirt_telemetry_*` gauges so export health stays visible when OTLP is down.

## Current State

- Metrics flow through an OTel `MeterProvider` when the otel extra is present,
  and through in-process fallback instruments otherwise.
- The only metrics exporter is OTLP push, built from
  `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` / `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Go already accepts a host-built provider: `WithMeterProvider`
  (`go/setup.go`) is adopted by `go/otel/providers.go` when it is a
  `*sdkmetric.MeterProvider`. A Go host can attach the OTel Prometheus
  exporter today, but nothing makes it config-driven, consistent, or
  documented.
- The spec's metrics surface is `get_meter`, `counter`, `gauge`, `histogram`.
  There are no observable (callback) instruments, which is the main way
  Prometheus users compute values at scrape time.
- `health_snapshot` defines 26 canonical fields (8 per signal × 3 signals +
  2 global) that are not exposed as metrics anywhere.

## Goals

1. **Tier 1 — OTLP push to Prometheus.** Prove and document that the existing
   OTLP metrics exporter works against Prometheus 3's native OTLP receiver.
2. **Tier 2 — mountable pull handler.** Each SDK can return an HTTP handler
   (or a text renderer) serving Prometheus exposition format, for the host to
   mount on a server it already runs.
3. **Tier 3 — standalone listener.** Opt-in, config-driven, loopback-bound by
   default, for daemons with no HTTP server of their own.
4. **Observable instruments** in the spec and every SDK, so scrape-time values
   work without host-side collectors.
5. **Health as metrics.** The health snapshot is served as
   `provide_telemetry_*` metrics on the pull endpoint, so export health stays
   visible when push is failing.
6. One `MeterProvider`, multiple readers: OTLP and Prometheus serve the same
   recorded data. No parallel instrument system.

## Non-Goals

- Wrapping native Prometheus client libraries (`client_golang`,
  `prometheus_client`, `prom-client`, …) as a second instrument API.
- Pushgateway support. It suits batch jobs only and accumulates stale series.
- Prometheus remote_write from inside the SDK. It needs a local WAL, retries
  and batching — the collector's job.
- Pull support in the browser. Browser TypeScript is Tier 1 only.
- Prometheus exposition from the in-process fallback (no OTel installed). The
  fallback would need per-label-set storage; revisit after Stage 4.
- A `Reset()` on instruments. Series that must disappear use observable
  instruments, whose callbacks report only what currently exists.

## Architecture

```
          counter()/gauge()/histogram()/observable_*()
                              │
                      OTel MeterProvider
                      ┌───────┴────────┐
          PeriodicReader(OTLP)    Prometheus reader ── health collector
                 │                     │
            OTLP push           metrics_handler()  ──► host's HTTP server   (Tier 2)
     (collector, Prom 3,               │
      Mimir, OpenObserve)      standalone listener ──► 127.0.0.1:9464     (Tier 3)
```

The SDK owns the readers only when it built the provider. When a host supplies
its own provider (`WithMeterProvider` and equivalents), the SDK adds nothing
and `metrics_handler()` reports that it is unavailable, rather than silently
serving an empty registry.

### Configuration

Use the OTel-standard variables rather than new `PROVIDE_*` names. New entries
under `config.metrics` in `spec/telemetry-api.yaml`:

| Env | Default | Meaning |
|---|---|---|
| `OTEL_METRICS_EXPORTER` | `otlp` | Comma list of `otlp`, `prometheus`, `none`. `prometheus` attaches the pull reader; with a host/port set it also starts the Tier 3 listener. |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | `127.0.0.1` | Tier 3 bind host. The OTel spec default is `localhost`; we pin loopback so a library never exposes a port by accident. `0.0.0.0` is an explicit opt-in and logs a warning once at setup. |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | `9464` | Tier 3 bind port. |
| `PROVIDE_METRICS_PROMETHEUS_LISTEN` | `false` | Starts the Tier 3 listener. Kept separate from `OTEL_METRICS_EXPORTER=prometheus` so a host can enable the reader for Tier 2 without the SDK opening a port. Set it to `auto` to follow the OTel convention, where `OTEL_METRICS_EXPORTER=prometheus` alone starts the listener. |
| `PROVIDE_METRICS_PROMETHEUS_PATH` | `/metrics` | Tier 3 path. Must start with `/` and carry no query or fragment; an invalid value falls back to `/metrics` with the usual strict-mode error and one-time warning. Tier 2 ignores it, since the host picks the mount path. |
| `PROVIDE_METRICS_PROMETHEUS_TRANSLATION` | `UnderscoreEscapingWithSuffixes` | How metric names are translated; see [Metric names](#metric-names). |
| `PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS` | `false` | Add `otel_scope_name` / `otel_scope_version` labels to every series. |
| `PROVIDE_METRICS_PROMETHEUS_TARGET_INFO` | `true` | Emit the `target_info` series carrying resource attributes. |
| `PROVIDE_METRICS_HEALTH_OTLP` | `false` | Also export the health metrics over OTLP. See [Health metrics](#health-metrics). |

Rules:

- `otlp` stays the default, so nothing changes for existing users.
- `otlp` with no endpoint keeps today's behavior (no OTLP reader).
- `none` alone means no exporting readers; instruments still record into the
  fallback.
- An unknown value is a `ConfigurationError` in strict mode and a one-time
  warning otherwise, matching how other enum keys are parsed.
- `PROVIDE_METRICS_ENABLED=false` still disables everything, including the
  pull reader.

### Tier 2: the handler

Idiomatic per language, one behavior:

| Language | Shape |
|---|---|
| Python | `metrics_handler()` → ASGI app; `render_prometheus() -> tuple[bytes, str]` for WSGI and others |
| TypeScript (Node) | `metricsHandler()` → `(req, res) => void` for `node:http` / Express; `renderPrometheus()` |
| Go | `MetricsHandler() http.Handler` in the `otel` module |
| Rust | `render_prometheus(accept) -> Result<(Vec<u8>, &'static str), TelemetryError>`; `metrics_handler(method, accept)` returning status, headers and body for any HTTP server |
| C# | `MapProvideTelemetryMetrics(this IEndpointRouteBuilder)` plus `RenderPrometheus()` |

Behavior shared by all languages:

- `GET` only; `Content-Type` is the Prometheus text format, version `0.0.4`.
  OpenMetrics negotiation is optional per language and not required by
  conformance.
- Before setup, after shutdown, or when the host owns the provider: `503`
  with a one-line body naming the reason. Never an empty `200`, which reads as
  "process has no metrics" rather than "not wired".
- Called each scrape: observable callbacks run, then the health collector
  reads `get_health_snapshot()`.

### Tier 3: the standalone listener

- Started by `setup()` when `PROVIDE_METRICS_PROMETHEUS_LISTEN=true` (or `auto`
  with `prometheus` in `OTEL_METRICS_EXPORTER`), stopped
  by `shutdown()`, restarted on reconfiguration only if host or port changed.
- Serves the Tier 2 handler at `PROVIDE_METRICS_PROMETHEUS_PATH` (default
  `/metrics`, Prometheus's default `metrics_path`); every other path is `404`.
- Server timeouts set (read-header, read, write, idle) so a slow client cannot
  hold the listener; litevirt's `server_timeouts_test.go` covers the same
  concern.
- If the bind fails (port in use), setup logs one warning and continues. Pull
  is never allowed to break the host. The failure appears in health as
  `setup_error`.

### Securing the listener and push

The Tier 3 listener reads the same web config file Prometheus itself takes as
`--web.config.file`, named by `PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG`:

```yaml
tls_server_config:
  cert_file: server.crt
  key_file: server.key
  client_ca_file: clients-ca.crt   # optional: mutual TLS
  min_version: TLS12
basic_auth_users:
  scraper: $2a$10$...               # bcrypt hash
```

Reusing that format means an operator who already secures Prometheus or an
exporter has nothing new to learn, and one file can serve both. Every SDK reads
a fixed subset of keys (`prometheus_metrics.listener_security` in the spec) so
the same file behaves the same way in all five. The listener fails closed: any
problem with the file, or with a certificate or key it names, keeps the
listener from starting rather than serving plain HTTP or skipping auth.
Certificates are re-read when they change, so rotation needs no restart. Port
and path stay on their own settings.

Push uses the standard OTel variables in every SDK: per-signal and shared
`OTEL_EXPORTER_OTLP_*_HEADERS` for basic auth or bearer tokens, and
`OTEL_EXPORTER_OTLP_*_CERTIFICATE`, `_CLIENT_CERTIFICATE` and `_CLIENT_KEY`
for a private CA and mutual TLS. A certificate that cannot be read leaves that
signal's exporter uninstalled with `setup_error` set, rather than being
ignored.

Stage 2 measured where each SDK stands today by pushing to a Prometheus that
requires basic auth, and to one that also requires TLS from a private CA:

| SDK | Basic auth via `OTEL_EXPORTER_OTLP_METRICS_HEADERS` | Private CA via `OTEL_EXPORTER_OTLP_CERTIFICATE` |
|---|---|---|
| Python, TypeScript, Go | works | works |
| Rust | works | ignored: export fails silently (closed in Stage 5: honoured, with mutual TLS) |
| C# | ignored (shared `OTEL_EXPORTER_OTLP_HEADERS` only) | ignored: export fails silently |

The gaps are recorded in `push_ingestion.unsupported_modes` and asserted by the
E2E test, so closing one fails the test until its entry is removed.

### Observable instruments

New spec entries under `api.metrics`:

```yaml
- name: observable_counter
  kind: function
  required: true
- name: observable_gauge
  kind: function
  required: true
- name: observable_up_down_counter
  kind: function
  required: false
```

Each takes a name, optional description and unit, and a callback that reports
`(value, attributes)` observations. Callbacks run on collection: each scrape
for Prometheus, each export interval for OTLP. Rules:

- A callback that raises or panics is caught, counted, and contributes no
  observations for that collection. It never fails the scrape.
- With no live provider, callbacks are registered against the fallback and
  run when `get_health_snapshot()` or a test helper asks for collection, so the
  fallback stays testable.
- The returned registration can be unregistered, so a host can drop a
  callback on reconfiguration.

### Health metrics

The health collector maps `health_snapshot` onto these series:

| Snapshot field | Metric | Type |
|---|---|---|
| `emitted_<signal>` | `provide_telemetry_emitted_total{signal}` | counter |
| `dropped_<signal>` | `provide_telemetry_dropped_total{signal}` | counter |
| `export_failures_<signal>` | `provide_telemetry_export_failures_total{signal}` | counter |
| `retries_<signal>` | `provide_telemetry_export_retries_total{signal}` | counter |
| `export_latency_ms_<signal>` | `provide_telemetry_export_latency_milliseconds{signal}` | gauge |
| `async_blocking_risk_<signal>` | `provide_telemetry_async_blocking_risk_total{signal}` | counter |
| `circuit_state_<signal>` | `provide_telemetry_circuit_state{signal}` (0 closed, 1 half-open, 2 open) | gauge |
| `circuit_open_count_<signal>` | `provide_telemetry_circuit_open_total{signal}` | counter |
| `setup_error` | `provide_telemetry_setup_error` (1 when set) | gauge |
| `receipt_failures` | `provide_telemetry_receipt_failures_total` | counter |

By default these are written straight into the Prometheus output by a
collector on the pull path. They do not go through the `MeterProvider`, so
OTLP does not export health about OTLP. Push-only users can set
`PROVIDE_METRICS_HEALTH_OTLP=true`, which registers the same series as
observable instruments on the provider so they reach OTLP too. When both pull
and that flag are on, the pull endpoint still serves health from its own
collector and the provider copy is filtered out of the pull output, so no
series appears twice. The docs warn that health pushed over OTLP goes quiet
exactly when OTLP export fails, so alerts should use `absent()` rather than
thresholds. The circuit-state encoding matches what litevirt uses today,
so its dashboards keep working after migration.

### Metric names

The OTel Prometheus exporters translate names: dots become underscores,
counters get `_total`, units become suffixes, and by default a `target_info`
series and `otel_scope_*` labels are added. Our own SLO instruments are
affected. `http.requests.total` and `http.request.duration_ms` (unit `ms`) are
expected to come out as `http_requests_total` and something like
`http_request_duration_ms_milliseconds`. Each exporter's exact output must be
captured in a fixture during Stage 2.

Translation is configurable with `PROVIDE_METRICS_PROMETHEUS_TRANSLATION`.
The values reuse the names of Prometheus 3's own OTLP receiver setting
(`otlp.translation_strategy`), so a service can produce the same names whether
it is pushed (Tier 1) or scraped (Tiers 2 and 3) by setting both sides to the
same value:

| Value | Characters | Suffixes | Example for `http.request.duration_ms` (unit `ms`) |
|---|---|---|---|
| `UnderscoreEscapingWithSuffixes` (default) | invalid characters become `_` | `_total` and unit suffixes added | `http_request_duration_ms_milliseconds` |
| `UnderscoreEscapingWithoutSuffixes` | invalid characters become `_` | none added | `http_request_duration_ms` |
| `NoUTF8EscapingWithSuffixes` | kept as UTF-8 | added | `http.request.duration_ms_milliseconds` |
| `NoTranslation` | kept as UTF-8 | none added | `http.request.duration_ms` |

The examples are the expected output; Stage 1 pins the exact strings in the
exposition fixture. The UTF-8 values need Prometheus 3 on the scraping side
and content negotiation in the handler; older scrapers get the default.

`UnderscoreEscapingWithoutSuffixes` is the migration path for hosts with
hand-written `client_golang` names: litevirt can keep
`litevirt_lb_keepalived_up` and its Grafana dashboards unchanged.

Contract:

- Translation is done by one shared rule-set per value, defined in the spec
  and checked by the cross-language fixture, not by whatever each exporter does
  by default. Where an exporter cannot be configured to match, the SDK
  translates before handing names to it.
- Under the `WithSuffixes` values, a unit suffix is not appended when the name
  already ends with the unit or its Prometheus base-unit equivalent, and
  `_total` is not appended twice.
- `otel_scope_*` labels and `target_info` follow their own switches
  (default off and on respectively), independent of the translation value.
- An unknown translation value falls back to the default, with the same
  strict-mode error and one-time warning as other enum keys.

### Temporality and cardinality

- Prometheus requires cumulative temporality. When `prometheus` is in
  `OTEL_METRICS_EXPORTER`, the pull reader is cumulative regardless of any
  delta preference, and a delta setting on the OTLP reader is left alone.
- The Prometheus OTLP receiver also rejects delta by default, so Tier 1 docs
  state that the OTLP reader must be cumulative (our default).
- Under pull, every label set stays in memory for the life of the process.
  The existing cardinality guards apply to instruments read by the pull
  reader, and the docs tell pull users to register limits with
  `register_cardinality_limit` for every attribute that is not a fixed set.

### Per-language notes

| Language | Exporter | Tier 1 | Tier 2 | Tier 3 | Notes |
|---|---|---|---|---|---|
| Go | `go.opentelemetry.io/otel/exporters/prometheus` | ✓ | ✓ | ✓ | Reference implementation. Use a private `prometheus.Registry`, never the default one, so hosts that already use `client_golang` do not collide. |
| Python | `opentelemetry-exporter-prometheus` | ✓ | ✓ | ✓ | Multi-process servers (gunicorn) get one registry per worker. Docs say to use Tier 1 push there; no multiprocess-mode support. |
| TypeScript | own renderer (port of Python's) | ✓ | Node only | Node only | The browser build excludes the pull code entirely. |
| Rust | own renderer over a cumulative `ManualReader` | ✓ | ✓ | feature `prometheus-listener` | The upstream crate is discouraged by opentelemetry-rust and its naming does not match the fixtures, so the SDK renders `ResourceMetrics` itself with a port of otlptranslator's namers (decision 2). The listener runs on its own threads, so the host needs no async runtime. |
| C# | `OpenTelemetry.Exporter.Prometheus.AspNetCore` / `.HttpListener` | ✓ | ✓ | ✓ | Both packages are prerelease. Lives in `Provide.Telemetry.OpenTelemetry`, never in the OTel-free core. |

Exporter maturity is as of this draft and is re-checked at the start of each
language's stage.

## Testing

- **Unit:** config parsing for every new key and invalid value; handler
  status codes (before setup, after shutdown, host-owned provider); callback
  failure isolation; listener start, stop, rebind and bind failure; health
  mapping for every field.
- **Shared fixtures:** `spec/prometheus_fixtures.yaml` holds the cases every
  SDK runs: metric and label names for each translation value (generated
  with `github.com/prometheus/otlptranslator` v1.0.0, the reference), config
  parsing, listener paths, handler status codes and the health mapping.
  Output is compared by sample (name, labels, value), not by exposition bytes,
  because float formatting and line order legitimately differ between
  exporters.
- **Scrape test:** each SDK starts a Tier 3 listener on an ephemeral port and
  scrapes it over real HTTP.
- **E2E:** Prometheus 3 with `--web.enable-otlp-receiver`, in three
  instances: plain, basic auth, and TLS from a generated private CA plus basic
  auth (`ci/prometheus-tls-setup.sh`). The push test (Tier 1, done) runs every
  SDK against all three. Stage 3 adds the reverse: Prometheus scraping each
  SDK's Tier 3 listener plain and with the listener secured by a web config.
- **Gates:** 100% branch coverage and 100% mutation kill apply as usual. New
  files stay under 777 lines; the handler, listener, health collector and name
  translation are separate files in each language.

## Delivery Stages

Each stage is its own PR and leaves `main` releasable.

1. **Spec and fixtures** (done). The `prometheus_metrics` section of
   `spec/telemetry-api.yaml`, the `observable_*`, `metrics_handler` and
   `render_prometheus` symbols behind the `observable_metrics` and
   `prometheus` capabilities, and `spec/prometheus_fixtures.yaml`. Each
   capability's language set in `spec/validate_conformance.py` starts empty
   and gains a language in the PR that ships it, after which a missing export
   fails conformance. New config keys sat in `prometheus_metrics.planned_config`
   until an SDK parsed them, then moved to `config_defaults`, whose
   applicability list cannot be empty. The OTLP TLS variables that remained
   are read by the exporter builders rather than parsed as config, so the
   section is now `prometheus_metrics.push_tls_env`.
   `tests/tooling/test_prometheus_contract.py` keeps the spec section, the
   fixtures and the capability gates consistent with each other.
2. **Tier 1 everywhere** (done). Prometheus 3.13.4 in `docker-compose.yml`
   with `infra/prometheus/prometheus.yml`, a `prometheus_push_probe` per SDK,
   `e2e/test_prometheus_push_e2e.py`, the `prometheus-push` job in
   `ci-contracts.yml`, and a "Sending Metrics to Prometheus" section in
   `docs/guide/configuration.md`. No SDK code changed. All five SDKs push
   successfully; Go's names match the contract exactly. The run surfaced two
   more divergences, now in `push_ingestion.known_divergences`: Rust drops
   instrument units and descriptions before they reach OTel, and the C#
   facade has no unit parameter. Both are since closed: Rust passes the unit and
   description to its OTel instruments, the C# facade takes optional
   description and unit, and their entries are gone.
   A follow-up within Stage 2 added the basic-auth and TLS push modes and
   measured the gaps in the table under "Securing the listener and push".
3. **Go: observable instruments, Tiers 2 and 3 with listener TLS and basic
   auth, health collector** (done). Config keys parsed and moved into
   `config_defaults` for Go; the OTel Prometheus exporter v0.66.0 (matching
   OTel v1.44 and the fixtures' otlptranslator v1.0.0) on a private registry;
   `MetricsHandler()` / `RenderPrometheus()` in the otel module with a 503 per
   not-ready state; the health collector; the listener with the web config
   subset, certificate reload and fail-closed startup, reporting failures
   through the new `BackendSetupState.ReportSetupError`; observable instruments
   through an optional `ObservableBackend` interface. Every Go-applicable case
   in `spec/prometheus_fixtures.yaml` runs as a Go test, Go is in the
   `observable_metrics` and `prometheus` capability sets, and
   `e2e/test_prometheus_scrape_e2e.py` has a real Prometheus scrape the Go
   listener plain and over TLS with basic auth. litevirt can now move `:7444`
   onto `MetricsHandler()` and delete its `telemetryCollector`.
4. **Python** (done), then **TypeScript (Node)** (done), same scope as Stage 3.
   Python: config keys in `_config_prometheus.py`; `gauge()` moved to an OTel
   Gauge, closing its half of decision 0; a port of otlptranslator's namers
   (`metrics/_prom_names.py`) checked against every translation, label and
   translator-only case; a text-format renderer with scrape-time UTF-8
   negotiation; a pull `MetricReader` with the not-ready statuses (plus
   `process_locked`, for OpenTelemetry's once-per-process global provider);
   `metrics_handler()` as an ASGI app and `render_prometheus()`; the listener on
   `http.server` with the web config subset, certificate reload and fail-closed
   startup (`bcrypt` and `PyYAML` in the `prometheus` extra); observable
   instruments. Python is in both capability sets and in the scrape E2E.
   `PROVIDE_METRICS_HEALTH_OTLP` registers the health families as observable
   instruments on the installed provider in Python and Go alike
   (`prometheus_metrics.health_metrics.health_otlp`); a scrape still carries
   each family once.
   TypeScript: the config keys in `config-prometheus.ts`; `gauge()` on an OTel
   Gauge, closing the other half of decision 0 and its push divergence; a port
   of the namers (`prom-names.ts`) and the renderer (`prom-render.ts`) rather
   than `@opentelemetry/exporter-prometheus`, whose naming does not follow
   otlptranslator; a cumulative pull `MetricReader` with the not-ready statuses
   (plus `otel_disabled` for `otelEnabled: false`), attached by
   `registerOtelProviders()`; `metricsHandler()` (a `(req, res)` listener) and
   `renderPrometheus()` from the Node-only `@provide-io/telemetry/prometheus`
   entry; the listener on `node:http`/`node:https`, loaded through a
   runtime-only import so the browser bundle never contains it (a test bundles
   the browser entries with esbuild to prove it), with the web config subset,
   per-connection certificate reload and fail-closed startup (`yaml` and
   `bcryptjs` as optional peers); observable instruments. TypeScript is in both
   capability sets and in the scrape E2E; `PROVIDE_METRICS_HEALTH_OTLP` and the
   unreadable-TLS-file rule of `push_security` behave as in Python and Go.
5. **Rust and C#**, including the push-security gaps (private CA in both,
   per-signal headers in C#). `metrics_handler` becomes `required: true` in the
   spec once all five ship.
   C# (done): config keys parsed in the core (`PrometheusSettings`); `gauge()`
   was already an OTel Gauge; a port of the otlptranslator namers and of
   Python's text renderer in `Provide.Telemetry.OpenTelemetry/Prometheus/`,
   checked against every translation, label and translator-only case; a
   cumulative pull reader (`BaseExportingMetricReader` over a capturing
   exporter, not the prerelease `OpenTelemetry.Exporter.Prometheus.*`
   packages, whose names differ from the fixtures) with one 503 reason per
   not-ready status; `PrometheusMetrics.RenderPrometheus(accept)` and a
   framework-neutral `PrometheusMetrics.MetricsHandler(method, accept)`; the
   listener on `TcpListener` + `SslStream` (`HttpListener` cannot serve TLS on
   Linux) with the web config subset (YamlDotNet, BCrypt.Net-Next),
   certificate reload and fail-closed startup, reported through a new
   `ITelemetryBackend.Configure` hook; observable instruments through an
   optional `IObservableMeter`. The push gaps are closed: per-signal headers
   replace the shared ones, and `OTEL_EXPORTER_OTLP[_SIGNAL]_CERTIFICATE`,
   `_CLIENT_CERTIFICATE` and `_CLIENT_KEY` feed a custom `HttpClientFactory`;
   a file that cannot be read or loaded leaves that signal's OTLP exporter
   unbuilt with `setup_error` set, as in Python and Go.
   `PROVIDE_METRICS_HEALTH_OTLP` registers the health families as observable
   instruments too. C# is in both capability sets and in the scrape E2E.
   Rust (done): config keys in `config/prometheus.rs`; the OTLP client TLS
   variables for every signal and transport (`OTEL_EXPORTER_OTLP_*CERTIFICATE`,
   `_CLIENT_CERTIFICATE`, `_CLIENT_KEY`), which close its `tls_basic_auth`
   push gap; `gauge()` was already an OTel Gauge. No exporter crate: a
   cumulative `ManualReader` feeds a renderer ported from the Python one
   (`prometheus/render.rs`, with scrape-time UTF-8 negotiation) and a port of
   otlptranslator's namers (`prometheus/names.rs`) checked against every
   translation, label and translator-only case. `render_prometheus(accept)` and
   a framework-neutral `metrics_handler(method, accept)` serve the not-ready
   statuses and the health families. The listener, behind the
   `prometheus-listener` feature, is std threads plus rustls with the web
   config subset, certificate reload, fail-closed startup and bcrypt basic auth.
   Observable instruments filter out series their callback stopped reporting,
   which the Rust SDK would otherwise keep exporting under cumulative
   temporality. Like the others, the OTLP TLS variables are read when an
   exporter is built: a file that cannot be read or loaded leaves that
   signal's exporter unbuilt with `setup_error` naming the variable, and
   `PROVIDE_METRICS_HEALTH_OTLP` registers the health families as observable
   instruments, which the pull renderer leaves out of a scrape. Rust is in
   both capability sets and in the scrape E2E.

## Decisions

0. **Gauge semantics are canonical.** Stage 1 found that Python and TypeScript
   back `gauge()` with an OTel UpDownCounter while Go, Rust and C# use a real
   Gauge. Under the suffix strategies that changes names (unit `1` becomes
   `_ratio` only for a gauge). The spec records it under
   `translation.known_divergences`; Python and TypeScript align before they
   join the `prometheus` capability.

1. **Everything that changes behavior is configurable.** Listener start,
   name translation, scope labels, `target_info` and health over OTLP each
   have their own key with a conservative default: no port opened unless
   asked, Prometheus 3's default translation, no scope labels, health on pull
   only.

2. **Rust renders the exposition itself.** The upstream
   `opentelemetry-prometheus` crate is discouraged by opentelemetry-rust and
   cannot be configured to produce every translation strategy's names, so the
   Rust SDK reads `ResourceMetrics` from its own pull reader and renders them
   with the same rules as Python.

## Open Questions

None.
