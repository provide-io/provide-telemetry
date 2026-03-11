# Telemetry Conventions

## Event Naming

Use: `domain.action.status` (exactly 3 segments)

Rules:

- lowercase only
- exactly 3 dot-separated segments
- underscores allowed inside segments

Examples:

- `auth.login.success`
- `matchmaking.queue.joined`
- `inventory.item.removed`

Use `undef.telemetry.event_name(domain, action, status)` when event names are composed dynamically.

### `event_name` Cookbook

Recommended:

- Fixed event:
  - `log.info("auth.login.success", user_id=user_id)`
- Dynamic status:
  - `log.info(event_name("auth", "login", "failed"), reason="bad_password")`
- Dynamic action from known enum/constant set:
  - `log.info(event_name("ws", action, "received"), size=len(payload))`
- Middleware/instrumentation composition:
  - `log.info(event_name("http", "request", "started"), method=method, path=path)`

Avoid:

- 4+ segment names:
  - `auth.login.password.failed`
- Free-form strings as segments:
  - `event_name("auth", user_input, "success")`
- Encoding details in event name instead of attributes:
  - prefer `event_name("auth", "login", "failed")` with `reason="token_expired"`

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

## Python File Header Convention

Use the canonical SPDX block for all Python files, with optional shebang first:

- `SPDX-FileCopyrightText` with `Copyright (C) 2026 MindTenet LLC`
- `SPDX-License-Identifier` with `Apache-2.0`
- `SPDX-Comment` with `Part of Undef Telemetry.`
- `#`
- blank line
