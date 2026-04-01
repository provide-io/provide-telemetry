# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/check_docs_accuracy.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/check_docs_accuracy.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_docs_accuracy", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load check_docs_accuracy script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_script_module()


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_check_docs_passes_for_valid_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_file(
        tmp_path / "README.md",
        "# Project\n\nSee [Architecture](docs/ARCHITECTURE.md#architecture).\n",
    )
    _write_file(
        tmp_path / "docs/ARCHITECTURE.md",
        (
            "# Architecture\n\n"
            "## Component Flow\n\n"
            "```mermaid\nflowchart TD\nA-->B\n```\n\n"
            "## Request Lifecycle\n\n"
            "```mermaid\nsequenceDiagram\nA->>B: go\n```\n\n"
            "## Processor Pipeline\n\n"
            "```mermaid\nflowchart LR\nA-->B\n```\n\n"
            "## State Machine\n\n"
            "```mermaid\nstateDiagram-v2\nA-->B\n```\n\n"
            "## Resilience Flow\n\n"
            "```mermaid\nflowchart TD\nA-->B\n```\n"
        ),
    )
    _write_file(tmp_path / "examples/README.md", "# Examples\n\nSee [Main](../README.md).\n")
    monkeypatch.chdir(tmp_path)
    assert checker.check_docs(tmp_path) == []


def test_check_docs_flags_missing_anchor(tmp_path: Path) -> None:
    _write_file(tmp_path / "README.md", "# Project\n\nSee [Arch](docs/ARCHITECTURE.md#missing).\n")
    _write_file(
        tmp_path / "docs/ARCHITECTURE.md",
        "# Architecture\n\n```mermaid\nflowchart TD\nA-->B\n```\n\n```mermaid\nsequenceDiagram\nA->>B: x\n```\n",
    )
    violations = checker.check_docs(tmp_path)
    assert any("missing anchor #missing" in v for v in violations)


def test_check_docs_flags_inaccurate_fallback_phrase(tmp_path: Path) -> None:
    _write_file(tmp_path / "README.md", "# Project\n\nno-op tracing/metrics continue without exceptions\n")
    _write_file(
        tmp_path / "docs/ARCHITECTURE.md",
        "# Architecture\n\n```mermaid\nflowchart TD\nA-->B\n```\n\n```mermaid\nsequenceDiagram\nA->>B: x\n```\n",
    )
    _write_file(tmp_path / "examples/README.md", "# Examples\n")
    violations = checker.check_docs(tmp_path)
    assert any("fallback wording is inaccurate" in v for v in violations)


def test_check_docs_flags_mutation_command_without_threshold(tmp_path: Path) -> None:
    _write_file(
        tmp_path / "README.md", "# Project\n\nuv run python scripts/run_mutation_gate.py --python-version 3.11\n"
    )
    _write_file(
        tmp_path / "docs/ARCHITECTURE.md",
        "# Architecture\n\n```mermaid\nflowchart TD\nA-->B\n```\n\n```mermaid\nsequenceDiagram\nA->>B: x\n```\n",
    )
    _write_file(tmp_path / "examples/README.md", "# Examples\n")
    violations = checker.check_docs(tmp_path)
    assert any("--min-mutation-score 100" in v for v in violations)
