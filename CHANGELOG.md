# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Both packages (`undef-telemetry` / `@undef-games/telemetry`) share a version number.

---

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
- **npm publish pipeline** — `release.yml` builds and publishes `@undef-games/telemetry` to npm on
  GitHub release via `NPM_TOKEN`.
- **TypeScript package metadata** — `author`, `homepage`, `repository`, `keywords`,
  `sideEffects: false`, `engines: { "node": ">=18" }`, `prepublishOnly` guard.

### Changed
- **TypeScript version aligned to Python** — `@undef-games/telemetry` is now `0.3.18` (was `0.1.0`).
- **Stryker mutation threshold raised to 100** — `break: 100` enforced in CI (was 70).
- **`src/otel.ts` included in strict type-checking** — removed from `tsconfig.json` exclude list;
  all 20 TypeScript source files are now fully type-checked under `strict: true`.
- **Python development status** — classifier updated from `3 - Alpha` to `4 - Beta`.
- **TypeScript upgraded to v6**, all npm dependencies updated to latest.

### Fixed
- Removed stale `undef-telemetry → repo-root` symlink that caused pytest to loop infinitely
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
