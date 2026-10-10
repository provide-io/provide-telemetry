# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tier 1 of the Prometheus contract: every SDK pushes to Prometheus 3 over OTLP.

Each language's prometheus_push_probe records the push_ingestion instruments
from spec/prometheus_fixtures.yaml and pushes them with the ordinary OTLP
metrics exporter to a Prometheus 3 started with --web.enable-otlp-receiver and
infra/prometheus/prometheus.yml. This test then reads the series back through
the Prometheus HTTP API and checks names, labels and values.

Three modes, each against its own Prometheus:

- plain           PROMETHEUS_URL (http, no auth)
- basic_auth      PROMETHEUS_AUTH_URL (http, basic auth via
                  OTEL_EXPORTER_OTLP_METRICS_HEADERS)
- tls_basic_auth  PROMETHEUS_TLS_URL (https with a private CA given through
                  OTEL_EXPORTER_OTLP_CERTIFICATE, plus basic auth)

The secured modes also need PROMETHEUS_BASIC_AUTH_USER, _PASSWORD and, for TLS,
PROMETHEUS_TLS_CA. ci/prometheus-tls-setup.sh generates the certificates and
web config. A mode whose URL is unset is skipped.

The set of metric names under the run's prefix must match exactly, so a series
that arrives under an unexpected name fails rather than going unnoticed.
Divergences and unsupported modes a language is known to have are listed in
the fixture; the test asserts the current behaviour, so fixing one fails here
until its entry is removed.

A language whose runtime is missing is skipped, unless
PROVIDE_E2E_REQUIRE_ALL_RUNTIMES=1, as in CI.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pytest
import yaml

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent
_FIXTURES = _REPO_ROOT / "spec" / "prometheus_fixtures.yaml"
_LOCAL_TSX = _REPO_ROOT / "typescript" / "node_modules" / ".bin" / "tsx"
_LANGUAGES = ["python", "typescript", "go", "rust", "csharp"]
_MODES = ["plain", "basic_auth", "tls_basic_auth"]
_PROBE_TIMEOUT_S = 600.0  # first cargo/dotnet build of the probe is slow
_QUERY_TIMEOUT_S = 30.0
_ABSENT_WAIT_S = 5.0  # the probe has already drained on exit; this is margin
# Trust-store variables a runner may set. They are removed from the probe's
# environment so only the OTel certificate variables can make TLS succeed.
_AMBIENT_CA_VARS = (
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH",
)


@dataclass(frozen=True)
class Probe:
    command: list[str]
    cwd: Path
    runtime: str


@dataclass(frozen=True)
class Target:
    """One Prometheus instance and how to reach it."""

    base: str
    auth: str | None = None
    ca_file: str | None = None

    def context(self) -> ssl.SSLContext | None:
        return ssl.create_default_context(cafile=self.ca_file) if self.ca_file else None


def _probes() -> dict[str, Probe]:
    tsx = [str(_LOCAL_TSX)] if _LOCAL_TSX.exists() else ["npx", "--yes", "tsx"]
    return {
        "python": Probe([sys.executable, "scripts/prometheus_push_probe.py"], _REPO_ROOT, sys.executable),
        "typescript": Probe([*tsx, "scripts/prometheus-push-probe.ts"], _REPO_ROOT / "typescript", "node"),
        "go": Probe(["go", "run", "./cmd/prometheus_push_probe"], _REPO_ROOT / "go" / "otel", "go"),
        "rust": Probe(
            ["cargo", "run", "--locked", "--quiet", "--features", "otel", "--example", "prometheus_push_probe"],
            _REPO_ROOT / "rust",
            "cargo",
        ),
        "csharp": Probe(
            ["dotnet", "run", "--project", "probes/PrometheusPushProbe"],
            _REPO_ROOT / "csharp",
            "dotnet",
        ),
    }


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def _target(mode: str) -> Target:
    if mode == "plain":
        return Target(_require("PROMETHEUS_URL").rstrip("/"))
    base = _require("PROMETHEUS_AUTH_URL" if mode == "basic_auth" else "PROMETHEUS_TLS_URL").rstrip("/")
    user = _require("PROMETHEUS_BASIC_AUTH_USER")
    password = _require("PROMETHEUS_BASIC_AUTH_PASSWORD")
    auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    ca_file = _require("PROMETHEUS_TLS_CA") if mode == "tls_basic_auth" else None
    return Target(base, auth, ca_file)


