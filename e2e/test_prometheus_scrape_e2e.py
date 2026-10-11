# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tier 3 of the Prometheus contract: a real Prometheus scrapes the SDK listener.

A Prometheus 3 started with infra/prometheus/scrape-e2e.yml (host networking,
web on PROMETHEUS_SCRAPE_URL) scrapes 127.0.0.1:9464 as job provide-plain and
127.0.0.1:9465 over TLS with basic auth as job provide-secured. This test runs
the SDK's prometheus_scrape_probe on each port, the secured one with the web
config ci/prometheus-tls-setup.sh writes, and checks what Prometheus stored:
the scrape succeeded (up == 1), a counter and an observable gauge arrived with
their translated names and values, and the health series are there.

Requires PROMETHEUS_SCRAPE_URL and, for the secured case, PROMETHEUS_TLS_CA
(the web config sits beside it). Python, Go, TypeScript, C# and Rust implement the listener;
each SDK joins the parametrization as it ships Tier 3.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent
_READY_TIMEOUT_S = 300.0  # includes compiling the probe
_SCRAPE_TIMEOUT_S = 30.0
_AMBIENT_CA_VARS = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
_PROBES = {
    "python": ([sys.executable, "scripts/prometheus_scrape_probe.py"], _REPO_ROOT, sys.executable),
    "go": (["go", "run", "./cmd/prometheus_scrape_probe"], _REPO_ROOT / "go" / "otel", "go"),
    "typescript": (["npx", "tsx", "scripts/prometheus-scrape-probe.ts"], _REPO_ROOT / "typescript", "npx"),
    "csharp": (["dotnet", "run", "--project", "probes/PrometheusScrapeProbe"], _REPO_ROOT / "csharp", "dotnet"),
    "rust": (
        ["cargo", "run", "--locked", "--quiet", "--features", "prometheus-listener", "--example", "prometheus_scrape_probe"],
        _REPO_ROOT / "rust",
        "cargo",
    ),
}
_MODES = {"plain": ("9464", "provide-plain"), "secured": ("9465", "provide-secured")}


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def _query(base: str, promql: str) -> list[dict[str, Any]]:
    url = f"{base}/api/v1/query?{urlencode({'query': promql})}"
    with urlopen(url, timeout=10) as response:  # nosec B310 — test-supplied URL
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "success", payload
    result: list[dict[str, Any]] = payload["data"]["result"]
    return result


def _value(base: str, promql: str) -> float | None:
    result = _query(base, promql)
    return float(result[0]["value"][1]) if result else None


@pytest.fixture()
def probe(request: pytest.FixtureRequest) -> Iterator[str]:
    language, mode = request.param
    command, cwd, runtime = _PROBES[language]
    if shutil.which(runtime) is None:
        if os.getenv("PROVIDE_E2E_REQUIRE_ALL_RUNTIMES") == "1":
            pytest.fail(f"{runtime} is required for the {language} probe")
        pytest.skip(f"{runtime} is not installed")
    port, job = _MODES[mode]
    env = {k: v for k, v in os.environ.items() if k not in _AMBIENT_CA_VARS}
    env.update(
        {
            "OTEL_METRICS_EXPORTER": "prometheus",
            "PROVIDE_METRICS_PROMETHEUS_LISTEN": "true",
            "OTEL_EXPORTER_PROMETHEUS_HOST": "127.0.0.1",
            "OTEL_EXPORTER_PROMETHEUS_PORT": port,
            "PROVIDE_TELEMETRY_SERVICE_NAME": f"prometheus-scrape-probe-{language}",
        }
    )
    if mode == "secured":
        env["PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG"] = str(
            Path(_require("PROMETHEUS_TLS_CA")).parent / "web-config.yml"
        )
    proc = subprocess.Popen(  # nosec B603 — fixed probe command
        command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + _READY_TIMEOUT_S
        assert proc.stdout is not None
        line = proc.stdout.readline()
        while line.strip() != "ready":
            assert proc.poll() is None and time.monotonic() < deadline, (
                f"probe never became ready: {proc.stderr.read() if proc.stderr else ''}"
            )
            line = proc.stdout.readline()
        yield job
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.parametrize(
    "probe",
    [(lang, mode) for lang in _PROBES for mode in _MODES],
    ids=[f"{lang}-{mode}" for lang in _PROBES for mode in _MODES],
    indirect=True,
)
def test_prometheus_scrapes_the_sdk_listener(probe: str) -> None:
    base = _require("PROMETHEUS_SCRAPE_URL").rstrip("/")
    job = probe
    checks = {
        f'up{{job="{job}"}}': 1.0,
        f'e2e_scrape_requests_total{{job="{job}"}}': 3.0,
        f'e2e_scrape_temperature_celsius{{job="{job}"}}': 41.5,
    }
    deadline = time.monotonic() + _SCRAPE_TIMEOUT_S
    got: dict[str, float | None] = {}
    while time.monotonic() < deadline:
        got = {q: _value(base, q) for q in checks}
        if got == checks:
            break
        time.sleep(1)
    assert got == checks
    health = _value(base, f'provide_telemetry_emitted_total{{job="{job}",signal="metrics"}}')
    assert health is not None and health >= 1.0, "health series missing from the scrape"
