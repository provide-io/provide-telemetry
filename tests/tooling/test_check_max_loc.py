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


_MODULE = _load_script_module()
find_loc_offenders = _MODULE.find_loc_offenders
DEFAULT_EXTENSIONS = _MODULE.DEFAULT_EXTENSIONS


def test_find_loc_offenders_flags_files_over_limit(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    ok_file = src / "ok.py"
    bad_file = src / "bad.py"
    ok_file.write_text("x = 1\n" * 10, encoding="utf-8")
    bad_file.write_text("x = 1\n" * 12, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [src], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    assert offenders == [(bad_file, 12)]
    assert grandfathered == []


def test_find_loc_offenders_skips_excluded_dirs(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    excluded = root / "mutants"
    excluded.mkdir()
    (excluded / "too_long.py").write_text("x = 1\n" * 1000, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    assert offenders == []
    assert grandfathered == []


def test_find_loc_offenders_scans_all_polyglot_extensions(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.ts").write_text("// line\n" * 600, encoding="utf-8")
    (src / "big.go").write_text("// line\n" * 600, encoding="utf-8")
    (src / "big.rs").write_text("// line\n" * 600, encoding="utf-8")
    (src / "big.py").write_text("# line\n" * 600, encoding="utf-8")

    offenders, _ = find_loc_offenders(
        [src], max_lines=500, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    paths = sorted(p.name for p, _ in offenders)
    assert paths == ["big.go", "big.py", "big.rs", "big.ts"]


def test_allowlist_grandfathers_existing_violators_under_ceiling(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    grand = src / "large.go"
    grand.write_text("// line\n" * 700, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [src],
        max_lines=500,
        extensions=DEFAULT_EXTENSIONS,
        allowlist={"src/large.go": 800},
        repo_root=tmp_path,
    )
    assert offenders == []
    assert grandfathered == [(grand, 700)]


def test_allowlist_does_not_let_files_grow_past_ceiling(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    grand = src / "large.go"
    grand.write_text("// line\n" * 700, encoding="utf-8")

    offenders, grandfathered = find_loc_offenders(
        [src],
        max_lines=500,
        extensions=DEFAULT_EXTENSIONS,
        allowlist={"src/large.go": 600},  # ceiling lower than current size
        repo_root=tmp_path,
    )
    assert offenders == [(grand, 700)]
    assert grandfathered == []


def test_node_modules_and_target_excluded(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "huge.ts").write_text("// line\n" * 5000, encoding="utf-8")
    (root / "target").mkdir()
    (root / "target" / "huge.rs").write_text("// line\n" * 5000, encoding="utf-8")

    offenders, _ = find_loc_offenders(
        [root], max_lines=10, extensions=DEFAULT_EXTENSIONS, allowlist={}, repo_root=tmp_path
    )
    assert offenders == []
