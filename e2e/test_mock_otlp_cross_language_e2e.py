# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language W3C traceparent propagation E2E test using a mock OTLP receiver.

Unlike the sibling ``test_cross_language_trace_e2e.py`` / ``test_three_way_trace_e2e.py``
suites, this test runs in the **default** pytest selection — it does not require
OpenObserve, Docker, or any external network resource.  A lightweight in-process
``MockOtlpReceiver`` (see ``e2e/backends/mock_otlp_receiver.py``) stands in for the
real backend.

The test orchestrates three language processes:

    TS  (root span)  ──traceparent──▶  Python backend  ──child span──▶  mock OTLP
    Go  (root span)  ──traceparent──▶  Python backend  ──child span──▶  mock OTLP

and asserts:

    1. Each client produces a span with a 32-char trace_id and a non-zero span_id.
    2. The Python backend produces a matching child span whose ``parent_span_id``
       equals the client's root span_id (W3C propagation actually worked).
    3. Both sides of the hop share the same trace_id (end-to-end correlation).
    4. The two clients use *different* trace_ids (no bleed between processes).

Skipped automatically when a required runtime is missing (node/go/tsx or the
``otel`` Python extra) — never fails hard.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from e2e.backends.mock_otlp_receiver import CapturedSpan, MockOtlpReceiver

pytestmark = pytest.mark.mock_e2e

_REPO_ROOT = Path(__file__).parent.parent
_SERVER_SCRIPT = _REPO_ROOT / "e2e" / "backends" / "cross_language_server.py"
_TS_SCRIPT = _REPO_ROOT / "typescript" / "scripts" / "e2e_cross_language_client.ts"
_GO_CLIENT_DIR = _REPO_ROOT / "go" / "cmd" / "e2e_cross_language_client"
# Prefer the locally-installed tsx (fast, offline); fall back to a system-wide
# ``tsx`` or ``npx --yes tsx`` when the worktree has no installed Node modules.
_LOCAL_TSX = _REPO_ROOT / "typescript" / "node_modules" / ".bin" / "tsx"

# Bounded overall timeout — the whole test should finish in well under 30 s.
_BACKEND_READY_TIMEOUT_S = 10.0
_CLIENT_TIMEOUT_S = 25.0
_SPAN_POLL_TIMEOUT_S = 15.0


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _resolve_tsx_command() -> list[str] | None:
    """Return the argv prefix needed to invoke ``tsx`` or ``None`` if not available."""
    if _LOCAL_TSX.exists():
        return [str(_LOCAL_TSX)]
    system_tsx = shutil.which("tsx")
    if system_tsx:
        return [system_tsx]
    npx = shutil.which("npx")
    if npx:
        # ``--yes`` skips the prompt if tsx is not yet in the npx cache.
        return [npx, "--yes", "tsx"]
    return None


def _skip_if_missing_runtimes() -> None:
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    if shutil.which("go") is None:
        pytest.skip("go not on PATH")
    if _resolve_tsx_command() is None:
        pytest.skip("tsx not available (neither local node_modules nor npx on PATH)")
    # The TS client imports from '../src/index' which pulls in @opentelemetry/api.
    # Without installed node_modules the import will fail at runtime — skip up front.
    if not (_REPO_ROOT / "typescript" / "node_modules" / "@opentelemetry" / "api").is_dir():
        pytest.skip("typescript/node_modules/@opentelemetry/api missing (run `npm ci` in typescript/)")


def _extract_trace_id(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("TRACE_ID="):
            return line.split("=", 1)[1].strip()
    return ""


def _wait_for_backend_ready(proc: subprocess.Popen[str], timeout: float) -> str:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            # Drain remaining stderr for a useful error message.
            stderr = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"backend exited before READY: stderr={stderr!r}")
        line = proc.stdout.readline()
        if line and line.startswith("READY"):
            return line.strip()
        if not line:
            time.sleep(0.05)
    raise AssertionError("backend did not become ready within timeout")


