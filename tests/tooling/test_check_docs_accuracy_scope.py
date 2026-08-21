# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Every shipped README must be inside the documentation checker's scope."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_SCRIPT_PATH = Path("scripts/check_docs_accuracy.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/check_docs_accuracy.py not available", allow_module_level=True)

_REPO_ROOT = _SCRIPT_PATH.resolve().parent.parent

_SHIPPED_DOCS = (
    "README.md",
    "go/README.md",
    "rust/README.md",
    "typescript/README.md",
    "csharp/README.md",
    "examples/README.md",
    "CONTRIBUTING.md",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_docs_accuracy", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", _SHIPPED_DOCS)
def test_shipped_document_is_checked(relative: str) -> None:
    target = _REPO_ROOT / relative
    if not target.is_file():
        pytest.skip(f"{relative} does not exist in this repository")
    module = _load()
    checked = {path.resolve() for path in module._iter_markdown_files(_REPO_ROOT)}
    assert target.resolve() in checked, f"{relative} is shipped but not checked"
