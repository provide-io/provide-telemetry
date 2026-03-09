# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

pytestmark = pytest.mark.otel


def test_otlp_http_exports_all_three_signal_types() -> None:
    pytest.importorskip("opentelemetry")
    received: list[dict[str, str | int]] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            received.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization") or "",
                    "content_type": self.headers.get("Content-Type") or "",
                    "size": len(body),
                }
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            _ = (format, args)
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server_port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        auth = "Basic " + base64.b64encode(b"someuserexample@provide.test:password").decode("ascii")
        env = dict(os.environ)
        env.update(
            {
                "UNDEF_TELEMETRY_SERVICE_NAME": "otlp-local-http-test",
                "UNDEF_TRACE_ENABLED": "true",
                "UNDEF_METRICS_ENABLED": "true",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"http://127.0.0.1:{server_port}/v1/traces",
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"http://127.0.0.1:{server_port}/v1/metrics",
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"http://127.0.0.1:{server_port}/v1/logs",
                "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization={auth}",
                "OTEL_BSP_SCHEDULE_DELAY": "200",
                "OTEL_METRIC_EXPORT_INTERVAL": "1000",
            }
        )
        code = (
            "from undef.telemetry import counter, get_logger, setup_telemetry, shutdown_telemetry, trace\n"
            "setup_telemetry()\n"
            "@trace('otlp.local_http.span')\n"
            "def run(i: int) -> None:\n"
            "    get_logger('otlp.local_http').info('otlp.local_http.log', iteration=str(i))\n"
            "    counter('otlp.local_http.requests').add(1, {'iteration': str(i)})\n"
            "for i in range(3):\n"
            "    run(i)\n"
            "shutdown_telemetry()\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True, env=env)

        server.shutdown()
        server.server_close()

        payload = json.dumps(received)
        assert any(item["path"] == "/v1/logs" and int(item["size"]) > 0 for item in received), payload
        assert any(item["path"] == "/v1/metrics" and int(item["size"]) > 0 for item in received), payload
        assert any(item["path"] == "/v1/traces" and int(item["size"]) > 0 for item in received), payload
        assert all(item["auth"] == auth for item in received), payload
        assert all(item["content_type"] == "application/x-protobuf" for item in received), payload
    finally:
        server.shutdown()
        server.server_close()
