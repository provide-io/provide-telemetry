# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""In-process mock OTLP/HTTP receiver for cross-language E2E tests.

Accepts POSTs on:
    /v1/traces   — ExportTraceServiceRequest  (protobuf, optionally gzip'd)
    /v1/logs     — ExportLogsServiceRequest   (accepted, bytes captured raw)
    /v1/metrics  — ExportMetricsServiceRequest (accepted, bytes captured raw)
    /health      — returns 200 immediately (used for readiness)

Decoded spans are exposed via ``MockOtlpReceiver.spans`` — a thread-safe list of
``CapturedSpan`` dataclasses capturing the fields needed to assert W3C
traceparent propagation (trace_id / span_id / parent_span_id / service_name /
name).

The receiver binds to an ephemeral port on 127.0.0.1, runs in a background
thread, and shuts down cleanly via ``stop()``.  No external dependencies beyond
``opentelemetry-proto`` (already required by the ``otel`` extra).
"""

from __future__ import annotations

import base64
import binascii
import gzip
import http.server
import json
import socketserver
import threading
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.proto.collector.trace.v1 import trace_service_pb2


@dataclass(slots=True)
class CapturedSpan:
    """Minimal view of a span captured by the mock receiver."""

    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    service_name: str


@dataclass(slots=True)
class MockOtlpReceiver:
    """Background OTLP/HTTP receiver with thread-safe captured payload lists."""

    host: str = "127.0.0.1"
    port: int = 0  # 0 → ephemeral; filled in on start()
    spans: list[CapturedSpan] = field(default_factory=list)
    raw_trace_bodies: list[bytes] = field(default_factory=list)
    raw_log_bodies: list[bytes] = field(default_factory=list)
    raw_metric_bodies: list[bytes] = field(default_factory=list)
    _server: socketserver.BaseServer | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def endpoint(self) -> str:
        """Base URL usable as OTEL_EXPORTER_OTLP_ENDPOINT."""
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """Start the receiver on an ephemeral port in a background thread."""
        handler = _make_handler(self)

        class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        server = _ThreadingHTTPServer((self.host, self.port), handler)
        self.port = int(server.server_address[1])
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="mock-otlp-receiver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Shut down the receiver and join the background thread."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ── Captured-data access ────────────────────────────────────────────────
    def snapshot_spans(self) -> list[CapturedSpan]:
        """Return a copy of captured spans (thread-safe)."""
        with self._lock:
            return list(self.spans)

    def spans_for_trace(self, trace_id: str) -> list[CapturedSpan]:
        """Return all captured spans sharing the given trace_id (hex, 32-char)."""
        tid = trace_id.lower()
        return [s for s in self.snapshot_spans() if s.trace_id.lower() == tid]

    # ── Internal: invoked by the request handler ─────────────────────────────
    def _record_trace(self, raw: bytes, decoded: list[CapturedSpan]) -> None:
        with self._lock:
            self.raw_trace_bodies.append(raw)
            self.spans.extend(decoded)

    def _record_log(self, raw: bytes) -> None:
        with self._lock:
            self.raw_log_bodies.append(raw)

    def _record_metric(self, raw: bytes) -> None:
        with self._lock:
            self.raw_metric_bodies.append(raw)


def _decode_spans(body: bytes, content_type: str) -> list[CapturedSpan]:
    """Parse an OTLP export payload into ``CapturedSpan`` rows.

    Supports both protobuf (``application/x-protobuf`` — Python & Go SDKs) and
    JSON (``application/json`` — TypeScript SDK).  The JSON form uses OTLP's
    canonical encoding where trace/span IDs are hex strings or base64.
    """
    ct = (content_type or "").lower()
    if "json" in ct:
        return _decode_spans_json(body)
    return _decode_spans_protobuf(body)


def _decode_spans_protobuf(body: bytes) -> list[CapturedSpan]:
    req = trace_service_pb2.ExportTraceServiceRequest()
    req.ParseFromString(body)
    out: list[CapturedSpan] = []
    for rs in req.resource_spans:
        service_name = _lookup_service_name(rs.resource.attributes)
        for ss in rs.scope_spans:
            for span in ss.spans:
                out.append(
                    CapturedSpan(
                        trace_id=span.trace_id.hex(),
                        span_id=span.span_id.hex(),
                        parent_span_id=span.parent_span_id.hex(),
                        name=span.name,
                        service_name=service_name,
                    )
                )
    return out


def _decode_spans_json(body: bytes) -> list[CapturedSpan]:
    doc = json.loads(body.decode("utf-8"))
    out: list[CapturedSpan] = []
    for rs in doc.get("resourceSpans", []) or []:
        resource = rs.get("resource") or {}
        service_name = _lookup_service_name_json(resource.get("attributes") or [])
        for ss in rs.get("scopeSpans", []) or []:
            for span in ss.get("spans", []) or []:
                out.append(
                    CapturedSpan(
                        trace_id=_decode_hex_or_b64(str(span.get("traceId") or "")),
                        span_id=_decode_hex_or_b64(str(span.get("spanId") or "")),
                        parent_span_id=_decode_hex_or_b64(str(span.get("parentSpanId") or "")),
                        name=str(span.get("name") or ""),
                        service_name=service_name,
                    )
                )
    return out


def _decode_hex_or_b64(value: str) -> str:
    """OTLP/JSON encodes binary IDs as base64 per the spec, but some SDKs emit hex.

    Return the canonical lower-case hex form regardless of which encoding was used.
    """
    if not value:
        return ""
    # All-hex string of the right length → already hex.
    stripped = value.strip()
    if len(stripped) in (16, 32) and all(c in "0123456789abcdefABCDEF" for c in stripped):
        return stripped.lower()
    try:
        return base64.b64decode(stripped).hex()
    except (binascii.Error, ValueError):
        return stripped.lower()


def _lookup_service_name(attrs: Any) -> str:
    """Extract ``service.name`` from an OTLP protobuf resource attribute list."""
    for kv in attrs:
        if kv.key == "service.name":
            # AnyValue is a oneof; service.name is always string_value.
            return str(kv.value.string_value)
    return ""


def _lookup_service_name_json(attrs: list[dict[str, Any]]) -> str:
    """Extract ``service.name`` from a JSON-encoded OTLP resource attribute list."""
    for kv in attrs:
        if kv.get("key") == "service.name":
            value = kv.get("value") or {}
            sv = value.get("stringValue")
            if isinstance(sv, str):
                return sv
    return ""


def _maybe_gunzip(body: bytes, headers: Any) -> bytes:
    """Decompress gzip-encoded bodies iff Content-Encoding says so."""
    encoding = (headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        return gzip.decompress(body)
    return body


def _make_handler(receiver: MockOtlpReceiver) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # silence stderr access log

        def _send_ok(self, body: bytes = b"") -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_ok(b"ok")
                return
            self.send_response(404)
            self.end_headers()

        def _read_body(self) -> bytes:
            """Read a request body respecting Content-Length or Transfer-Encoding: chunked.

            The TS OTLP exporter in Node streams the request with chunked transfer
            encoding (no Content-Length), so ``self.rfile.read(Content-Length)``
            returns zero bytes and we silently drop the payload.  Handle both.
            """
            cl_header = self.headers.get("Content-Length")
            if cl_header is not None:
                try:
                    length = int(cl_header)
                except ValueError:
                    length = 0
                return self.rfile.read(length) if length > 0 else b""

            te_header = (self.headers.get("Transfer-Encoding") or "").lower()
            if "chunked" in te_header:
                chunks: list[bytes] = []
                while True:
                    size_line = self.rfile.readline().strip()
                    if not size_line:
                        break
                    try:
                        size = int(size_line.split(b";", 1)[0], 16)
                    except ValueError:
                        break
                    if size == 0:
                        # Consume trailer/CRLF and stop.
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()  # trailing CRLF after each chunk
                return b"".join(chunks)
            return b""

        def do_POST(self) -> None:
            raw = self._read_body()
            try:
                body = _maybe_gunzip(raw, self.headers)
            except OSError:
                # malformed gzip — still ack so exporter doesn't retry storm
                self._send_ok()
                return

            if self.path == "/v1/traces":
                content_type = self.headers.get("Content-Type") or ""
                try:
                    spans = _decode_spans(body, content_type)
                except Exception:
                    spans = []
                receiver._record_trace(body, spans)
                # Empty ExportTraceServiceResponse is a valid ACK.
                self._send_ok()
                return

            if self.path == "/v1/logs":
                receiver._record_log(body)
                self._send_ok()
                return

            if self.path == "/v1/metrics":
                receiver._record_metric(body)
                self._send_ok()
                return

            self.send_response(404)
            self.end_headers()

    return Handler
