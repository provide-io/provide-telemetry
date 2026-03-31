# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for error fingerprinting processor."""

from __future__ import annotations

import sys
from typing import Any

from undef.telemetry.logger.processors import _compute_error_fingerprint, add_error_fingerprint


class TestComputeErrorFingerprint:
    def test_produces_12_char_hex(self) -> None:
        result = _compute_error_fingerprint("ValueError", None)
        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        a = _compute_error_fingerprint("ValueError", None)
        b = _compute_error_fingerprint("ValueError", None)
        assert a == b

    def test_different_types_different_fingerprint(self) -> None:
        a = _compute_error_fingerprint("ValueError", None)
        b = _compute_error_fingerprint("TypeError", None)
        assert a != b

    def test_with_traceback(self) -> None:
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()
            result = _compute_error_fingerprint("ValueError", tb)
            assert len(result) == 12

    def test_same_call_path_same_fingerprint(self) -> None:
        """Same exception from same call site = same fingerprint."""
        fps: list[str] = []
        for _ in range(2):
            try:
                raise ValueError("test")
            except ValueError:
                _, _, tb = sys.exc_info()
                fps.append(_compute_error_fingerprint("ValueError", tb))
        assert fps[0] == fps[1]


class TestAddErrorFingerprint:
    def test_adds_fingerprint_on_exc_info_tuple(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
            event: dict[str, Any] = {"event": "error", "exc_info": exc_info}
            result = add_error_fingerprint(None, "", event)
            assert "error_fingerprint" in result
            assert len(result["error_fingerprint"]) == 12

    def test_adds_fingerprint_on_exc_info_true(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            event: dict[str, Any] = {"event": "error", "exc_info": True}
            result = add_error_fingerprint(None, "", event)
            assert "error_fingerprint" in result

    def test_adds_fingerprint_on_exc_name(self) -> None:
        event: dict[str, Any] = {"event": "error", "exc_name": "TimeoutError"}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result
        assert len(result["error_fingerprint"]) == 12

    def test_adds_fingerprint_on_exception_field(self) -> None:
        event: dict[str, Any] = {"event": "error", "exception": "ConnectionError"}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" in result

    def test_no_fingerprint_on_normal_event(self) -> None:
        event: dict[str, Any] = {"event": "app.start.ok"}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_no_fingerprint_on_exc_info_none(self) -> None:
        event: dict[str, Any] = {"event": "info", "exc_info": None}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result

    def test_no_fingerprint_on_exc_info_false(self) -> None:
        event: dict[str, Any] = {"event": "info", "exc_info": False}
        result = add_error_fingerprint(None, "", event)
        assert "error_fingerprint" not in result
