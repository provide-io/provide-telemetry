# Prometheus Metrics Support Design

**Date:** 2026-10-10

**Status:** Draft — one open question (Rust exporter) remains, needed before Stage 5

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
- Auth or TLS on the Tier 3 listener. Hosts that need either mount the Tier 2
  handler behind their own server.
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
| Rust | `render_prometheus() -> (Vec<u8>, &'static str)`; an `axum`/`hyper` adapter behind a feature flag |
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
- Serves the Tier 2 handler at `/metrics`; every other path is `404`.
- Server timeouts set (read-header, read, write, idle) so a slow client cannot
  hold the listener; litevirt's `server_timeouts_test.go` covers the same
  concern.
- If the bind fails (port in use), setup logs one warning and continues. Pull
  is never allowed to break the host. The failure appears in health as
  `setup_error`.

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
| TypeScript | `@opentelemetry/exporter-prometheus` | ✓ | Node only | Node only | The browser build excludes the pull code entirely. |
| Rust | `opentelemetry-prometheus` or own renderer | ✓ | ✓ | feature `prometheus-listener` | The upstream crate is discouraged by opentelemetry-rust. Stage 5 decides between it and rendering from `ResourceMetrics` ourselves. |
| C# | `OpenTelemetry.Exporter.Prometheus.AspNetCore` / `.HttpListener` | ✓ | ✓ | ✓ | Both packages are prerelease. Lives in `Provide.Telemetry.OpenTelemetry`, never in the OTel-free core. |

Exporter maturity is as of this draft and is re-checked at the start of each
language's stage.

## Testing

- **Unit:** config parsing for every new key and invalid value; handler
  status codes (before setup, after shutdown, host-owned provider); callback
  failure isolation; listener start, stop, rebind and bind failure; health
  mapping for every field.
- **Exposition fixture:** one shared fixture in `spec/` listing instruments to
  create and the exact expected exposition lines for each translation value
  and each scope-label / `target_info` switch. Every SDK must produce
  byte-identical output after sorting lines, which enforces the naming
  contract.
- **Scrape test:** each SDK starts a Tier 3 listener on an ephemeral port and
  scrapes it over real HTTP.
- **E2E:** a Prometheus 3 container with `--web.enable-otlp-receiver` added to
  `docker-compose.yml`. One test pushes over OTLP (Tier 1) and one has
  Prometheus scrape the listener (Tier 3); both query the result back through
  the Prometheus HTTP API.
- **Gates:** 100% branch coverage and 100% mutation kill apply as usual. New
  files stay under 777 lines; the handler, listener, health collector and name
  translation are separate files in each language.

## Delivery Stages

Each stage is its own PR and leaves `main` releasable.

1. **Spec and docs.** New config keys, `observable_*` entries,
   `metrics_handler` (`required: false`), the health metric mapping, the name
   rule-set and the exposition fixture. `spec/validate_conformance.py` learns
   the new optional entries.
2. **Tier 1 everywhere.** Prometheus 3 in `docker-compose.yml`, the OTLP→Prom
   E2E test, and a "Sending metrics to Prometheus" section in
   `docs/guide/configuration.md`. Expected to need little or no SDK code.
3. **Go: observable instruments, Tiers 2 and 3, health collector.** litevirt
   trials it by moving `:7444` onto `MetricsHandler()` and deleting its
   `telemetryCollector`.
4. **Python**, then **TypeScript (Node)**, same scope as Stage 3.
5. **Rust and C#.** `metrics_handler` becomes `required: true` in the spec once
   all five ship.

## Decisions

1. **Everything that changes behavior is configurable.** Listener start,
   name translation, scope labels, `target_info` and health over OTLP each
   have their own key with a conservative default: no port opened unless
   asked, Prometheus 3's default translation, no scope labels, health on pull
   only.

## Open Questions

1. **Rust exporter.** Take the discouraged upstream `opentelemetry-prometheus`
   crate now, or write the renderer ourselves from `ResourceMetrics` from the
   start? Configurable translation favors our own renderer, since the upstream
   crate may not support every value.
