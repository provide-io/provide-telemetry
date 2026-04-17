# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_go_readme_mentions_runtime_introspection() -> None:
    readme = (REPO_ROOT / "go" / "README.md").read_text(encoding="utf-8")

    assert "GetRuntimeConfig" in readme
    assert "GetRuntimeStatus" in readme


def test_rust_readme_mentions_runtime_introspection() -> None:
    readme = (REPO_ROOT / "rust" / "README.md").read_text(encoding="utf-8")

    assert "get_runtime_config" in readme
    assert "get_runtime_status" in readme


def test_typescript_readme_mentions_runtime_introspection() -> None:
    readme = (REPO_ROOT / "typescript" / "README.md").read_text(encoding="utf-8")

    assert "getRuntimeConfig" in readme
    assert "getRuntimeStatus" in readme
