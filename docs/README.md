# Documentation Map

Start from your role.

## Using the library — `guide/`

| Doc | What it answers |
|-----|-----------------|
| [api.md](guide/api.md) | The shared semantic contract: every API, its behavior, in all five languages |
| [configuration.md](guide/configuration.md) | Every environment variable, generated from the spec |
| [conventions.md](guide/conventions.md) | DA(R)S event naming and telemetry conventions |
| [capability-matrix.md](guide/capability-matrix.md) | What is guaranteed vs feature-gated vs a real per-language difference |
| [positioning.md](guide/positioning.md) | Why this library exists relative to plain OpenTelemetry |

## Running services on it — `operations/`

| Doc | What it answers |
|-----|-----------------|
| [runbook.md](operations/runbook.md) | Local health checks, env var triage, common failure modes |
| [production-profiles.md](operations/production-profiles.md) | Recommended config profiles per deployment shape |
| [release.md](operations/release.md) | How each language publishes to its registry, with one-time registry setup recorded |

## Working on the repo — `internal/`

| Doc | What it answers |
|-----|-----------------|
| [architecture.md](internal/architecture.md) | Component design and data flow |
| [internals.md](internal/internals.md) | Implementation details behind the facades |
| [concurrency.md](internal/concurrency.md) | Locks, atomics, contextvars — the concurrency model per language |
| [parity.md](internal/parity.md) | The parity contract, its status, and the open gaps |
| [quality-gates.md](internal/quality-gates.md) | Performance budgets, mutation-exemption policy, fuzzing |
| [dx-rubric.md](internal/dx-rubric.md) | The developer-experience rubric releases are judged against |

## Historical records — `plans/`

Dated planning and evidence snapshots. Frozen: they describe the repo as it
was on their date, and are not updated when the tree moves on.
