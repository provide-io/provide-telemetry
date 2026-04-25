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

_SPDX_PATH = Path("scripts/spdx_headers.py")
_NORMALIZE_PATH = Path("scripts/normalize_spdx_headers.py")
_CHECK_PATH = Path("scripts/check_spdx_headers.py")
if not (_SPDX_PATH.exists() and _NORMALIZE_PATH.exists() and _CHECK_PATH.exists()):
    pytest.skip("SPDX tooling scripts not available in this test runtime", allow_module_level=True)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"unable to load module from {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SPDX_MODULE = _load(_SPDX_PATH, "spdx_headers")
_NORMALIZE_MODULE = _load(_NORMALIZE_PATH, "normalize_spdx_headers")
_CHECK_MODULE = _load(_CHECK_PATH, "check_spdx_headers")


def test_normalize_python_text_without_shebang() -> None:
    text = (
        "# SPDX-License-Identifier" + ": Apache-2.0\n"
        "# Copyright (C) 2026 provide.io llc\n"
        "# This file is part of Provide Telemetry.\n\n"
        "x = 1\n"
    )
    normalized = _SPDX_MODULE.normalize_python_text(text)
    assert normalized.startswith("".join(_SPDX_MODULE.CANONICAL_BLOCK))
    assert normalized.endswith("x = 1\n")


def test_normalize_python_text_with_shebang() -> None:
    text = (
        "#!/usr/bin/env python3\n"
        "# SPDX-License-Identifier" + ": Apache-2.0\n"
        "# Copyright (C) 2026 provide.io llc\n\n"
        "print('ok')\n"
    )
    normalized = _SPDX_MODULE.normalize_python_text(text)
    assert normalized.startswith("#!/usr/bin/env python3\n")
    assert "".join(_SPDX_MODULE.CANONICAL_BLOCK) in normalized
    assert normalized.endswith("print('ok')\n")


def test_has_canonical_header_roundtrip() -> None:
    canonical = "".join(_SPDX_MODULE.CANONICAL_BLOCK) + "value = 2\n"
    assert _SPDX_MODULE.has_canonical_header(canonical) is True
    assert _SPDX_MODULE.has_canonical_header("value = 2\n") is False


def test_find_python_files_skips_excluded_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / ".provide" / "act-actions").mkdir(parents=True)
    (tmp_path / ".provide" / "act-actions" / "third_party.py").write_text("x = 3\n", encoding="utf-8")
    found = _SPDX_MODULE.find_python_files(tmp_path)
    assert found == [tmp_path / "src" / "a.py"]


def test_normalize_headers_rewrites_files(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("print('hello')\n", encoding="utf-8")
    changed = _NORMALIZE_MODULE.normalize_headers(tmp_path)
    assert changed == [path]
    assert _SPDX_MODULE.has_canonical_header(path.read_text(encoding="utf-8"))


def test_find_noncompliant_files(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    bad = tmp_path / "bad.py"
    good.write_text("".join(_SPDX_MODULE.CANONICAL_BLOCK) + "x = 1\n", encoding="utf-8")
    bad.write_text("x = 1\n", encoding="utf-8")
    missing, invalid = _CHECK_MODULE.find_noncompliant_files(tmp_path)
    assert missing == [bad]
    assert invalid == []
