# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/check_event_literals.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/check_event_literals.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_event_literals", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load check_event_literals script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_module = _load_script_module()
find_event_literal_violations = _module.find_event_literal_violations


def test_event_literal_check_accepts_valid_literal(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    file_path = root / "ok.py"
    file_path.write_text(
        "def run(log):\n    log.info('auth.login.success', request_id='r1')\n",
        encoding="utf-8",
    )

    violations = find_event_literal_violations([root], set())
    assert violations == []


def test_event_literal_check_flags_invalid_literal(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    file_path = root / "bad.py"
    file_path.write_text(
        "def run(log):\n    log.info('auth.login.password.failed')\n",
        encoding="utf-8",
    )

    violations = find_event_literal_violations([root], set())
    assert len(violations) == 1
    assert "invalid event literal" in violations[0]
    assert "auth.login.password.failed" in violations[0]


def test_event_literal_check_ignores_non_literal_dynamic_event(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    file_path = root / "dynamic.py"
    file_path.write_text(
        "from provide.telemetry import event_name\ndef run(log):\n    log.info(event_name('auth', 'login', 'success'))\n",
        encoding="utf-8",
    )

    violations = find_event_literal_violations([root], set())
    assert violations == []
