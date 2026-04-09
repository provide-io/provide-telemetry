# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for custom secret pattern registration API."""

from __future__ import annotations

import re
import threading
from typing import Any

import pytest

from provide.telemetry import pii as pii_mod
from provide.telemetry.pii import (
    _SECRET_PATTERNS,
    _detect_secret_in_value,
    get_secret_patterns,
    register_secret_pattern,
    sanitize_payload,
)


@pytest.fixture(autouse=True)
def _reset_rules() -> None:
    pii_mod.reset_pii_rules_for_tests()


# ---------------------------------------------------------------------------
# register_secret_pattern
# ---------------------------------------------------------------------------


class TestRegisterSecretPattern:
    """Tests for register_secret_pattern."""

    def test_custom_pattern_detects_secret(self) -> None:
        """A registered pattern causes _detect_secret_in_value to match."""
        pattern = re.compile(r"CUSTOM_[A-Z]{20,}")
        register_secret_pattern("custom_key", pattern)
        assert _detect_secret_in_value("CUSTOM_ABCDEFGHIJKLMNOPQRST") is True

    def test_custom_pattern_used_in_sanitize_payload(self) -> None:
        """Custom patterns redact matching values in sanitize_payload."""
        pattern = re.compile(r"MYTOKEN_[A-Za-z0-9]{20,}")
        register_secret_pattern("my_token", pattern)
        payload: dict[str, Any] = {"data": "MYTOKEN_abcdefghij1234567890"}
        result = sanitize_payload(payload, enabled=True)
        assert result["data"] == "***"

    def test_same_name_replaces_pattern(self) -> None:
        """Registering the same name replaces the previous pattern."""
        pat1 = re.compile(r"FIRST_[A-Z]{20,}")
        pat2 = re.compile(r"SECOND_[A-Z]{20,}")
        register_secret_pattern("dup", pat1)
        register_secret_pattern("dup", pat2)
        patterns = get_secret_patterns()
        custom = [(n, p) for n, p in patterns if n == "dup"]
        assert len(custom) == 1
        assert custom[0][1] is pat2

    def test_replace_does_not_add_duplicate(self) -> None:
        """After replacement, total custom count stays at 1."""
        pat1 = re.compile(r"A{20,}")
        pat2 = re.compile(r"B{20,}")
        register_secret_pattern("x", pat1)
        register_secret_pattern("x", pat2)
        all_patterns = get_secret_patterns()
        # built-in count + 1 custom
        assert len(all_patterns) == len(_SECRET_PATTERNS) + 1

    def test_different_names_accumulate(self) -> None:
        """Different names produce separate entries."""
        register_secret_pattern("a", re.compile(r"A{20,}"))
        register_secret_pattern("b", re.compile(r"B{20,}"))
        all_patterns = get_secret_patterns()
        assert len(all_patterns) == len(_SECRET_PATTERNS) + 2


# ---------------------------------------------------------------------------
# get_secret_patterns
# ---------------------------------------------------------------------------


class TestGetSecretPatterns:
    """Tests for get_secret_patterns."""

    def test_returns_builtins_when_no_custom(self) -> None:
        """With no custom patterns, returns only built-in patterns."""
        patterns = get_secret_patterns()
        assert patterns == _SECRET_PATTERNS

    def test_returns_builtins_and_custom(self) -> None:
        """Returns both built-in and custom patterns."""
        register_secret_pattern("extra", re.compile(r"EXTRA_[A-Z]{20,}"))
        patterns = get_secret_patterns()
        assert len(patterns) == len(_SECRET_PATTERNS) + 1
        names = [n for n, _p in patterns]
        assert "extra" in names

    def test_returns_tuple(self) -> None:
        """Return type is a tuple (immutable snapshot)."""
        result = get_secret_patterns()
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# reset clears custom patterns
# ---------------------------------------------------------------------------


class TestResetClearsCustomPatterns:
    """Tests that reset_pii_rules_for_tests clears custom patterns."""

    def test_reset_clears_custom_patterns(self) -> None:
        register_secret_pattern("tmp", re.compile(r"TMP_[A-Z]{20,}"))
        assert len(get_secret_patterns()) == len(_SECRET_PATTERNS) + 1
        pii_mod.reset_pii_rules_for_tests()
        assert get_secret_patterns() == _SECRET_PATTERNS

    def test_reset_does_not_remove_builtins(self) -> None:
        pii_mod.reset_pii_rules_for_tests()
        assert len(get_secret_patterns()) == len(_SECRET_PATTERNS)


# ---------------------------------------------------------------------------
# _MIN_SECRET_LENGTH applies to custom patterns
# ---------------------------------------------------------------------------


class TestMinSecretLengthAppliesToCustom:
    """Custom patterns still respect the _MIN_SECRET_LENGTH guard."""

    def test_short_value_not_matched_by_custom_pattern(self) -> None:
        """Values shorter than _MIN_SECRET_LENGTH are skipped even for custom patterns."""
        # Pattern would match "SHORT" but value is too short (< 20 chars)
        register_secret_pattern("short", re.compile(r"SHORT"))
        assert _detect_secret_in_value("SHORT") is False

    def test_long_value_matched_by_custom_pattern(self) -> None:
        """Values at or above _MIN_SECRET_LENGTH are checked against custom patterns."""
        register_secret_pattern("long", re.compile(r"LONG"))
        long_value = "LONG" + "x" * 20
        assert _detect_secret_in_value(long_value) is True

    def test_long_value_not_matched_by_any_pattern(self) -> None:
        """A long value that matches neither built-in nor custom patterns returns False."""
        register_secret_pattern("nope", re.compile(r"WILLNOTMATCH"))
        # Long enough to pass length check, but matches no pattern
        long_value = "just some ordinary text that is long enough"
        assert _detect_secret_in_value(long_value) is False


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestSecretPatternThreadSafety:
    """Concurrent registration and sanitization must not crash."""

    def test_concurrent_register_and_detect(self) -> None:
        """Register patterns from multiple threads while sanitizing."""
        errors: list[Exception] = []
        barrier = threading.Barrier(4)

        def register_patterns(thread_id: int) -> None:
            try:
                barrier.wait(timeout=5)
                for i in range(50):
                    name = f"thread_{thread_id}_pat_{i}"
                    register_secret_pattern(name, re.compile(rf"T{thread_id}P{i}_[A-Z]{{20,}}"))
            except Exception as exc:
                errors.append(exc)

        def sanitize_loop() -> None:
            try:
                barrier.wait(timeout=5)
                for _ in range(50):
                    sanitize_payload(
                        {"value": "T0P0_ABCDEFGHIJKLMNOPQRST"},
                        enabled=True,
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_patterns, args=(0,)),
            threading.Thread(target=register_patterns, args=(1,)),
            threading.Thread(target=register_patterns, args=(2,)),
            threading.Thread(target=sanitize_loop),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors, f"Thread errors: {errors}"
