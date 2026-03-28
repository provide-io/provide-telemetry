# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Minimal HTTP backend for cross-language distributed tracing E2E tests.

Run standalone:
    UNDEF_TRACE_ENABLED=true \\
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:5080/api/default/v1/traces \\
    OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ..." \\
    python e2e/backends/cross_language_server.py --port 18765

Endpoints:
    GET /traced   — extracts W3C traceparent, emits child span, returns 200
    GET /health   — returns 200 immediately (used by test to detect readiness)
    GET /shutdown — calls shutdown_telemetry() and exits (flushes OTel spans)
"""

from __future__ import annotations

import argparse
import http.server
import sys

from opentelemetry import trace
from opentelemetry.propagate import extract as otel_extract

from undef.telemetry import setup_telemetry, shutdown_telemetry
from undef.telemetry.config import TelemetryConfig


def _make_handler() -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # suppress default access logs

        def _send(self, status: int, body: bytes = b"ok") -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200)
                return

            if self.path == "/shutdown":
                self._send(200)
                shutdown_telemetry()
                sys.exit(0)

            if self.path == "/traced":
                # Extract W3C traceparent from incoming headers.
                # otel_extract() uses the globally configured W3C propagator,
                # which is registered by setup_telemetry() when OTel is enabled.
                carrier = {k.lower(): v for k, v in self.headers.items()}
                parent_ctx = otel_extract(carrier)

                tracer = trace.get_tracer("py.e2e.backend")
                with tracer.start_as_current_span(
                    "py.e2e.cross_language_handler",
                    context=parent_ctx,
                ):
                    # Span is a child of the incoming traceparent.
                    # The OTel batch processor will export it to OpenObserve.
                    pass

                self._send(200)
                return

            self._send(404, b"not found")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-language E2E backend server")
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()

    cfg = TelemetryConfig.from_env()
    setup_telemetry(cfg)

    # Signal readiness on stdout so the test can detect it.
    print(f"READY port={args.port}", flush=True)

    with http.server.HTTPServer(("127.0.0.1", args.port), _make_handler()) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
