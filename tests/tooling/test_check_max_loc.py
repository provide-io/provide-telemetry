# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/check_max_loc.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/check_max_loc.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_max_loc", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load check_max_loc script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


find_loc_offenders = _load_script_module().find_loc_offenders


def test_find_loc_offenders_flags_files_over_limit(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    ok_file = src / "ok.py"
    bad_file = src / "bad.py"
    ok_file.write_text("x = 1\n" * 10, encoding="utf-8")
    bad_file.write_text("x = 1\n" * 12, encoding="utf-8")

    offenders = find_loc_offenders([src], max_lines=10)
    assert offenders == [(bad_file, 12)]


def test_find_loc_offenders_skips_excluded_dirs(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    excluded = root / "mutants"
    excluded.mkdir()
    (excluded / "too_long.py").write_text("x = 1\n" * 1000, encoding="utf-8")

    offenders = find_loc_offenders([root], max_lines=10)
    assert offenders == []
