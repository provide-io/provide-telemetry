# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for error fingerprinting processor."""

from __future__ import annotations

import hashlib
import sys
import traceback
from typing import Any
from unittest.mock import Mock, patch

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

    def test_adds_fingerprint_on_exception_instance(self) -> None:
        """exc_info can be a direct Exception object (structlog pattern)."""
        try:
            raise ValueError("direct exception")
        except ValueError as exc:
            event: dict[str, Any] = {"event": "error", "exc_info": exc}
            result = add_error_fingerprint(None, "", event)
            assert "error_fingerprint" in result
            assert len(result["error_fingerprint"]) == 12


class TestComputeErrorFingerprintExact:
    def test_exact_hash_no_tb(self) -> None:
        """Kills: missing .lower() on exc_type, [:12] → [:11], or any encoding mutation."""
        expected = hashlib.sha256(b"valueerror").hexdigest()[:12]
        assert _compute_error_fingerprint("ValueError", None) == expected

    def test_case_folds_exc_type(self) -> None:
        """Kills: .lower() removed from exc_type."""
        lower = _compute_error_fingerprint("valueerror", None)
        upper = _compute_error_fingerprint("VALUEERROR", None)
        mixed = _compute_error_fingerprint("ValueError", None)
        assert lower == upper == mixed

    def test_colon_separator_between_type_and_frame(self) -> None:
        """Kills: ':'.join(parts) → ''.join(parts) or other separator."""
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()

        # Compute expected hash using same frame-extraction logic but explicit ':' sep
        frames = traceback.extract_tb(tb)[-3:]
        parts = ["valueerror"]
        for frame in frames:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts.append(f"{basename}:{func}")
        expected_colon = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]
        expected_no_sep = hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:12]

        result = _compute_error_fingerprint("ValueError", tb)
        assert result == expected_colon
        assert result != expected_no_sep

    def test_basename_colon_func_frame_format(self) -> None:
        """Kills: f'{basename}:{func}' → f'{basename}.{func}' or f'{basename} {func}'."""
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()

        frames = traceback.extract_tb(tb)[-3:]
        frame = frames[-1]
        leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
        basename = leaf.rsplit(".", 1)[0].lower()
        func = (frame.name or "").lower()

        # Both basename and func must be non-empty for this to be meaningful
        assert basename, "test setup: basename should not be empty"
        assert func, "test setup: func name should not be empty"

        expected = hashlib.sha256(f"valueerror:{basename}:{func}".encode()).hexdigest()[:12]
        expected_dot = hashlib.sha256(f"valueerror:{basename}.{func}".encode()).hexdigest()[:12]

        assert _compute_error_fingerprint("ValueError", tb) == expected
        assert _compute_error_fingerprint("ValueError", tb) != expected_dot

    def test_uses_last_3_frames_from_longer_stack(self) -> None:
        """Kills: traceback.extract_tb(tb)[-3:] → extract_tb(tb) (all frames)."""

        def inner() -> None:
            raise ValueError("test")

        def middle() -> None:
            inner()

        def outer() -> None:
            middle()

        try:
            outer()
        except ValueError:
            _, _, tb = sys.exc_info()

        all_frames = traceback.extract_tb(tb)
        assert len(all_frames) >= 4, "test requires >=4 frames in stack"

        # With [-3:], only last 3 frames contribute
        last3 = all_frames[-3:]
        parts_3 = ["valueerror"]
        for frame in last3:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts_3.append(f"{basename}:{func}")
        expected = hashlib.sha256(":".join(parts_3).encode("utf-8")).hexdigest()[:12]

        # All frames would produce a different hash
        all_parts = ["valueerror"]
        for frame in all_frames:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            all_parts.append(f"{basename}:{func}")
        full_hash = hashlib.sha256(":".join(all_parts).encode("utf-8")).hexdigest()[:12]

        result = _compute_error_fingerprint("ValueError", tb)
        assert result == expected
        assert result != full_hash

    def test_case_folds_func_and_basename_from_tb(self) -> None:
        """Kills: .lower() removed from basename or func."""
        try:
            raise ValueError("test")
        except ValueError:
            _, _, tb = sys.exc_info()

        result = _compute_error_fingerprint("ValueError", tb)
        result_upper = _compute_error_fingerprint("VALUEERROR", tb)
        assert result == result_upper


class TestComputeErrorFingerprintFrameExtraction:
    """Kills mutations in the filename/funcname extraction logic."""

    def test_windows_path_backslashes_normalized_to_forward(self) -> None:
        """Kills: replace('\\\\', '/') string literal mutations (mutmut_17, mutmut_18).

        Backslashes in Windows paths must be normalized to forward slashes before
        rsplit('/') can extract the basename. If either string literal is mutated,
        the backslash is not removed and rsplit('/') finds no separator, leaving
        the full Windows path as the 'leaf' (wrong basename, different hash).
        """
        with patch("undef.telemetry.logger.processors.traceback.extract_tb") as mock_extract:
            mock_extract.return_value = [traceback.FrameSummary("C:\\Users\\user\\project\\app.py", 1, "my_func")]
            result = _compute_error_fingerprint("ValueError", "fake_tb")  # type: ignore[arg-type]
        expected = hashlib.sha256(b"valueerror:app:my_func").hexdigest()[:12]
        assert result == expected

    def test_basename_uses_last_dot_to_strip_extension(self) -> None:
        """Kills: rsplit('.', 1) mutations — split('.', 1), rsplit('.', 2), rsplit('.', ) (mutmut_28/29/31).

        For a filename like 'module.test.py' with multiple dots:
        - rsplit('.', 1)[0] = 'module.test'  (correct: strip only extension)
        - split('.', 1)[0]  = 'module'       (wrong: split from left)
        - rsplit('.', 2)[0] = 'module'       (wrong: strip two extensions)
        - rsplit('.', )[0]  = 'module'       (wrong: strip all after first dot)
        """
        with patch("undef.telemetry.logger.processors.traceback.extract_tb") as mock_extract:
            mock_extract.return_value = [traceback.FrameSummary("/path/to/module.test.py", 1, "helper")]
            result = _compute_error_fingerprint("ValueError", "fake_tb")  # type: ignore[arg-type]
        expected = hashlib.sha256(b"valueerror:module.test:helper").hexdigest()[:12]
        assert result == expected

    def test_anonymous_function_uses_empty_string_not_sentinel(self) -> None:
        """Kills: (frame.name or '') → (frame.name or 'XXXX') (mutmut_36).

        When frame.name is falsy (empty string or None), the function component
        must be '' (empty), not a sentinel string. Changing '' to 'XXXX' would
        produce a different hash.
        """
        with patch("undef.telemetry.logger.processors.traceback.extract_tb") as mock_extract:
            frame = Mock()
            frame.filename = "/path/to/app.py"
            frame.name = ""  # falsy — triggers the `or` branch
            mock_extract.return_value = [frame]
            result = _compute_error_fingerprint("ValueError", "fake_tb")  # type: ignore[arg-type]
        expected = hashlib.sha256(b"valueerror:app:").hexdigest()[:12]
        assert result == expected
