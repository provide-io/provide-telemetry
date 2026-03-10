# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling
_SCRIPT_PATH = Path("scripts/check_licenses.py")
if not _SCRIPT_PATH.exists():
    pytest.skip("scripts/check_licenses.py not available in this test runtime", allow_module_level=True)


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_licenses", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        msg = "unable to load check_licenses script module"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_script_module()


def test_license_allowed_exact_string() -> None:
    assert checker._license_allowed("Apache-2.0")


def test_license_allowed_or_expression() -> None:
    assert checker._license_allowed("Apache-2.0 OR BSD-3-Clause")


def test_license_rejects_unknown_expression_token() -> None:
    assert not checker._license_allowed("Apache-2.0 OR GPL-3.0-only")
