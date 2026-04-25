# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SPEC = REPO_ROOT / ".github" / "workflows" / "ci-spec.yml"
CI_GO = REPO_ROOT / ".github" / "workflows" / "ci-go.yml"
CI_RUST = REPO_ROOT / ".github" / "workflows" / "ci-rust.yml"
CI_PYTHON = REPO_ROOT / ".github" / "workflows" / "ci-python.yml"
CI_TYPESCRIPT = REPO_ROOT / ".github" / "workflows" / "ci-typescript.yml"
CI_MUTATION = REPO_ROOT / ".github" / "workflows" / "ci-mutation.yml"
README = REPO_ROOT / "README.md"
TS_STRYKER = REPO_ROOT / "typescript" / "stryker.config.mjs"
OTEL_COLLECTOR_CONFIG = REPO_ROOT / "tests" / "integration" / "otel-collector-config.yaml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


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


def test_python_facing_workflows_retry_uv_sync() -> None:
    helper = "bash ci/run_uv_sync_with_retry.sh"

    for workflow_path in (CI_PYTHON, CI_MUTATION, REPO_ROOT / ".github" / "workflows" / "ci-shared.yml"):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert helper in workflow
        assert "- run: uv sync" not in workflow

    for workflow_path in (
        REPO_ROOT / ".github" / "workflows" / "release.yml",
        REPO_ROOT / ".github" / "workflows" / "ci-strip-governance.yml",
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert helper in workflow


def test_non_local_github_actions_are_sha_pinned() -> None:
    uses_pattern = re.compile(r"uses:\s+([^@\s]+)@([^\s#]+)")
    unpinned: list[str] = []
    for workflow_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        for line_no, line in enumerate(workflow_path.read_text(encoding="utf-8").splitlines(), start=1):
            match = uses_pattern.search(line)
            if match is None:
                continue
            action, ref = match.groups()
            if action.startswith("./"):
                continue
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                unpinned.append(f"{workflow_path.relative_to(REPO_ROOT)}:{line_no}: {action}@{ref}")
    assert unpinned == []


def test_strict_parity_bootstrap_installs_runtime_probe_dependencies() -> None:
    bootstrap = (REPO_ROOT / "ci" / "install_parity_deps.py").read_text(encoding="utf-8")

    assert '"uv", "sync", "--group", "dev", "--extra", "otel"' in bootstrap


def test_go_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_GO.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow
    assert "run: ../ci/wait-for-collector.sh" in workflow
    assert "hashFiles('go/logger/go.mod')" in workflow
    assert "hashFiles('go/tracer/go.mod')" in workflow
    assert "hashFiles('go/otel/go.mod')" in workflow


def test_rust_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_RUST.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "cargo test --manifest-path Cargo.toml --features otel" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow
    assert "run: ../ci/wait-for-collector.sh" in workflow


def test_typescript_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_TYPESCRIPT.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "otel/opentelemetry-collector-contrib:0.102.1" in workflow
    assert "PROVIDE_TEST_OTLP_ENDPOINT" in workflow
    assert "PROVIDE_TEST_OTLP_OUTPUT_DIR" in workflow


def test_mutation_workflow_keeps_rust_nightly_advisory() -> None:
    workflow = CI_MUTATION.read_text(encoding="utf-8")

    assert "rust-mutation:" in workflow
    assert "if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" in workflow
    assert "continue-on-error: ${{ github.event_name == 'schedule' }}" in workflow
    assert "hashFiles('go/logger/go.mod')" in workflow
    assert "hashFiles('go/tracer/go.mod')" in workflow
    assert "hashFiles('go/otel/go.mod')" in workflow


def test_typescript_mutation_threshold_matches_documented_regression_floor() -> None:
    stryker = TS_STRYKER.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "break: 95" in stryker
    assert "TypeScript runs Stryker with a 96.07% current score / 95% break threshold" in readme
    assert "Rust nightly mutation sweep is advisory" in readme


def test_python_mutation_threshold_matches_documented_regression_floor() -> None:
    workflow = CI_MUTATION.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "--min-mutation-score 95" in workflow
    assert "Python runs mutmut with a 95.90% current score / 95% minimum threshold" in readme


def test_local_otlp_collector_exports_all_three_signals_to_files() -> None:
    config = OTEL_COLLECTOR_CONFIG.read_text(encoding="utf-8")

    for expected in [
        "verbosity: detailed",
        "logs:",
        "traces:",
        "metrics:",
    ]:
        assert expected in config
