# Telemetry Conventions

## Event Naming

Use: `domain.action.status`

Rules:

- lowercase only
- dot-separated segments
- underscores allowed inside segments

Examples:

- `auth.login.success`
- `matchmaking.queue.joined`
- `inventory.item.removed`

## Required Context Keys

Recommended base keys across services:

- `request_id`
- `session_id`
- `actor_id`
- `service`
- `env`

Use `UNDEF_TELEMETRY_REQUIRED_KEYS` to enforce package-specific requirements.

## Attribute Naming

- Use snake_case keys.
- Prefer low-cardinality values for metrics dimensions.
- Avoid raw PII in attributes and logs.

## Metric Naming

- Prefix by domain (`game.`, `auth.`, `ws.`, `api.`).
- Counters: cumulative events (`auth.login_attempts`).
- Histograms: latency/size distributions (`api.request_duration_ms`).
- Gauges/up-down counters: concurrency/load (`ws.active_connections`).

## Trace Span Naming

- Use verb-oriented names: `http.request`, `db.query`, `ws.receive`.
- Keep span names stable across releases.
- Put variable details in attributes, not names.

## Cross-Package Compatibility

When adding new telemetry fields:

1. Keep old field names for at least one release cycle.
2. Introduce aliases in dashboards/queries first.
3. Announce canonical key in changelog and docs.
