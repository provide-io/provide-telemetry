# Changelog

## [0.4.2] — 2026-03-29

### Tests

* **ts:** assert exact ANSI codes, SKIP_KEYS completeness, and msg fallback ([8c135eb](https://github.com/undef-games/undef-telemetry/commit/8c135eb))
* **ts:** anchor case-fold test with exact hash to kill toUpperCase mutation ([19affde](https://github.com/undef-games/undef-telemetry/commit/19affde))
* **ts:** assert exact fingerprint values to kill mutation survivors ([9ef4d82](https://github.com/undef-games/undef-telemetry/commit/9ef4d82))
* **ts:** add Stryker disable pragma for otel covered-0 survivors ([d979aba](https://github.com/undef-games/undef-telemetry/commit/d979aba))

---

## [0.4.1] — 2026-03-28

### Features

* **typescript:** add error fingerprinting and session correlation with 100% coverage ([6769ed7](https://github.com/undef-games/undef-telemetry/commit/6769ed7))
* **typescript:** add pretty ANSI log renderer with color support and TTY detection ([add0cc2](https://github.com/undef-games/undef-telemetry/commit/add0cc2))
* **typescript:** add conditional exports for browser/edge OTel no-op stub ([c0f0879](https://github.com/undef-games/undef-telemetry/commit/c0f0879))

### Bug Fixes

* **typescript:** remove workerd/edge-light from otel no-op (Cloudflare/Vercel support OTel natively) ([880bfee](https://github.com/undef-games/undef-telemetry/commit/880bfee))

### Tests

* **typescript:** add otel-noop coverage test ([2f93d6b](https://github.com/undef-games/undef-telemetry/commit/2f93d6b))
* **typescript:** kill surviving mutants in backpressure, cardinality, resilience ([eb8ee9b](https://github.com/undef-games/undef-telemetry/commit/eb8ee9b))

---

## [0.4.0](https://github.com/undef-games/undef-telemetry/compare/telemetry-v0.3.0...telemetry-v0.4.0) (2026-03-28)


### Features

* add memray memory profiling infrastructure and optimize hot paths ([648177c](https://github.com/undef-games/undef-telemetry/commit/648177c7394591841cefabdf132304c4a2fdea78))
* **browser-e2e:** add Vite-served browser tracer page and proxy config ([e0bbdc3](https://github.com/undef-games/undef-telemetry/commit/e0bbdc3a5bb6deb3aa75ede51a3e784884f44937))
* enterprise hardening — governance, releases, supply chain, ops ([d42ce5a](https://github.com/undef-games/undef-telemetry/commit/d42ce5a11874e3e25aec184ba43995f7c0feb7a7))
* polyglot spec infrastructure for multi-language support ([a5711af](https://github.com/undef-games/undef-telemetry/commit/a5711af396c9da2517e31815587ce70612b828bd))
* **typescript:** add TypeScript package with 100% mutation score ([d70527f](https://github.com/undef-games/undef-telemetry/commit/d70527f8136504a0533ddd53271c58af3e443235))
* **typescript:** implement shutdownTelemetry with full OTel provider drain ([0a740f7](https://github.com/undef-games/undef-telemetry/commit/0a740f723e1dcc2bab5321eba3f96e38c3c4ea39))
* **version:** transition to shared major.minor versioning with per-language patch ([48c8728](https://github.com/undef-games/undef-telemetry/commit/48c87284e845ba3cf1df1d5e2d09ce4c0723d28d))


### Bug Fixes

* address PR review feedback — lock file sync, parser robustness, exception narrowing, license link ([fb6428a](https://github.com/undef-games/undef-telemetry/commit/fb6428a4a2d06a910c977f8eb2a0b2b0904cfee4))
* lint errors, 100% coverage, exclude stryker sandbox from v8 coverage ([02cfe3b](https://github.com/undef-games/undef-telemetry/commit/02cfe3b90e8bc43504e79eb4058811efa2e567f1))
* remove stale eslint-disable directives, bump perf threshold for CI, update happy-dom ([dc1bbdf](https://github.com/undef-games/undef-telemetry/commit/dc1bbdfa9a0f32c88cb1bd1630568ba0223a05e2))
* three bugs in telemetry logger — static isBrowser, stale cfg, Node.js write hook ([59e076d](https://github.com/undef-games/undef-telemetry/commit/59e076d0cd4ee159873c4c98484c5b8733583bd8))


### Tests

* **e2e:** browser distributed trace linkage via Playwright + Vite proxy ([0075d5a](https://github.com/undef-games/undef-telemetry/commit/0075d5af8ee75a62b6cd464bf9e749f1e4a2d9c9))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([61611c8](https://github.com/undef-games/undef-telemetry/commit/61611c859d8c09df8ff2835d6ca85fe26facb5af))
* **e2e:** cross-language distributed trace linkage via W3C traceparent ([1bada42](https://github.com/undef-games/undef-telemetry/commit/1bada42f39e7b7bd422aa640b8341e3bf5329ffd))
* **ts:** add full coverage and mutation tests for otel.ts ([e5187eb](https://github.com/undef-games/undef-telemetry/commit/e5187ebb273453097c746e5125a08bd17429d408))
* **ts:** kill window typeof-check mutation survivors in node env ([125f561](https://github.com/undef-games/undef-telemetry/commit/125f561fab0099fdf33e69959fa04c3fde0a69ee))
* **typescript:** kill config.ts logFormat string mutation with empty-string test ([4a765cf](https://github.com/undef-games/undef-telemetry/commit/4a765cf83c798fe10835ec21826e657c95734d6f))
* **typescript:** kill surviving mutants in backpressure, cardinality, resilience ([eb8ee9b](https://github.com/undef-games/undef-telemetry/commit/eb8ee9ba6ecb7557c5276f5ca677e07214c7c536))
