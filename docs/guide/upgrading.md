# Upgrading

Changes that alter what a service emits or counts without changing any
function signature. Code that compiles against the new version can still
behave differently, so read the entries between your old version and the new
one. [CHANGELOG.md](../../CHANGELOG.md) has the full detail for each release.

## To 0.11

### Stamped fields replace caller fields of the same name

The SDK stamps `service`, `env` and `version` from config, and `trace_id` and
`span_id` from the live span. A caller field or bound-context field with one of
those names is now replaced by the stamped value, in all five languages. Before
0.11 the record could carry both, and a backend kept whichever one it happened
to keep.

What to check:

- **A field you log under one of those names for another purpose.** A
  `version` meaning a schema, certificate revocation list or image version is
  lost on every record once `PROVIDE_TELEMETRY_VERSION` is set. Rename it:
  `schema_version`, `crl_version`, `image_version`.
- **A field naming another service.** Use `peer.service`, which is not
  reserved.
- **Go:** the raw spellings `service.name`, `service.env`, `service.version`,
  `trace.id` and `span.id` are reserved along with the wire names.
- **C#:** the `service_name` and `environment` attributes are reserved too.

In releases after 0.11.0, a replacement that loses a different value is not
silent: it adds to the `reserved_field_replacements` health counter, and the
first one for each field logs a WARN record, `logger.reserved_field.replaced`,
naming the field. Search for that event, or watch
`provide_telemetry_reserved_field_replacements_total`, to find the fields to
rename.

A field is replaced only when the SDK has a value of its own: an empty config
value, or no live span, leaves the caller's field standing. Nested fields are
never touched. In Python, `console` and `pretty` output does not stamp
`service`, `env` or `version`, so those formats keep the caller's value.

### Log health counters count different things

- **A consent refusal now counts toward `dropped_logs`,** as sampling and
  backpressure refusals already did. Before 0.11, Python, TypeScript, Go and
  Rust counted nothing for it.
- **`emitted_logs` counts a record after both its local and backend sinks,**
  not when it is admitted. A record whose backend export fails still counts as
  emitted and adds to `export_failures_logs`; a refused record never counts.
- **A failing log output writer counts toward `export_failures_logs`.** This
  covers Go's `WithLogOutput` and Python's and Rust's `set_log_output`: a writer
  that returns an error or panics, and a record the writer logs back from
  inside its own write, which is dropped. Go already counted the first case.
  TypeScript and C# have no log output writer.

Dashboards and alerts on these counters will see their values move without any
change in traffic.

## To 0.9

### Caller fields are emitted

`PROVIDE_LOG_INCLUDE_CALLER` is on by default and adds `filename` (a base name)
and `lineno` to every record. Go and C# honour it from 0.9: before, each parsed
the variable into a config field nothing read. TypeScript renamed its
`caller_file` and `caller_line` to `filename` and `lineno` in the same release.

The fields name the frame that called the logger. Where another logging
library is bridged into this one through an adapter, that frame is the
adapter's, unless the adapter passes on its caller. To leave the fields out,
set `PROVIDE_LOG_INCLUDE_CALLER=false`.

## To 0.8

### `CRITICAL` is its own level, above `ERROR`

The `level` field is one vocabulary in every language:
`TRACE DEBUG INFO WARN ERROR CRITICAL`. `PROVIDE_LOG_LEVEL=CRITICAL` therefore
admits CRITICAL records only and drops ERROR, as any threshold drops the levels
below it. Where a threshold of `CRITICAL` was used to mean "errors and worse",
set `ERROR`.

Python's lowercase levels and TypeScript's numeric pino levels are gone from
the output: a query for `level="WARN"` now matches all five languages.

## Using your own OpenTelemetry providers

Export health (`export_failures_*`, `retries_*`, `circuit_state_*`) is measured
by the resilient exporter wrappers the SDK puts around the exporters it builds.
A host that passes its own provider (`WithTracerProvider` in Go, and the
equivalents elsewhere) exports through its own exporters, which those wrappers
never see, so that signal's export counters stay at zero and its circuit stays
`closed` whatever the collector does. Let the SDK build the provider when those
numbers matter. In Go, the provider `go/otel` builds already samples with
`ParentBased(TraceIDRatioBased)` at `PROVIDE_TRACE_SAMPLE_RATE`, and a test pins
that a collector refusing its spans shows up in `TracesExportFailures`.
