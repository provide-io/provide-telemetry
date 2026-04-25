# Architectural Positioning

As of April 14, 2026, this is the practical comparison for `provide-telemetry` versus direct OpenTelemetry and vendor-owned SDK stacks, followed by the blunt recommendation on what to do with this repo.

## Decision Table

| Option | What It Is | Choose When | Avoid When | Migration Cost | Lock-in |
|---|---|---|---|---|---|
| `provide-telemetry` | A house telemetry facade and policy layer over logs, traces, metrics, plus schema, PII, backpressure, and runtime controls across Python, TypeScript, Go, and Rust. Evidence: shared facade in `src/provide/telemetry/__init__.py`, lifecycle in `src/provide/telemetry/setup.py`, parity contract in `spec/telemetry-api.yaml`. | You want one internal standard across languages, you want policy built in, and you are willing to own the abstraction. | You want to stay close to ecosystem standards, want vendor support out of the box, or do not want to maintain semantic parity yourself. | Medium to high if you are already on raw OTel or a vendor SDK, because you have to adopt this API and its conventions. | Medium vendor lock-in, high internal-platform lock-in. You are not tied to a vendor, but you are tied to your own facade. |
| OpenTelemetry directly | Vendor-neutral observability standard for traces, metrics, and logs, with Collector and broad vendor support. | You want the industry standard, maximum portability, and direct access to the real primitives. | You want a single high-level API across languages with org-specific defaults already encoded. | Medium because OTel is flexible but you must assemble conventions, wrappers, and policy yourself. | Low. This is the least locked-in path. |
| Datadog | Full observability platform with agent, APM, logs, metrics, service map, and single-step instrumentation. | You want fast time-to-value, auto-instrumentation, a managed platform, and deep UI and product integration. | You want a vendor-neutral contract or do not want an agent and platform dependency in the middle of your telemetry model. | Low to medium for adoption if you accept the platform; high to leave later if you lean into Datadog-native features. | High. Strong product and workflow lock-in. |
| Sentry | Error-monitoring-first platform that also does tracing and spans. | Your center of gravity is exceptions, app debugging, and trace-linked incident investigation rather than building a telemetry standard. | You want a broad backend-service observability contract with first-class logs and metrics policy across multiple languages under one custom API. | Low to medium if you mainly need errors plus tracing; higher if you expect it to replace a full internal telemetry platform. | Medium to high. Less infrastructure-heavy than Datadog, but still a vendor model. |

## How I Would Decide

- Choose `provide-telemetry` if the real problem is organizational consistency.
- Choose OpenTelemetry if the real problem is portability and standards alignment.
- Choose Datadog if the real problem is operational speed and product depth.
- Choose Sentry if the real problem is debugging failures and app performance with a strong error workflow.

## Why These Ratings

- `provide-telemetry` scores high on consistency because the repo is explicitly built as a shared facade plus parity spec, but that same choice creates internal lock-in and maintenance burden.
- OpenTelemetry scores best on portability because it is the standard itself, but it gives you primitives, not your policy layer.
- Datadog scores best on "works quickly" because its official path includes agent-driven and single-step instrumentation, plus built-in correlation and service map features.
- Sentry scores best when traces exist to explain errors and performance issues, not when you want a neutral telemetry control plane.

## Short Version

- If you want to own the contract: `provide-telemetry`.
- If you want to own as little as possible while staying standard: OpenTelemetry.
- If you want to buy the platform: Datadog.
- If you want errors first, tracing second: Sentry.

## Recommendation

My blunt recommendation: shrink it, not keep it as-is and not replace it with a vendor SDK as the core abstraction.

### What To Keep

- A thin cross-language facade
- The event and schema contract
- PII, cardinality, and sampling policy hooks
- ASGI and context propagation helpers
- OTel-first provider wiring

### What To De-emphasize Or Remove

- Ambitious runtime reconfiguration
- "Optional" or "strippable" governance claims until they are actually true in live signal paths
- Duplicated custom behavior that sits far above raw OTel in four languages

### Why

The repo's strongest asset is clear:

- It gives a polyglot org one telemetry contract, proven by the shared spec in `spec/telemetry-api.yaml`.

Its weakest asset is also clear:

- It is trying to be a mini observability platform inside every app runtime.

That second part is where cost and fragility start to dominate:

- Four implementations means semantic drift risk.
- Global mutable runtime state makes correctness harder.
- Advanced behaviors like hot reload and optional governance boundaries are where the architecture is already showing cracks.

So the repo has a good core idea, but it is carrying too much platform logic for what should probably remain an SDK.

### When I Would Keep It

Keep the broader design only if all of these are true:

- You have a real multi-language estate: at least three active languages in production.
- You have multiple teams who need one contract more than they need raw flexibility.
- You have compliance or privacy requirements that justify built-in policy.
- You have at least one dedicated owner who can maintain parity across Python, TypeScript, Go, and Rust.

If that is the environment, this repo is defensible.

### When I Would Shrink It

Shrink it if this is true:

- The main value is consistency, not custom runtime behavior.
- The team can rely on OpenTelemetry for the underlying provider model.
- You want to reduce maintenance burden without losing the house standard.

That is the path I would choose here.

### When I Would Replace It With Direct OpenTelemetry

Replace it with direct OTel plus a much smaller helper package if:

- You are mostly one language, maybe two.
- You do not need a custom contract across all four languages.
- You do not want to own semantic parity forever.
- Standards alignment matters more than framework-level opinion.

For most teams, this is the right answer.

### When I Would Replace It With Datadog Or Sentry

Only do that if the org decision is:

- "We are buying observability as a platform capability."
- "We do not want to own a telemetry abstraction layer."

Then this repo should not remain the primary API. Either retire it or reduce it to a thin integration adapter.

### Net

- Small team or single-language org: replace with direct OpenTelemetry.
- Mid-size polyglot org: shrink this repo to the contract and policy layer.
- Large org with real platform ownership and compliance pressure: keep it, but tighten its scope and harden the weak boundaries.

## Sources

- OpenTelemetry docs: https://opentelemetry.io/docs/
- Datadog tracing getting started: https://docs.datadoghq.com/getting_started/tracing/
- Datadog platform overview: https://docs.datadoghq.com/getting_started/application/
- Sentry OpenTelemetry support: https://docs.sentry.io/platforms/node/performance/instrumentation/opentelemetry
- Sentry tracing setup: https://docs.sentry.io/platforms/javascript/guides/express/tracing