def _api(target: Target, path: str, params: dict[str, str]) -> Any:
    headers = {"Authorization": target.auth} if target.auth else {}
    request = Request(f"{target.base}{path}?{urlencode(params)}", headers=headers)
    with urlopen(request, timeout=10, context=target.context()) as response:  # nosec B310 — test-supplied URL
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "success", payload
    return payload["data"]


def _metric_names(target: Target, escaped: str) -> set[str]:
    data = _api(target, "/api/v1/label/__name__/values", {"match[]": f'{{__name__=~"{escaped}_.+"}}'})
    return set(data)


def _sample(target: Target, metric: str, labels: dict[str, str]) -> float | None:
    matchers = ",".join([f'__name__="{metric}"', *(f'{k}="{v}"' for k, v in sorted(labels.items()))])
    result = _api(target, "/api/v1/query", {"query": f"{{{matchers}}}"})["result"]
    if not result:
        return None
    assert len(result) == 1, f"{metric}{labels} matched {len(result)} series: {result}"
    return float(result[0]["value"][1])


def _fixture() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_FIXTURES.read_text(encoding="utf-8"))["push_ingestion"]
    return loaded


def _expected(fixture: dict[str, Any], language: str, prefix: str, escaped: str) -> list[dict[str, Any]]:
    divergences = (fixture.get("known_divergences") or {}).get(language) or {}
    expected: list[dict[str, Any]] = []
    for series in fixture["expected_series"]:
        metric = divergences.get(series["metric"], series["metric"])
        expected.append({**series, "metric": metric.format(prefix=prefix, escaped=escaped)})
    return expected


def _probe_env(target: Target, service: str, prefix: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _AMBIENT_CA_VARS}
    env.update(
        {
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"{target.base}/api/v1/otlp/v1/metrics",
            "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "http/protobuf",
            "PROVIDE_TELEMETRY_SERVICE_NAME": service,
            "PROVIDE_PROM_PROBE_PREFIX": prefix,
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
        }
    )
    if target.auth:
        # Header values are URL-decoded by every SDK (see docs/guide/configuration.md).
        env["OTEL_EXPORTER_OTLP_METRICS_HEADERS"] = f"Authorization={quote(target.auth)}"
    if target.ca_file:
        env["OTEL_EXPORTER_OTLP_CERTIFICATE"] = target.ca_file
        env["OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE"] = target.ca_file
    return env


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("language", _LANGUAGES)
def test_sdk_pushes_metrics_to_prometheus_over_otlp(language: str, mode: str) -> None:
    target = _target(mode)
    probe = _probes()[language]
    if shutil.which(probe.runtime) is None:
        if os.getenv("PROVIDE_E2E_REQUIRE_ALL_RUNTIMES") == "1":
            pytest.fail(f"{probe.runtime} is required for the {language} probe")
        pytest.skip(f"{probe.runtime} is not installed")

    fixture = _fixture()
    unsupported = ((fixture.get("unsupported_modes") or {}).get(mode) or {}).get(language)
    run_id = uuid.uuid4().hex[:10]
    prefix = f"e2e.prom.{language}.{mode}.{run_id}"
    escaped = prefix.replace(".", "_")
    service = f"prometheus-push-probe-{language}"
    done = subprocess.run(  # nosec B603 — fixed probe commands
        probe.command,
        cwd=probe.cwd,
        env=_probe_env(target, service, prefix),
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
        check=False,
    )

    if unsupported:
        # The export fails open, so the probe may still exit 0; what must hold
        # is that nothing arrived. Data arriving means the gap is closed.
        time.sleep(_ABSENT_WAIT_S)
        arrived = _metric_names(target, escaped)
        assert not arrived, (
            f"{language} now delivers in mode {mode} ({sorted(arrived)}); remove its "
            f"push_ingestion.unsupported_modes entry: {unsupported}"
        )
        return

    assert done.returncode == 0, f"{language} probe failed:\nstdout:\n{done.stdout}\nstderr:\n{done.stderr}"
    expected = _expected(fixture, language, prefix, escaped)
    want_names = {s["metric"] for s in expected}
    # Histograms also produce _bucket series; they are checked by name only.
    want_names |= {s["metric"].removesuffix("_count") + "_bucket" for s in expected if s["metric"].endswith("_count")}

    deadline = time.monotonic() + _QUERY_TIMEOUT_S
    while _metric_names(target, escaped) != want_names and time.monotonic() < deadline:
        time.sleep(1)
    assert _metric_names(target, escaped) == want_names, f"probe stderr:\n{done.stderr}"

    for series in expected:
        value = _sample(target, series["metric"], {**series["labels"], "job": service})
        assert value == float(series["value"]), f"{series['metric']}: got {value}, want {series['value']}"
