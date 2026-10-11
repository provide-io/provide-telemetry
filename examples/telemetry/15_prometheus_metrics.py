#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""📈 Prometheus metrics — serve a scrape endpoint from the SDK.

Demonstrates:
- Enabling the Prometheus pull reader with OTEL_METRICS_EXPORTER=prometheus
  (use otlp,prometheus to push over OTLP as well)
- metrics_handler(): the scrape endpoint as an ASGI app, mounted wherever the
  host likes (app.mount("/metrics", metrics_handler()) in Starlette/FastAPI)
- A counter and a histogram with units, plus an observable gauge whose
  callback runs on every scrape
- One in-process scrape, showing the Prometheus names the SDK renders:
  dots become underscores, counters gain _total, units become suffixes
- The SDK's own health as provide_telemetry_* series in the same scrape

Runs offline: the handler is called directly, so no port is bound. For a
standalone listener instead, set PROVIDE_METRICS_PROMETHEUS_LISTEN=true
(binds 127.0.0.1:9464 and serves /metrics by default).
Requires the otel extra: uv run --group dev --extra otel python ...
"""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from typing import Any

from provide.telemetry import (
    Observation,
    counter,
    histogram,
    metrics_handler,
    observable_gauge,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.config import TelemetryConfig


async def scrape(path: str = "/metrics") -> tuple[int, str, str]:
    """Drive the ASGI handler the way a server would for one GET request."""
    app = metrics_handler()
    scope: dict[str, Any] = {"type": "http", "method": "GET", "path": path, "headers": [(b"accept", b"text/plain")]}
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    status = int(sent[0]["status"])
    content_type = dict(sent[0]["headers"]).get(b"content-type", b"").decode()
    return status, content_type, bytes(sent[1]["body"]).decode()


def metric_names(body: str) -> list[str]:
    """The family names from the # TYPE lines of a text-format scrape."""
    return [line.split()[2] for line in body.splitlines() if line.startswith("# TYPE ")]


def main() -> None:
    print("📈 Prometheus Metrics Demo\n")

    # ── ⚙️  Enable the pull reader ─────────────────────────
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "prometheus-example",
            "OTEL_METRICS_EXPORTER": "prometheus",
        }
    )
    setup_telemetry(cfg)
    print("⚙️  OTEL_METRICS_EXPORTER=prometheus → pull reader attached")

    # ── 📊 Record instruments with units ───────────────────
    print("\n📊 Recording instruments:")
    requests = counter("example.prom.requests", "Requests handled", "1")
    requests.add(3, {"route": "/checkout"})
    print("  🔹 counter   example.prom.requests (unit 1)    +3")
    latency = histogram("example.prom.latency", "Request latency", "ms")
    for value in (12.5, 40.0, 87.5):
        latency.record(value, {"route": "/checkout"})
    print("  🔹 histogram example.prom.latency (unit ms)    12.5, 40.0, 87.5")
    queue_depth = 7
    depth = observable_gauge(
        "example.prom.queue_depth",
        lambda: [Observation(float(queue_depth), {"queue": "jobs"})],
        "Jobs waiting",
        "1",
    )
    print("  🔹 observable gauge example.prom.queue_depth   callback → 7")

    # ── 🔎 One scrape through the handler ──────────────────
    print("\n🔎 GET /metrics (in-process ASGI call):")
    status, content_type, body = asyncio.run(scrape())
    print(f"  ✅ {status}  {content_type}")
    names = metric_names(body)
    print("\n🏷️  Your metrics, as Prometheus names them (ms → _milliseconds, 1 → _ratio, counter → _total):")
    for name in names:
        if name.startswith("example_"):
            print(f"  🔸 {name}")
    print("\n🩺 SDK health series in the same scrape:")
    for name in names:
        if name.startswith("provide_telemetry_"):
            print(f"  🔸 {name}")
    for line in body.splitlines():
        if line.startswith("example_prom_queue_depth"):
            print(f"\n📏 Observable gauge sample: {line}")

    # ── 🧹 Shutdown ────────────────────────────────────────
    depth.unregister()
    shutdown_telemetry()
    status, _, reason = asyncio.run(scrape())
    print(f"\n🧹 After shutdown the handler answers {status}: {reason.strip()}")
    print("\n🏁 Done!")


if __name__ == "__main__":
    main()
