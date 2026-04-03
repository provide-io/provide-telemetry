# Telemetry Conventions

## Event Naming

Event names follow the DA(R)S pattern: **Domain**, **Action**, **(Resource)**, **Status**.

- **3-segment DAS**: `domain.action.status` — use when no resource qualifier is needed
- **4-segment DARS**: `domain.action.resource.status` — use when a resource narrows the action

Rules:

- lowercase only
- 3 or 4 dot-separated segments
- underscores allowed inside segments
- last segment is always the status

Examples:

- `auth.login.success` (DAS: domain=auth, action=login, status=success)
- `payment.subscription.renewal.success` (DARS: domain=payment, action=subscription, resource=renewal, status=success)
- `matchmaking.queue.joined` (DAS)
- `inventory.item.removed` (DAS)

Use `provide.telemetry.event(*segments)` when event names are composed dynamically.

### `event()` Cookbook

Recommended:

- Fixed event:
  - `log.info("auth.login.success", user_id=user_id)`
- Dynamic status:
  - `log.info(event("auth", "login", "failed"), reason="bad_password")`
- Dynamic action from known enum/constant set:
  - `log.info(event("ws", action, "received"), size=len(payload))`
- Middleware/instrumentation composition:
  - `log.info(event("http", "request", "started"), method=method, path=path)`
- DARS with resource (4 segments):
  - `log.info(event("payment", "subscription", "renewal", "success"))`

Avoid:

- 5+ segment names:
  - `auth.login.password.reset.attempt.failed`
- Free-form strings as segments:
  - `event("auth", user_input, "success")`
- Encoding details in event name instead of attributes:
  - prefer `event("auth", "login", "failed")` with `reason="token_expired"`

## Required Context Keys

Recommended base keys across services:

- `request_id`
- `session_id`
- `actor_id`
- `service`
- `env`

Use `PROVIDE_TELEMETRY_REQUIRED_KEYS` to enforce package-specific requirements.

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

- `SPDX-FileCopyrightText` with `Copyright (C) 2026 provide.io llc`
- `SPDX-License-Identifier` with `Apache-2.0`
- `SPDX-Comment` with `Part of Provide Telemetry.`
- `#`
- blank line
