# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for pyproject.toml tooling configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_ty_python_version_matches_min_supported_python() -> None:
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))

    requires_python = pyproject["project"]["requires-python"]
    ty_python_version = pyproject["tool"]["ty"]["environment"]["python-version"]

    assert requires_python.startswith(">=")
    assert ty_python_version == requires_python.removeprefix(">=")
