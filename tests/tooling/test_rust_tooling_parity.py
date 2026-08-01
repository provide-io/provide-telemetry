# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent


def test_rust_cargo_toml_enables_parameterized_test_support() -> None:
    cargo_toml = (_REPO_ROOT / "rust" / "Cargo.toml").read_text(encoding="utf-8")

    assert "[dev-dependencies]" in cargo_toml
    assert 'rstest = "' in cargo_toml


def test_ci_mutation_workflow_includes_rust_job() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "ci-mutation.yml").read_text(encoding="utf-8")

    assert "rust-mutation:" in workflow
    assert "cargo-mutants" in workflow
    assert "cargo-nextest" in workflow
    assert "--all-features" in workflow
    assert "--test-tool nextest" in workflow
    assert '--shard "${{ matrix.shard }}"' in workflow
    assert '"1/8"' in workflow
    assert '"8/8"' in workflow
    assert "fail-fast: false" in workflow
    assert "working-directory: rust" in workflow


def test_ci_mutation_workflow_routes_jobs_by_language_changes() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "ci-mutation.yml").read_text(encoding="utf-8")

    assert "Detect changed implementation surfaces" in workflow
    assert "git diff --name-only" in workflow
    assert "git rev-parse HEAD" in workflow
    assert "python-mutation" in workflow
    assert "typescript-mutation" in workflow
    assert "rust-mutation" in workflow
    assert 'echo "python=${python}"' in workflow
    assert 'echo "typescript=${typescript}"' in workflow
    assert 'echo "rust=${rust}"' in workflow
    assert 'echo "go=${go}"' in workflow
    assert "needs.changes.outputs.python" in workflow
    assert "needs.changes.outputs.typescript" in workflow
    assert "if: needs.changes.outputs.rust == 'true'" in workflow
    assert "continue-on-error: true" not in workflow
    assert "tests/tooling/test_rust_*.py) ;;" in workflow


def test_mutation_policy_changes_trigger_their_language_gate() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "ci-mutation.yml").read_text(encoding="utf-8")

    for policy_path in (
        # Python's mutation roots live in [tool.mutmut] here — this is what
        # scripts/run_mutation_gate.py actually reads.
        "pyproject.toml",
        "rust/.cargo/mutants.toml",
        "typescript/stryker.config.mjs",
        "typescript/stryker.otel.config.mjs",
    ):
        assert workflow.count(policy_path) >= 3, (
            f"{policy_path} must appear in push paths, pull-request paths, and change routing"
        )
