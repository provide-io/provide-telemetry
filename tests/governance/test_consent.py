# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for consent-aware collection."""

from __future__ import annotations

import pytest

from provide.telemetry.consent import ConsentLevel, get_consent_level, set_consent_level, should_allow


@pytest.fixture(autouse=True)
def _reset() -> None:
    from provide.telemetry.consent import _reset_consent_for_tests

    _reset_consent_for_tests()


def test_default_consent_is_full() -> None:
    assert get_consent_level() == ConsentLevel.FULL


def test_full_allows_all_signals() -> None:
    set_consent_level(ConsentLevel.FULL)
    assert should_allow("logs", "DEBUG") is True
    assert should_allow("traces") is True
    assert should_allow("metrics") is True
    assert should_allow("context") is True


def test_none_blocks_all_signals() -> None:
    set_consent_level(ConsentLevel.NONE)
    assert should_allow("logs", "ERROR") is False
    assert should_allow("traces") is False
    assert should_allow("metrics") is False
    assert should_allow("context") is False


def test_functional_allows_warn_and_above_logs() -> None:
    set_consent_level(ConsentLevel.FUNCTIONAL)
    assert should_allow("logs", "DEBUG") is False
    assert should_allow("logs", "INFO") is False
    assert should_allow("logs", "WARNING") is True
    assert should_allow("logs", "ERROR") is True
    assert should_allow("traces") is True
    assert should_allow("metrics") is True
    assert should_allow("context") is False


def test_minimal_allows_errors_and_health_only() -> None:
    set_consent_level(ConsentLevel.MINIMAL)
    assert should_allow("logs", "WARNING") is False
    assert should_allow("logs", "ERROR") is True
    assert should_allow("traces") is False
    assert should_allow("metrics") is False
    assert should_allow("context") is False


def test_functional_log_level_none() -> None:
    set_consent_level(ConsentLevel.FUNCTIONAL)
    # None log_level should be treated as empty string → order 0 < WARNING → False
    assert should_allow("logs", None) is False


def test_minimal_log_level_none() -> None:
    set_consent_level(ConsentLevel.MINIMAL)
    # None log_level → order 0 < ERROR → False
    assert should_allow("logs", None) is False


def test_set_consent_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "MINIMAL")
    from provide.telemetry.consent import _load_consent_from_env

    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.MINIMAL


def test_load_consent_from_env_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
    from provide.telemetry.consent import _load_consent_from_env

    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.FULL  # unchanged


def test_load_consent_from_env_functional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "FUNCTIONAL")
    from provide.telemetry.consent import _load_consent_from_env

    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.FUNCTIONAL


def test_load_consent_from_env_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "NONE")
    from provide.telemetry.consent import _load_consent_from_env

    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.NONE


def test_load_consent_from_env_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "FULL")
    from provide.telemetry.consent import _load_consent_from_env

    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.FULL


def test_consent_enum_values() -> None:
    assert ConsentLevel.FULL.value == "FULL"
    assert ConsentLevel.FUNCTIONAL.value == "FUNCTIONAL"
    assert ConsentLevel.MINIMAL.value == "MINIMAL"
    assert ConsentLevel.NONE.value == "NONE"


def test_functional_unknown_signal_allowed() -> None:
    set_consent_level(ConsentLevel.FUNCTIONAL)
    # Any signal that is not "logs" or "context" passes at FUNCTIONAL
    assert should_allow("traces") is True
    assert should_allow("metrics") is True
    assert should_allow("custom_signal") is True


def test_minimal_unknown_signal_blocked() -> None:
    set_consent_level(ConsentLevel.MINIMAL)
    # Any signal that is not "logs" is blocked at MINIMAL
    assert should_allow("custom_signal") is False


def test_load_consent_from_env_unset_defaults_to_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PROVIDE_CONSENT_LEVEL is unset, _load_consent_from_env defaults to FULL."""
    from provide.telemetry.consent import _load_consent_from_env

    monkeypatch.delenv("PROVIDE_CONSENT_LEVEL", raising=False)
    # Set level to something other than FULL first
    set_consent_level(ConsentLevel.MINIMAL)
    _load_consent_from_env()
    assert get_consent_level() == ConsentLevel.FULL
