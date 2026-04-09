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
    assert "working-directory: rust" in workflow
