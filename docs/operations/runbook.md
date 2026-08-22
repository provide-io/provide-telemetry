# Operations Runbook

## Runtime Defaults

- Python: 3.11+
- Log format default: `console`
- Event schema validation: disabled by default (`PROVIDE_TELEMETRY_STRICT_EVENT_NAME=false`)
- Strict schema mode: off by default (`PROVIDE_TELEMETRY_STRICT_SCHEMA=false`)

See also: [`docs/operations/production-profiles.md`](production-profiles.md) for strict/compat/high-throughput presets.

## Core Environment Variables

All environment variables with types, defaults, and descriptions are documented in the
[Configuration Reference](../guide/configuration.md). The most commonly set variables are
`PROVIDE_TELEMETRY_SERVICE_NAME`, `PROVIDE_LOG_LEVEL`, and `PROVIDE_LOG_FORMAT`.

## Event Naming Policy

Canonical naming rules and examples live in [`docs/guide/conventions.md`](../guide/conventions.md).
Operationally, keep strict validation enabled unless you are in an explicit migration window.

## Failure Behavior

Symptom first. The three rows that carry per-language nuance link to a section
below; the rest are self-contained.

| Symptom | Cause | What to check |
|---|---|---|
| Nothing is emitted at all, and one warning naming an env value appeared at startup | `PROVIDE_CONSENT_LEVEL` was set to a value the SDK does not recognise, so consent failed closed to `NONE` | [Consent gate](#consent-gate) |
| Logs still flow, but no spans and no OTel metrics | OTel packages are missing; tracing falls back to no-op tracers and metrics to in-process wrappers | Install the `otel` extra for your language |
| Records carry a `_schema_error` field | An invalid event name under strict event mode, or a key listed in `PROVIDE_TELEMETRY_REQUIRED_KEYS` is absent | Required keys are enforced whenever the variable is set, regardless of strict schema mode. The direct helpers — `event()`, `event_name()`, `validate_event_name()`, `validate_required_keys()` — raise `EventSchemaError` instead of annotating |
| Log records have no trace IDs after propagation | The inbound W3C `traceparent` was rejected: all-zero IDs, reserved version `ff`, or an invalid flags/version token. Rejected values are never bound | The caller's header |
| A request handler stalls during export | Exporter retries/backoff are running on the event loop | [Async services](#async-services-and-the-blocking-guard) |
| An export runs past `PROVIDE_EXPORTER_*_TIMEOUT_SECONDS` | Four runtimes enforce that variable; C# does not | [Exporter timeouts](#exporter-timeouts) |

### Consent gate

A set, non-empty `PROVIDE_CONSENT_LEVEL` that is not `FULL`, `FUNCTIONAL`,
`MINIMAL` or `NONE` (trimmed, case-insensitive) sets consent to `NONE` and
writes one warning per process naming the value. Collection stops: an opt-out
control must not keep collecting because the operator misspelled it.

Unset and blank (empty or whitespace-only) are no-ops, so `PROVIDE_CONSENT_LEVEL=`
in a compose file changes nothing. The warning is deliberately written outside
the SDK's own logger — Python `RuntimeWarning`, TypeScript `console.warn`, Go,
Rust and C# on stderr — because the `NONE` it just applied would silence a log
record. Confirm the applied level with `get_consent_level()` /
`GetConsentLevel()` / `getConsentLevel()`.

Every SDK reads the variable at `setup_telemetry()` and on the first
`get_logger()` in a process that never called setup. A `set_consent_level()`
made after setup is never overwritten by the environment.

### Async services and the blocking guard

Keep exporter retries and backoff at zero, the default. Non-zero values can
block request handlers, and what happens then differs by runtime:

- **Python and Go** carry a runtime guard. A retry/backoff that would block an
  event loop is refused (fail-fast) unless
  `PROVIDE_EXPORTER_*_ALLOW_BLOCKING_EVENT_LOOP=true`, and each suppressed call
  increments `async_blocking_risk_*`.
- **TypeScript and Rust** have no such variable — `spec/telemetry-api.yaml`
  scopes it to Python and Go — and no blocking guard. They only count
  `async_blocking_risk_*`: in Node a drain that would have blocked, in Rust a
  flush/shutdown drain.
- **C# has neither the variable nor a guard.** `ExporterPolicy` has no
  `AllowBlockingInEventLoop` field and `async_blocking_risk_*` is always zero.
  Its drains run on the thread pool via `ResilientExporter.DrainAsync`, so the
  practical exposure differs from a blocked event loop.

### Exporter timeouts

`PROVIDE_EXPORTER_*_TIMEOUT_SECONDS` is enforced at exporter construction and
per-batch export in Python, TypeScript, Go and Rust. Timed-out attempts count
as failures and follow the retry/fail-open policy. Per-language module
references are in the Resilience table of
[`docs/internal/internals.md`](../internal/internals.md).

**C# bounds exports differently.** Its OTLP exporters are built without an
explicit timeout (`Endpoints.Apply` sets endpoint, protocol and headers only).
The per-attempt budget comes from the absolute deadline that
`FlushTelemetry(timeout)` / `ShutdownTelemetry()` computes — ten seconds by
default, shared by every signal, so three installed providers cost one budget
rather than three. `TimeoutSeconds` survives only as the gate deciding whether
the circuit breaker is consulted at all (`ResilienceExecutor`, matching
Python's `TimeoutSeconds > 0` rule). To bound a C# export, pass the timeout to
`FlushTelemetry`; setting the environment variable will not do it.

## Lifecycle

- Call `setup_telemetry()` once during process startup.
- Call `shutdown_telemetry()` during graceful shutdown to flush providers.
- `setup_telemetry()` and `shutdown_telemetry()` are lock-serialized; concurrent calls are safe.
- After `shutdown_telemetry()`, package-local setup state is cleared. If real
  OTel providers had been installed, provider-changing lifecycle transitions
  still require a full process restart before `setup_telemetry()`.
- Runtime reconfiguration APIs mutate internal process state only. Read the
  active snapshot back via `get_runtime_config()` / `GetRuntimeConfig()` /
  `getRuntimeConfig()` rather than assuming the caller still owns a live config
  object.

## Local Health Check

```bash
uv sync --group dev
uv run python scripts/check_max_loc.py --max-lines 777
uv run python scripts/check_event_literals.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run ty check src tests
uv run bandit -r src -ll
uv run python -m pip_audit --path .
uv run python scripts/run_pytest_gate.py
uv sync --group dev --extra otel
uv run python scripts/run_pytest_gate.py -m otel -q
# Optional full e2e (requires live OpenObserve)
uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q
# Optional fuzz/property run
uv run python scripts/run_pytest_gate.py tests/fuzz tests/property --no-cov
# Optional mutation pass (can take time)
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1 --min-mutation-score 95
# Optional performance smoke (report-only by default)
uv run python scripts/run_performance_smoke.py --iterations 300000
```

Note: `run_mutation_gate.py` injects a no-op `setproctitle` shim for mutmut
subprocesses to avoid known segfault behavior on some hosts.
Marker-specific runs (`-m otel`, `-m e2e`, `tests/fuzz`/`tests/property`, and
the like) should keep passing `--no-cov`: the strict 100% coverage gate applies
only to the default `pytest` run.

## Mutation Policy Files

- `pyproject.toml` `[tool.mutmut] source_paths` is the source of truth for Python
  mutation roots — it is what `scripts/run_mutation_gate.py` actually runs against.
- The bar is a **100% kill** — `_is_clean()` in `scripts/run_mutation_gate.py` passes
  only on zero survivors, timeouts, suspicious and no-tests results. The `95.0`
  `--min-mutation-score` floor (configured in `scripts/run_mutation_gate.py` and
  `.github/workflows/ci-mutation.yml`) is a second guard against an implausibly
  short run, not the threshold to aim for.
- If mutation roots or test selection change, rerun the local mutation gate
  before declaring policy status, so the baseline is not stale.

## Docs Quality

The `docs-quality` CI job is a required gate. Run the same checks locally:

```bash
uv sync --group dev
uv run python scripts/check_docs_accuracy.py
uv run python scripts/run_pytest_gate.py tests/docs tests/tooling/test_check_docs_accuracy.py --no-cov -q
```

## Act / Docker-in-Docker Quality Runs

Use the checked-in wrapper for local `act` runs:

```bash
scripts/act_local.sh push -W .github/workflows/ci-mutation.yml -j changes
scripts/act_local.sh push -W .github/workflows/ci-typescript.yml -j otlp-integration
```

The wrapper clones third-party actions into `.provide/act-actions`, checks out the exact
SHA-pinned refs from the workflows, and passes `--local-repository` mappings to `act`.
This works around `act` versions that try to fetch SHA pins as branch refs without
weakening GitHub Actions supply-chain pinning.

When acting as a local runner on macOS with `colima`, keep the job-container socket as
`unix:///var/run/docker.sock`:

```bash
scripts/act_local.sh pull_request -W .github/workflows/ci-shared.yml -j docs-quality
```

Passing the macOS `~/.colima/.../docker.sock` path as `--container-daemon-socket` makes
Docker try to mount that host path inside the Linux VM and can fail before workflow
steps start.

## OpenObserve Validation

After running `uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q` with the `OPENOBSERVE_*`
env vars in place, verify telemetry landed:

1. Browse `http://localhost:5080/web/streams?org_identifier=default` and look for `provide-telemetry` streams.
2. Search for `e2e.openobserve.span` or the metric stream name from `e2e/test_openobserve_e2e.py`.
3. Rerun the examples in `examples/openobserve/` if nothing appears immediately, then refresh the UI.
