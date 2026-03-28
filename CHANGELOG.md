# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Both packages (`undef-telemetry` / `@undef/telemetry`) share a version number.

---

## [0.4.0](https://github.com/undef-games/undef-telemetry/compare/undef-telemetry-v0.3.0...undef-telemetry-v0.4.0) (2026-03-28)


### Features

* add memray memory profiling infrastructure and optimize hot paths ([648177c](https://github.com/undef-games/undef-telemetry/commit/648177c7394591841cefabdf132304c4a2fdea78))
* **browser-e2e:** add Vite-served browser tracer page and proxy config ([e0bbdc3](https://github.com/undef-games/undef-telemetry/commit/e0bbdc3a5bb6deb3aa75ede51a3e784884f44937))
* enterprise hardening — governance, releases, supply chain, ops ([d42ce5a](https://github.com/undef-games/undef-telemetry/commit/d42ce5a11874e3e25aec184ba43995f7c0feb7a7))
* per-module log level overrides (UNDEF_LOG_MODULE_LEVELS) ([c4a3b12](https://github.com/undef-games/undef-telemetry/commit/c4a3b12a752ada3fade0021e43dc12683f6e056c))
* per-module log level overrides (UNDEF_LOG_MODULE_LEVELS) ([c947f41](https://github.com/undef-games/undef-telemetry/commit/c947f4178939efc6f44c3547e512a7565b76bc77))
* polyglot spec infrastructure for multi-language support ([a5711af](https://github.com/undef-games/undef-telemetry/commit/a5711af396c9da2517e31815587ce70612b828bd))
* **spec:** add canonical API surface definition for polyglot conformance ([8a70c00](https://github.com/undef-games/undef-telemetry/commit/8a70c008b97ddaa78280b44e0396953c93e40af1))
* **spec:** add conformance validation script for Python and TypeScript ([b74c58f](https://github.com/undef-games/undef-telemetry/commit/b74c58f54e816a78c94f1080359125cb93dd47ce))
* **typescript:** add TypeScript package with 100% mutation score ([d70527f](https://github.com/undef-games/undef-telemetry/commit/d70527f8136504a0533ddd53271c58af3e443235))
* **typescript:** implement shutdownTelemetry with full OTel provider drain ([0a740f7](https://github.com/undef-games/undef-telemetry/commit/0a740f723e1dcc2bab5321eba3f96e38c3c4ea39))
* **version:** transition to shared major.minor versioning with per-language patch ([48c8728](https://github.com/undef-games/undef-telemetry/commit/48c87284e845ba3cf1df1d5e2d09ce4c0723d28d))


### Bug Fixes

* add e2e/ to ruff per-file-ignores after test promotion ([d1c20a3](https://github.com/undef-games/undef-telemetry/commit/d1c20a3329518b761206e07a41108fb768aa9788))
* address PR review feedback — lock file sync, parser robustness, exception narrowing, license link ([fb6428a](https://github.com/undef-games/undef-telemetry/commit/fb6428a4a2d06a910c977f8eb2a0b2b0904cfee4))
* allow logging config changes without provider restart ([fb3620e](https://github.com/undef-games/undef-telemetry/commit/fb3620ea90e589eaac12f6ad0e34ee3388685560))
* anchor memray test paths to project root via VERSION file ([61dc9a4](https://github.com/undef-games/undef-telemetry/commit/61dc9a412751d21e055c7ed73169947c54c2486e))
* **e2e:** collect console messages properly, retry Vite page load instead of sleep ([dd8fa58](https://github.com/undef-games/undef-telemetry/commit/dd8fa58854f0fa88901e86a84f98b303705390ce))
* exclude memray tests from mutmut stats collection ([7ee1885](https://github.com/undef-games/undef-telemetry/commit/7ee1885ebf2b20ce19449895d59c66b5350c4609))
* exclude node_modules from SPDX header check ([705af03](https://github.com/undef-games/undef-telemetry/commit/705af03a2ea4ad5ac91a723485b067452fc67de9))
* format e2e test, add REUSE annotations for new config files ([c7d67c9](https://github.com/undef-games/undef-telemetry/commit/c7d67c9144efe981ca119a4feaf22c9390af3389))
* lint errors, 100% coverage, exclude stryker sandbox from v8 coverage ([02cfe3b](https://github.com/undef-games/undef-telemetry/commit/02cfe3b90e8bc43504e79eb4058811efa2e567f1))
* mark pytest hook parameters as used for vulture ([b02c01e](https://github.com/undef-games/undef-telemetry/commit/b02c01e6529d76971103e28464952674ad4a4201))
* mark setattr API names as no-mutate, bypass resilience in handler tests for CI stability ([0326c48](https://github.com/undef-games/undef-telemetry/commit/0326c486c447ef12ebcc45636310d5c07ce7c001))
* remove invalid --CI flag from mutmut run ([3d0aa9e](https://github.com/undef-games/undef-telemetry/commit/3d0aa9e5acb0c2bca9f602bcc62ed9ae51df4be1))
* remove stale eslint-disable directives, bump perf threshold for CI, update happy-dom ([dc1bbdf](https://github.com/undef-games/undef-telemetry/commit/dc1bbdfa9a0f32c88cb1bd1630568ba0223a05e2))
* rename unused loop variable to satisfy ruff B007 ([cd07499](https://github.com/undef-games/undef-telemetry/commit/cd07499e2e1ee3c1e40d88f869657697a1917828))
* reset sampling policy between tests; correct config.py docs ([5f92e32](https://github.com/undef-games/undef-telemetry/commit/5f92e32b954d181843b6bfba978bd8186daf7e04))
* resolve pre-existing ruff and mypy errors in test files ([f8daaff](https://github.com/undef-games/undef-telemetry/commit/f8daaff7a1e2d54d4ec0d27b461e3db85d3572ec))
* resolve ty type-checker errors in processors and test overrides ([942bb15](https://github.com/undef-games/undef-telemetry/commit/942bb1553bfb004dd1d1f97a02858ec8a9e666cf))
* resolve ty type-checker errors with setattr/getattr for dynamic attributes ([6b6888a](https://github.com/undef-games/undef-telemetry/commit/6b6888a79ad5d39dfc498da16a0a7f754bad4677))
* restore 25μs perf threshold for CI runners, remove flaky marker ([bfd9e62](https://github.com/undef-games/undef-telemetry/commit/bfd9e623106b4eb399db3d47ebf594e89b2b6526))
* **spec:** address review issues in conformance validation ([6ce01f7](https://github.com/undef-games/undef-telemetry/commit/6ce01f7452050a23a0ccc3ab90d91c9fc4abe857))
* **test:** accept 2-segment version after major.minor transition ([c41a517](https://github.com/undef-games/undef-telemetry/commit/c41a5179092b6cd7ab65b1bccc89387ada4ee868))
* three bugs in telemetry logger — static isBrowser, stale cfg, Node.js write hook ([59e076d](https://github.com/undef-games/undef-telemetry/commit/59e076d0cd4ee159873c4c98484c5b8733583bd8))


### Tests

* add circuit breaker lifecycle test ([2e33f78](https://github.com/undef-games/undef-telemetry/commit/2e33f7804ee5d385092fcd8195c2cc9d24524c8e))
* add cross-signal isolation test ([c6082be](https://github.com/undef-games/undef-telemetry/commit/c6082be9756c8f92da6a199b1671ca84b79bee95))
* add ghost thread accumulation test ([db62d0c](https://github.com/undef-games/undef-telemetry/commit/db62d0cf587f37ef591d988163606ffaf4af6e44))
* add pytest-rerunfailures for flaky performance tests ([debace7](https://github.com/undef-games/undef-telemetry/commit/debace798eb5420123b9583853d13cc31bd8aec3))
* **e2e:** browser distributed trace linkage via Playwright + Vite proxy ([0075d5a](https://github.com/undef-games/undef-telemetry/commit/0075d5af8ee75a62b6cd464bf9e749f1e4a2d9c9))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([61611c8](https://github.com/undef-games/undef-telemetry/commit/61611c859d8c09df8ff2835d6ca85fe26facb5af))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([1bada42](https://github.com/undef-games/undef-telemetry/commit/1bada42f39e7b7bd422aa640b8341e3bf5329ffd))
* fix scaffold lint issues and defensive teardown ([fea1b3d](https://github.com/undef-games/undef-telemetry/commit/fea1b3dcf0b20237da1b048ec0b8dc2ab96aa4af))
* harden assertions, add cross-signal isolation, fix OTel markers and docs ([47bda6d](https://github.com/undef-games/undef-telemetry/commit/47bda6d044ac0f7c7bec68e47a46e6c8ace7d63a))
* kill 34 no_tests mutation survivors in otel component loaders ([3186330](https://github.com/undef-games/undef-telemetry/commit/318633086364184cc484588a8b35287d8676d7d8))
* kill 7 mutation survivors in _otel and provider guard conditions ([1c4f863](https://github.com/undef-games/undef-telemetry/commit/1c4f863a5b3a471477ce39a01b47cfa05c5a2823))
* kill final 2 no_tests mutation survivors in provider component guards ([e15cb97](https://github.com/undef-games/undef-telemetry/commit/e15cb97dea8a0cf15b873a0caa3a919ca7cc9545))
* scaffold executor saturation test file with fixtures and helpers ([ce77b28](https://github.com/undef-games/undef-telemetry/commit/ce77b2816a5093e70e4847abe91a2014c89aade4))
* **ts:** add full coverage and mutation tests for otel.ts ([e5187eb](https://github.com/undef-games/undef-telemetry/commit/e5187ebb273453097c746e5125a08bd17429d408))
* **ts:** kill window typeof-check mutation survivors in node env ([125f561](https://github.com/undef-games/undef-telemetry/commit/125f561fab0099fdf33e69959fa04c3fde0a69ee))
* **typescript:** kill config.ts logFormat string mutation with empty-string test ([4a765cf](https://github.com/undef-games/undef-telemetry/commit/4a765cf83c798fe10835ec21826e657c95734d6f))
* **typescript:** kill surviving mutants in backpressure, cardinality, resilience ([eb8ee9b](https://github.com/undef-games/undef-telemetry/commit/eb8ee9ba6ecb7557c5276f5ca677e07214c7c536))
* use &lt;= for thread drain assertion (safer under parallel runners) ([c11afff](https://github.com/undef-games/undef-telemetry/commit/c11afff62ecfae4c3411c63a2defd8d852a9e542))


### CI/CD

* add changed-files mutation gate for Python PRs ([a2a680e](https://github.com/undef-games/undef-telemetry/commit/a2a680eb5620deef7ff332893228d699ddfa2c43))
* add changed-files mutation gate for TypeScript PRs ([6f42454](https://github.com/undef-games/undef-telemetry/commit/6f424545eb2bef79c4a000053297d1af4f454ac7))
* add CODEOWNERS for code review assignment ([f3bdae2](https://github.com/undef-games/undef-telemetry/commit/f3bdae2eac6104090aff8a8d92df364b3e321fd4))
* add CodeQL SAST scanning for Python and TypeScript ([2ca88df](https://github.com/undef-games/undef-telemetry/commit/2ca88df015b145248b73e0b28913b257a1461dc6))
* add commitlint for conventional commit enforcement ([4b218d4](https://github.com/undef-games/undef-telemetry/commit/4b218d4912d85219999435c04cb4dfe17a93b147))
* add CycloneDX SBOM generation to release pipeline ([81b0f72](https://github.com/undef-games/undef-telemetry/commit/81b0f72908c3a8bedb81de228ccaa739efe7a9fb))
* add Dependabot for automated dependency updates ([fe93b0d](https://github.com/undef-games/undef-telemetry/commit/fe93b0dcc7581e5ae0254166406a5b2b4746e72c))
* add numbered emoji prefixes to workflow names for sorted display ([f2704a6](https://github.com/undef-games/undef-telemetry/commit/f2704a660073ec11e152cdf2a4f15a1363da57ff))
* add playwright chromium install to openobserve-e2e job ([7bde5e4](https://github.com/undef-games/undef-telemetry/commit/7bde5e4514ef031b342d912e7bccfcdac85b5ed5))
* add pull request template ([7cc5e24](https://github.com/undef-games/undef-telemetry/commit/7cc5e24d60fa79ac9ce019538497cbbbd451619c))
* add Sigstore artifact signing to release pipeline ([219bbaf](https://github.com/undef-games/undef-telemetry/commit/219bbaf1155c3b3d46381d0a2b5f7b934f81729e))
* add spec conformance and version sync workflow ([a11de50](https://github.com/undef-games/undef-telemetry/commit/a11de50f1e92faf132753c914c3e6ac298eaf47d))
* configure release-please for automated releases ([ab3b8af](https://github.com/undef-games/undef-telemetry/commit/ab3b8af8cda50c06d265635437dadc1f00e907e4))
* log surviving mutant names on mutation gate failure ([810c740](https://github.com/undef-games/undef-telemetry/commit/810c7406af3a01874731a92733bd08569b8bddbe))
* pin all GitHub Actions to SHA for supply chain security ([8bd28e8](https://github.com/undef-games/undef-telemetry/commit/8bd28e880c80759d04b97bb7572abc43d39bd872))
* run mutation-gate, otlp-integration, performance-smoke, and TS mutation on every PR ([bf3219b](https://github.com/undef-games/undef-telemetry/commit/bf3219b2f6755cbeef7eec2ccd2bb9c0310aa020))
* split monolithic CI into language-specific workflows with path filters ([b184204](https://github.com/undef-games/undef-telemetry/commit/b1842042d0b46d600a5ef71f8c05584e7e7c4cca))
* update all GitHub Actions to latest major versions ([881b467](https://github.com/undef-games/undef-telemetry/commit/881b467f46b2ef3f1b02f3a50d0da1a419183488))


### Documentation

* add branch protection configuration guide ([5c17102](https://github.com/undef-games/undef-telemetry/commit/5c1710241975fc210e88d0e890d95310d45eee6f))
* add enterprise hardening design spec ([e5c24f2](https://github.com/undef-games/undef-telemetry/commit/e5c24f2353eda731f44da053e7355a5971e77aa7))
* add enterprise hardening implementation plan ([49d2920](https://github.com/undef-games/undef-telemetry/commit/49d2920a2ebee5269bb297d134e58da69cc00f6f))
* add executor saturation load test design spec ([a768008](https://github.com/undef-games/undef-telemetry/commit/a768008beb55e0f53ddd64f2686657c1192c7203))
* add executor saturation load test implementation plan ([d2e3113](https://github.com/undef-games/undef-telemetry/commit/d2e3113589aee1a5aa32f0bb02e6d4822ba1a3bf))
* add polyglot structure section to CLAUDE.md ([1b5d6fc](https://github.com/undef-games/undef-telemetry/commit/1b5d6fc14cb89db4620ef03524525a88b832e475))
* remove stale migration language, stub references, and history comments ([68b6317](https://github.com/undef-games/undef-telemetry/commit/68b631700096b72297887dc986c4e65c20c27f79))
* rewrite README for polyglot end-state with badges and TypeScript ([2f65d9f](https://github.com/undef-games/undef-telemetry/commit/2f65d9f86067635e35de4e0a3ea416985d92d498))


### Refactoring

* **e2e:** promote cross-language E2E tests to repo root ([3481b0c](https://github.com/undef-games/undef-telemetry/commit/3481b0c1a0986aaff54d1c3961b1336fbfae8fe1))

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
- **npm publish pipeline** — `release.yml` builds and publishes `@undef/telemetry` to npm on
  GitHub release via `NPM_TOKEN`.
- **TypeScript package metadata** — `author`, `homepage`, `repository`, `keywords`,
  `sideEffects: false`, `engines: { "node": ">=18" }`, `prepublishOnly` guard.

### Changed
- **TypeScript version aligned to Python** — `@undef/telemetry` is now `0.3.18` (was `0.1.0`).
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
