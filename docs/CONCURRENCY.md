# Concurrency Model

This document is the cross-language reference for how `provide-telemetry`
keeps state consistent under concurrent access. For the higher-level runtime
architecture, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for the
initialisation sequence, see [`INTERNALS.md`](INTERNALS.md).

## Shared invariants

The four runtimes (Python, TypeScript, Go, Rust) agree on three invariants:

1. **Context is async-local everywhere; never stored in a process-global
   after setup.** Trace IDs, session IDs, request IDs, baggage, and
   propagation state live in async-local containers (`contextvars`,
   `AsyncLocalStorage`, Go `context.Context` values, Rust guards over
   task-local / thread-local snapshots). Process-global storage is used
   only for policy (sampling, backpressure, consent, cardinality) and
   setup/lifecycle flags.
2. **Setup is idempotent and serialised.** Each runtime guards its
   `setup_telemetry` / `setupTelemetry` / `SetupTelemetry` coordinator with
   a mutex so concurrent calls collapse to a single installation.
3. **Provider-changing reconfiguration cannot be hot-swapped once the
   upstream OpenTelemetry provider is installed.** All four runtimes
   communicate this by requiring a process restart for provider swaps;
   policy (sampling rate, queue depth, exporter timeouts) is always
   hot-reloadable.

## Python

### Locks

- `src/provide/telemetry/setup.py` — module-level `threading.Lock` guards
  both `setup_telemetry()` and `shutdown_telemetry()`. The `_setup_done`
  sentinel and the lock together guarantee the first caller performs work
  and every later caller is a no-op until `shutdown_telemetry()` clears
  the flag.
- `src/provide/telemetry/logger/core.py` — `_lock` + `_configured` sentinel
  serialise logger configuration. `configure_logging(..., force=True)` is
  the only way to re-run the pipeline under the lock.
- `src/provide/telemetry/tracing/provider.py` — `_provider_lock` guards
  provider install and baseline capture. `_setup_generation` is a monotonic
  counter used to detect a race between "build provider outside the lock"
  and "shutdown happened mid-build"; the loser discards its provider.
- `src/provide/telemetry/metrics/provider.py` — mirror of the tracing
  provider lock, using `_meter_lock` and its own `_setup_generation`.
- `src/provide/telemetry/runtime.py` — `_reconfigure_lock` serialises
  reconfigure calls. Readers of the active config hold the same lock
  (post-P0 fix): `_active_config` is never read without taking the lock,
  which prevents torn reads under free-threaded CPython (3.13+
  `--disable-gil`).
- `src/provide/telemetry/sampling.py`, `backpressure.py`, `pii.py`,
  `cardinality.py`, `consent.py`, `resilience.py`, `health.py`,
  `receipts.py` — each subsystem owns a private `threading.Lock` guarding
  its policy dicts and counters. Holding two subsystem locks at once is
  forbidden; when a caller needs data from multiple subsystems, it takes
  one lock at a time and copies out primitive values before calling into
  the next.

### Context

Per-request state lives in `contextvars.ContextVar` instances:

- `src/provide/telemetry/logger/context.py` — `request_id`, `session_id`,
  and the user-injected logger context dict.
- `src/provide/telemetry/tracing/context.py` — `trace_id`, `span_id`.
- `src/provide/telemetry/propagation.py` — a stack of propagation snapshots
  so that nested `bind_propagation_context` calls restore the exact outer
  state on unwind.

`contextvars` are task-local under `asyncio`, so concurrent coroutines
observe isolated views of the same logical field. The ASGI middleware
(`src/provide/telemetry/asgi/middleware.py`) uses `save_context()` /
`reset_context()` to snapshot and restore the logger context across every
request without requiring the application itself to clean up.

### Hot-reload semantics

`update_runtime_config()` (and `reload_runtime_from_env()`) snapshot the
incoming config, acquire `_reconfigure_lock`, swap `_active_config`, and
push policy values to the subsystem locks. Logging pipeline changes force
a re-run of `configure_logging`, which is itself lock-protected. The
tracer / meter providers are *not* recreated in-place — only their policy
envelope is updated — because OpenTelemetry's process-global providers
cannot be safely swapped after spans are in flight.

