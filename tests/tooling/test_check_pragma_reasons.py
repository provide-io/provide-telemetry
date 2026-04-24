# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Unit tests for ``scripts/check_pragma_reasons.py``.

The tests operate entirely on synthetic fixtures in ``tmp_path`` so they
never depend on how many pragma exemptions the real tree happens to carry
at any given moment.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_SCRIPT_PATH = Path("scripts/check_pragma_reasons.py")
if not _SCRIPT_PATH.exists():
    pytest.skip(
        "scripts/check_pragma_reasons.py not available in this test runtime",
        allow_module_level=True,
    )


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pragma_reasons", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load check_pragma_reasons script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so decorators like @dataclass can introspect
    # the module via sys.modules during class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MODULE = _load_script_module()
scan_paths = _MODULE.scan_paths
scan_file = _MODULE.scan_file
main = _MODULE.main


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_bare_pragma_is_flagged(tmp_path: Path) -> None:
    f = _write(tmp_path / "bare.py", "x = 1  # pragma: no mutate\n")
    violations = scan_paths([tmp_path], kinds=["no mutate"])
    assert [(v.path, v.lineno) for v in violations] == [(f, 1)]


def test_em_dash_reason_is_accepted(tmp_path: Path) -> None:
    _write(tmp_path / "em.py", "x = 1  # pragma: no mutate — sentinel default\n")
    assert scan_paths([tmp_path], kinds=["no mutate"]) == []


def test_double_dash_reason_is_accepted(tmp_path: Path) -> None:
    _write(tmp_path / "dd.py", "x = 1  # pragma: no mutate -- sentinel default\n")
    assert scan_paths([tmp_path], kinds=["no mutate"]) == []


def test_double_hash_reason_is_accepted(tmp_path: Path) -> None:
    _write(tmp_path / "dh.py", "x = 1  # pragma: no mutate  # sentinel default\n")
    assert scan_paths([tmp_path], kinds=["no mutate"]) == []


def test_colon_reason_is_accepted(tmp_path: Path) -> None:
    # ``# pragma: no mutate: reason`` is a tolerated degenerate form.
    _write(tmp_path / "co.py", "x = 1  # pragma: no mutate: sentinel default\n")
    assert scan_paths([tmp_path], kinds=["no mutate"]) == []


def test_reason_with_only_whitespace_is_not_accepted(tmp_path: Path) -> None:
    f = _write(tmp_path / "ws.py", "x = 1  # pragma: no mutate —   \n")
    violations = scan_paths([tmp_path], kinds=["no mutate"])
    assert [(v.path, v.lineno) for v in violations] == [(f, 1)]


def test_no_cover_is_not_checked_by_default(tmp_path: Path) -> None:
    _write(tmp_path / "nc.py", "x = 1  # pragma: no cover\n")
    assert scan_paths([tmp_path], kinds=["no mutate"]) == []


def test_no_cover_checked_when_requested(tmp_path: Path) -> None:
    f = _write(tmp_path / "nc.py", "x = 1  # pragma: no cover\n")
    violations = scan_paths([tmp_path], kinds=["no cover"])
    assert [(v.path, v.lineno, v.kind) for v in violations] == [(f, 1, "no cover")]


def test_multiple_violations_report_correct_line_numbers(tmp_path: Path) -> None:
    body = "a = 1  # pragma: no mutate — ok\nb = 2  # pragma: no mutate\nc = 3\nd = 4  # pragma: no mutate\n"
    f = _write(tmp_path / "multi.py", body)
    violations = scan_paths([tmp_path], kinds=["no mutate"])
    assert [(v.path, v.lineno) for v in violations] == [(f, 2), (f, 4)]


def test_main_returns_zero_when_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / "ok.py", "x = 1  # pragma: no mutate — reason\n")
    rc = main(["--roots", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "passed" in out


def test_main_returns_nonzero_and_prints_guidance_on_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "bad.py", "x = 1  # pragma: no mutate\n")
    rc = main(["--roots", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "failed" in out
    assert "Add a reason after the pragma" in out


def test_main_quiet_suppresses_pass_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / "ok.py", "x = 1  # pragma: no mutate — reason\n")
    rc = main(["--roots", str(tmp_path), "--quiet"])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_scan_file_handles_missing_path_gracefully(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.py"
    assert scan_file(missing, ["no mutate"]) == []
