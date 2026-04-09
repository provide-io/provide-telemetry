# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_CARGO = REPO_ROOT / "rust" / "Cargo.toml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def test_rust_crate_is_publishable() -> None:
    cargo = RUST_CARGO.read_text(encoding="utf-8")

    assert "publish = false" not in cargo


def test_release_workflow_includes_rust_build_and_publish_jobs() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "build-rust:" in workflow
    assert "publish-rust:" in workflow
    assert "cargo package --locked" in workflow
    assert "cargo publish --locked" in workflow
