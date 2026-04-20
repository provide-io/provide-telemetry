# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import re
import subprocess
import sys

import pytest

import provide.telemetry as t


def test_public_api_exports() -> None:
    assert callable(t.setup_telemetry)
    assert callable(t.get_logger)
    assert callable(t.counter)
    assert callable(t.gauge)
    assert callable(t.histogram)
    assert callable(t.trace)
    assert hasattr(t, "TelemetryMiddleware")
    assert callable(t.shutdown_telemetry)
    assert callable(t.extract_w3c_context)
    assert callable(t.set_sampling_policy)
    assert callable(t.get_health_snapshot)
    assert callable(t.update_runtime_config)
    assert callable(t.reconfigure_telemetry)
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", t.__version__) is not None


def test_public_api_version_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", _raise)
    module = importlib.reload(t)
    assert module.__version__ == "0.0.0"
    importlib.reload(module)


def test_public_api_version_type_error_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_: str) -> str:
        raise TypeError("bad metadata payload")

    monkeypatch.setattr(metadata, "version", _raise)
    module = importlib.reload(t)
    assert module.__version__ == "0.0.0"
    importlib.reload(module)


def test_import_has_no_root_logging_side_effect() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging; before=len(logging.getLogger().handlers); import provide.telemetry; "
            "after=len(logging.getLogger().handlers); print(before, after)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    before, after = proc.stdout.strip().split()
    assert before == after