def _start_python_backend(port: int, otlp_base: str) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "PROVIDE_TRACE_ENABLED": "true",
        "PROVIDE_METRICS_ENABLED": "false",
        "PROVIDE_LOG_OTEL_ENABLED": "false",
        "PROVIDE_TELEMETRY_SERVICE_NAME": "py-mock-e2e-backend",
        "PROVIDE_TELEMETRY_VERSION": "mock-e2e",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{otlp_base}/v1/traces",
        # Drive the BSP hard so spans flush before shutdown without padding the test budget.
        "OTEL_BSP_SCHEDULE_DELAY": "100",
        "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "1",
        "OTEL_BSP_EXPORT_TIMEOUT": "2000",
    }
    return subprocess.Popen(
        [sys.executable, str(_SERVER_SCRIPT), "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def _run_ts_client(backend_url: str, otlp_base: str) -> subprocess.CompletedProcess[str]:
    tsx_cmd = _resolve_tsx_command()
    assert tsx_cmd is not None, "tsx command resolution failed — _skip_if_missing_runtimes should have skipped"
    env = {
        **os.environ,
        "E2E_BACKEND_URL": backend_url,
        # Dummy creds — the mock receiver does not validate auth, but the TS
        # client script requires these env vars to be set.
        "OPENOBSERVE_USER": "mock",
        "OPENOBSERVE_PASSWORD": "mock",
        "OTEL_EXPORTER_OTLP_ENDPOINT": otlp_base,
    }
    return subprocess.run(
        [*tsx_cmd, str(_TS_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=_CLIENT_TIMEOUT_S,
        cwd=str(_REPO_ROOT / "typescript"),
        check=False,
    )


def _run_go_client(backend_url: str, otlp_base: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "E2E_BACKEND_URL": backend_url,
        "OPENOBSERVE_USER": "mock",
        "OPENOBSERVE_PASSWORD": "mock",
        "OTEL_EXPORTER_OTLP_ENDPOINT": otlp_base,
    }
    return subprocess.run(
        ["go", "run", "."],
        env=env,
        capture_output=True,
        text=True,
        timeout=_CLIENT_TIMEOUT_S,
        cwd=str(_GO_CLIENT_DIR),
        check=False,
    )


def _shutdown_backend(proc: subprocess.Popen[str], port: int) -> None:
    # The backend's /shutdown endpoint calls shutdown_telemetry() and exits, which
    # flushes the BatchSpanProcessor. Fall back to terminate() if the HTTP call
    # fails (e.g. connection reset because the server exits mid-response).
    try:
        from urllib.request import Request, urlopen

        urlopen(Request(f"http://127.0.0.1:{port}/shutdown", method="GET"), timeout=2)
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=3)


def _poll_for_spans(
    receiver: MockOtlpReceiver,
    trace_id: str,
    min_count: int,
    timeout: float,
) -> list[CapturedSpan]:
    """Poll the mock receiver until at least ``min_count`` spans share ``trace_id``."""
    deadline = time.monotonic() + timeout
    hits: list[CapturedSpan] = []
    while time.monotonic() < deadline:
        hits = receiver.spans_for_trace(trace_id)
        if len(hits) >= min_count:
            return hits
        time.sleep(0.1)
    return hits


def _run_hop(
    receiver: MockOtlpReceiver,
    language: str,
    run_client: subprocess.CompletedProcess[str],
) -> tuple[str, str, str]:
    """Execute one hop of the orchestration and return (trace_id, root_span_id, service_name).

    ``run_client`` is the already-executed subprocess result; we keep this helper
    purely for assertion structuring so each hop's failure surface is obvious.
    """
    assert run_client.returncode == 0, (
        f"{language} client failed (exit {run_client.returncode}):\n"
        f"stdout: {run_client.stdout!r}\nstderr: {run_client.stderr!r}"
    )
    trace_id = _extract_trace_id(run_client.stdout)
    assert trace_id and len(trace_id) == 32, (
        f"expected 32-char TRACE_ID in {language} stdout, got: {run_client.stdout!r}"
    )

    # Wait for ≥2 spans (client root + python child) sharing this trace_id.
    hits = _poll_for_spans(receiver, trace_id, min_count=2, timeout=_SPAN_POLL_TIMEOUT_S)
    assert len(hits) >= 2, (
        f"{language}: expected >=2 captured spans for trace_id={trace_id!r}, got {len(hits)}. "
        f"client stdout: {run_client.stdout!r}"
    )

    # Identify the root span (no parent) vs the Python child.
    roots = [h for h in hits if int(h.parent_span_id or "0", 16) == 0]
    children = [h for h in hits if int(h.parent_span_id or "0", 16) != 0]
    assert roots, f"{language}: no root span (all {len(hits)} spans had a parent)"
    assert children, f"{language}: no child span (backend context propagation did not fire)"

    root = roots[0]
    child = children[0]

    # Core propagation assertion: the Python child's parent_span_id is the client's span_id.
    assert child.parent_span_id == root.span_id, (
        f"{language}: child.parent_span_id={child.parent_span_id!r} != root.span_id={root.span_id!r}"
    )
    assert child.service_name == "py-mock-e2e-backend", (
        f"{language}: expected backend service_name=py-mock-e2e-backend, got {child.service_name!r}"
    )

    return trace_id, root.span_id, root.service_name


def test_cross_language_mock_otlp_traceparent_propagation(mock_otlp_receiver: MockOtlpReceiver) -> None:
    """Python backend relays TS/Go traceparents to the mock receiver with intact trace_ids."""

    _skip_if_missing_runtimes()
    pytest.importorskip("opentelemetry")

    otlp_base: str = mock_otlp_receiver.endpoint
    backend_port = _find_free_port()
    backend_url = f"http://127.0.0.1:{backend_port}"

    server_proc = _start_python_backend(backend_port, otlp_base)
    try:
        _wait_for_backend_ready(server_proc, _BACKEND_READY_TIMEOUT_S)

        # ── Hop 1: TypeScript ────────────────────────────────────────────────
        ts_result = _run_ts_client(backend_url, otlp_base)
        ts_trace_id, ts_root_span_id, ts_service = _run_hop(mock_otlp_receiver, "typescript", ts_result)
        assert ts_service == "ts-e2e-client", f"unexpected TS service name: {ts_service!r}"

        # ── Hop 2: Go ────────────────────────────────────────────────────────
        go_result = _run_go_client(backend_url, otlp_base)
        go_trace_id, go_root_span_id, _go_service = _run_hop(mock_otlp_receiver, "go", go_result)

        # The two hops must not collide — independent clients always get
        # fresh trace_ids / span_ids.
        assert ts_trace_id != go_trace_id, "TS and Go produced the same trace_id (impossible)"
        assert ts_root_span_id != go_root_span_id, "TS and Go produced the same root span_id"

    finally:
        _shutdown_backend(server_proc, backend_port)
