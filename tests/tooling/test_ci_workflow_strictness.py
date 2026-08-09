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

    for workflow_path in (REPO_ROOT / ".github" / "workflows" / "release.yml",):
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
    assert "hashFiles('go/otel/go.mod')" in workflow


def test_rust_ci_runs_real_otlp_collector_gate() -> None:
    workflow = CI_RUST.read_text(encoding="utf-8")

    assert "otlp-integration:" in workflow
    assert "--fail-uncovered-lines 0 --fail-under-functions 100" in workflow
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


def test_mutation_workflow_gates_every_changed_language() -> None:
    workflow = CI_MUTATION.read_text(encoding="utf-8")

    assert "rust-mutation:" in workflow
    assert "if: needs.changes.outputs.rust == 'true'" in workflow
    assert "continue-on-error:" not in workflow
    assert "cargo-nextest --version 0.9.140 --locked" in workflow
    assert "cargo-mutants --version 27.1.0 --locked" in workflow
    assert 'CARGO_PROFILE_TEST_DEBUG: "0"' in workflow
    assert "gremlins/cmd/gremlins@v0.6.0" in workflow
    assert workflow.count("--threshold-efficacy=100") == 3
    assert workflow.count("--threshold-mcover=100") == 3
    assert '--exclude-files="mutation_constants.go"' in workflow
    # go/otel is a separate module, so its step is legitimately conditional.
    # go/logger is a package of the root module and must NOT be gated on a
    # go.mod that will never exist — that gate silently skipped the step.
    assert "hashFiles('go/otel/go.mod')" in workflow
    assert "hashFiles('go/logger/go.mod')" not in workflow
    assert "Run gremlins mutation tests for go/logger" in workflow


def test_rust_mutation_workflow_bounds_compiler_and_test_parallelism() -> None:
    workflow = CI_MUTATION.read_text(encoding="utf-8")

    assert 'CARGO_BUILD_JOBS: "1"' in workflow
    assert 'NEXTEST_TEST_THREADS: "1"' in workflow
    assert "--jobserver-tasks 1" in workflow
    assert '--shard "${{ matrix.shard }}"' in workflow

    # cargo-mutants rejects -j alongside --in-place, so fan-out is bounded by
    # the two environment variables and --jobserver-tasks instead. Asserting
    # the literal flag string would pin an incompatible pair.
    assert " -j 1" not in workflow


def test_rust_mutation_runs_in_place_so_spec_reading_tests_can_find_the_spec() -> None:
    """cargo-mutants must not copy the crate to a scratch directory.

    config_applicability.rs, receipt_fixtures.rs and jcs_number_fixtures.rs all
    locate the spec with ``concat!(env!("CARGO_MANIFEST_DIR"), "/../spec/…")``,
    which resolves at compile time. Inside a copied crate that path does not
    exist, so ``cargo test`` fails in the unmutated tree and cargo-mutants
    exits having tested zero mutants — a broken gate that reads as a red build
    for the wrong reason, and would read as a pass to anyone skimming for
    "0 survivors".
    """
    workflow = CI_MUTATION.read_text(encoding="utf-8")

    assert "cargo mutants --in-place" in workflow


def test_typescript_mutation_threshold_matches_documented_regression_floor() -> None:
    stryker = TS_STRYKER.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "break: 95" in stryker
    assert "break: 80" in (REPO_ROOT / "typescript" / "stryker.otel.config.mjs").read_text(encoding="utf-8")
    assert "TypeScript uses Stryker with a 95% core break threshold plus an 80% OTLP transport ratchet" in readme
    assert "Rust requires a 100% cargo-mutants kill rate" in readme


def test_python_mutation_threshold_matches_documented_regression_floor() -> None:
    workflow = CI_MUTATION.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "--min-mutation-score 95" in workflow
    # The README used to say Python "runs mutmut with a 95% minimum threshold",
    # which understated the gate: _is_clean() rejects any survivor, timeout,
    # suspicious or no-tests result, and the 95% floor is an additional guard
    # that a run at 99% still fails. Pin the accurate wording.
    assert "fails on any survivor, timeout, suspicious, or no-tests result" in readme
    assert "the 95% score floor is an extra guard, not the bar" in readme


def test_csharp_mutation_threshold_matches_the_measured_baseline() -> None:
    """C#'s Stryker threshold must be a measured number, not an aspiration.

    Every other language's threshold in this repo reflects reality. A break
    threshold above the real score is a gate that fails on unchanged code and
    gets disabled, which is how a suite ends up with no mutation coverage at
    all while appearing to have one.
    """
    import json

    config = json.loads((REPO_ROOT / "csharp" / "stryker-config.json").read_text(encoding="utf-8"))
    thresholds = config.get("stryker-config", config)["thresholds"]
    readme = README.read_text(encoding="utf-8")

    assert thresholds["break"] == 78
    assert "break threshold of 78" in readme
    assert "79.14%" in readme


def test_local_otlp_collector_exports_all_three_signals_to_files() -> None:
    config = OTEL_COLLECTOR_CONFIG.read_text(encoding="utf-8")

    for expected in [
        "verbosity: detailed",
        "logs:",
        "traces:",
        "metrics:",
    ]:
        assert expected in config
