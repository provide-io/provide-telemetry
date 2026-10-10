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

The set of metric names under the run's prefix must match exactly, so a series
that arrives under an unexpected name fails rather than going unnoticed.
Divergences a language is known to have are listed in the fixture; the test
asserts the divergent name, so fixing one fails here until its entry is removed.

Requires PROMETHEUS_URL (e.g. http://127.0.0.1:9090). A language whose runtime
is missing is skipped, unless PROVIDE_E2E_REQUIRE_ALL_RUNTIMES=1, as in CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
import yaml

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent
_FIXTURES = _REPO_ROOT / "spec" / "prometheus_fixtures.yaml"
_LOCAL_TSX = _REPO_ROOT / "typescript" / "node_modules" / ".bin" / "tsx"
_PROBE_TIMEOUT_S = 600.0  # first cargo/dotnet build of the probe is slow
_QUERY_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class Probe:
    command: list[str]
    cwd: Path
    runtime: str


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


def _prometheus_url() -> str:
    url = os.getenv("PROMETHEUS_URL")
    if not url:
        pytest.skip("PROMETHEUS_URL is not set")
    return url.rstrip("/")


def _api(base: str, path: str, params: dict[str, str]) -> Any:
    with urlopen(f"{base}{path}?{urlencode(params)}", timeout=10) as response:  # nosec B310 — test-supplied URL
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "success", payload
    return payload["data"]


def _metric_names(base: str, escaped: str) -> set[str]:
    data = _api(base, "/api/v1/label/__name__/values", {"match[]": f'{{__name__=~"{escaped}_.+"}}'})
    return set(data)


def _sample(base: str, metric: str, labels: dict[str, str]) -> float | None:
    matchers = ",".join([f'__name__="{metric}"', *(f'{k}="{v}"' for k, v in sorted(labels.items()))])
    result = _api(base, "/api/v1/query", {"query": f"{{{matchers}}}"})["result"]
    if not result:
        return None
    assert len(result) == 1, f"{metric}{labels} matched {len(result)} series: {result}"
    return float(result[0]["value"][1])


def _expected(language: str, prefix: str, escaped: str) -> list[dict[str, Any]]:
    fixture = yaml.safe_load(_FIXTURES.read_text(encoding="utf-8"))["push_ingestion"]
    divergences = (fixture.get("known_divergences") or {}).get(language) or {}
    expected: list[dict[str, Any]] = []
    for series in fixture["expected_series"]:
        metric = divergences.get(series["metric"], series["metric"])
        expected.append({**series, "metric": metric.format(prefix=prefix, escaped=escaped)})
    return expected


@pytest.mark.parametrize("language", ["python", "typescript", "go", "rust", "csharp"])
def test_sdk_pushes_metrics_to_prometheus_over_otlp(language: str) -> None:
    base = _prometheus_url()
    probe = _probes()[language]
    if shutil.which(probe.runtime) is None:
        if os.getenv("PROVIDE_E2E_REQUIRE_ALL_RUNTIMES") == "1":
            pytest.fail(f"{probe.runtime} is required for the {language} probe")
        pytest.skip(f"{probe.runtime} is not installed")

    run_id = uuid.uuid4().hex[:10]
    prefix = f"e2e.prom.{language}.{run_id}"
    escaped = prefix.replace(".", "_")
    service = f"prometheus-push-probe-{language}"
    env = {
        **os.environ,
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"{base}/api/v1/otlp/v1/metrics",
        "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "http/protobuf",
        "PROVIDE_TELEMETRY_SERVICE_NAME": service,
        "PROVIDE_PROM_PROBE_PREFIX": prefix,
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
    }
    done = subprocess.run(  # nosec B603 — fixed probe commands
        probe.command, cwd=probe.cwd, env=env, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S, check=False
    )
    assert done.returncode == 0, f"{language} probe failed:\nstdout:\n{done.stdout}\nstderr:\n{done.stderr}"

    expected = _expected(language, prefix, escaped)
    want_names = {s["metric"] for s in expected}
    # Histograms also produce _bucket series; they are checked by name only.
    want_names |= {s["metric"].removesuffix("_count") + "_bucket" for s in expected if s["metric"].endswith("_count")}

    deadline = time.monotonic() + _QUERY_TIMEOUT_S
    while _metric_names(base, escaped) != want_names and time.monotonic() < deadline:
        time.sleep(1)
    assert _metric_names(base, escaped) == want_names

    for series in expected:
        value = _sample(base, series["metric"], {**series["labels"], "job": service})
        assert value == float(series["value"]), f"{series['metric']}: got {value}, want {series['value']}"
