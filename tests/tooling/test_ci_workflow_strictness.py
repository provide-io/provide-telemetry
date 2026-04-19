# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SPEC = REPO_ROOT / ".github" / "workflows" / "ci-spec.yml"
CI_GO = REPO_ROOT / ".github" / "workflows" / "ci-go.yml"
CI_RUST = REPO_ROOT / ".github" / "workflows" / "ci-rust.yml"
CI_PYTHON = REPO_ROOT / ".github" / "workflows" / "ci-python.yml"
CI_TYPESCRIPT = REPO_ROOT / ".github" / "workflows" / "ci-typescript.yml"
OTEL_COLLECTOR_CONFIG = REPO_ROOT / "tests" / "integration" / "otel-collector-config.yaml"


def test_ci_spec_watches_full_runtime_surface() -> None:
    workflow = CI_SPEC.read_text(encoding="utf-8")

    for expected in [
        '"spec/**"',
        '"ci/**"',
        '"src/provide/telemetry/**"',
        '"typescript/src/**"',
        '"go/**"',
        '"rust/**"',
        '".github/workflows/ci-spec.yml"',
    ]:
        assert expected in workflow

    # Strict defaults: the behavioral parity script runs output+contract checks by
    # default — no explicit --check-output flag is required in CI.
    assert "spec/run_behavioral_parity.py" in workflow
    assert "python spec/validate_conformance.py" in workflow


def test_python_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_PYTHON.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow


def test_strict_parity_bootstrap_installs_runtime_probe_dependencies() -> None:
    bootstrap = (REPO_ROOT / "ci" / "install_parity_deps.py").read_text(encoding="utf-8")

    assert '"uv", "sync", "--group", "dev", "--extra", "otel"' in bootstrap


def test_go_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_GO.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow


def test_rust_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_RUST.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "cargo test --manifest-path Cargo.toml --features otel" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow


def test_typescript_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_TYPESCRIPT.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow


def test_local_otlp_collector_exports_all_three_signals_to_files() -> None:
    config = OTEL_COLLECTOR_CONFIG.read_text(encoding="utf-8")

    for expected in [
        "verbosity: detailed",
        "logs:",
        "traces:",
        "metrics:",
    ]:
        assert expected in config