## TypeScript

- `typescript/src/setup.ts` — module-singleton pattern with an init sentinel.
  A promise-valued `_initialising` handle lets concurrent `setupTelemetry()`
  calls await the same installation.
- Request-scoped state uses Node's `AsyncLocalStorage`. The runtime
  convention is the same as Python's `contextvars`: each request's bindings
  are isolated from every concurrent request and restored automatically
  when the async frame unwinds.
- **Propagation init is async.** Callers who rely on `AsyncLocalStorage`
  being populated inside ESM environments must `await awaitPropagationInit()`
  before making the first call that reads context (post-P1 fix). Failing
  to await would observe a transient empty store while the ESM dynamic
  import resolves the OTel propagation backend.
- Policy modules (sampling, backpressure, cardinality, consent) are plain
  module singletons protected by the single-threaded event loop; there is
  no explicit mutex.

## Go

- Each subsystem package owns a package-level `sync.RWMutex`:
  `cardinality`, `consent`, `backpressure`, `sampling`, `resilience`,
  `backend`, and the top-level `setup` coordinator. `RLock()` is used for
  policy reads on the hot path; `Lock()` is reserved for policy updates,
  reset, and setup/shutdown transitions.
- **Lock order: setup → subsystems.** The setup coordinator acquires its
  own lock first, then delegates to subsystem calls that each take their
  own lock internally and release it before returning. State is never
  shared across locks held simultaneously — every cross-subsystem value
  is passed as a primitive copy.
- Per-request context flows through Go's standard `context.Context`. There
  is no ambient goroutine-local storage; every function that needs trace
  or session state receives a `context.Context` parameter. The ASGI /
  HTTP middleware attaches the context on inbound requests and removes it
  on response.
- Cardinality and consent subsystems use a two-phase prune pattern
  (snapshot candidates under the lock, release, delete survivors under
  the lock again) so they never hold the mutex across expensive
  allocations.

## Rust

- Lazy-initialised globals use `OnceLock<Mutex<T>>`. The `_lock::lock()`
  helper (`rust/src/_lock.rs`) centralises the "poisoned-mutex" recovery
  pattern: if a prior panic poisoned the lock, the helper extracts the
  inner value via `PoisonError::into_inner()` so the telemetry layer
  continues to function in degraded mode rather than aborting the host
  process (post-P0 fix).
- Context propagation is guard-based: `bind_context()`, `bind_session_context()`,
  `set_trace_context()`, and `bind_propagation_context()` all return RAII
  guards that restore the previous snapshot on `Drop`. This gives the same
  nesting and task-isolation semantics as Python's contextvars without
  requiring a process-global mutable context.
- Policy state (sampling, cardinality, backpressure, resilience,
  classification) lives behind `OnceLock<Mutex<T>>`; the mutex is held only
  long enough to clone out the relevant frozen struct or increment a
  counter.
- When the `otel` cargo feature is enabled, the Rust crate still defers to
  OpenTelemetry's process-global provider, so provider-changing
  reconfiguration requires a process restart — just like the other
  runtimes.

## Cross-cutting notes

- No runtime uses unbounded queues. Backpressure caps are configurable but
  enforced under the owning subsystem's lock, so the "full queue" decision
  is always consistent with the ticket count.
- Shutdown is ordered: tracing → metrics → logging → runtime reset →
  executor shutdown. Each step is independently lock-protected.
- Tests that reset module-level singletons use `importlib.reload` (Python),
  Jest module-reset hooks (TypeScript), fresh `TestMain` helpers (Go),
  and `#[cfg(test)]` resetters (Rust). Never touch the locks directly; use
  the documented `_reset_*_for_tests` helpers.

For the initialisation ordering and the processor-chain order, see
[`INTERNALS.md`](INTERNALS.md) — this document intentionally does not
duplicate that content.
