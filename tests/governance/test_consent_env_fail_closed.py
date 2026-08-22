# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""PROVIDE_CONSENT_LEVEL fail-closed semantics.

An unset or blank variable is a no-op. A recognised value is applied. A set,
non-empty, unrecognised value is an opt-out the operator misspelled, so it
fails closed to NONE and warns once per process, naming the bad value.
"""

from __future__ import annotations

import warnings

import pytest

from provide.telemetry.consent import (
    ConsentLevel,
    _load_consent_from_env,
    _reset_consent_for_tests,
    get_consent_level,
    set_consent_level,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    _reset_consent_for_tests()


def _load_expecting_no_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _load_consent_from_env()


def test_blank_value_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose files set VAR= constantly; blank is 'unset', not 'invalid'."""
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "")
    set_consent_level(ConsentLevel.MINIMAL)
    _load_expecting_no_warning()
    assert get_consent_level() is ConsentLevel.MINIMAL


def test_whitespace_only_value_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "  \t ")
    set_consent_level(ConsentLevel.MINIMAL)
    _load_expecting_no_warning()
    assert get_consent_level() is ConsentLevel.MINIMAL


def test_recognised_value_does_not_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", " functional ")
    _load_expecting_no_warning()
    assert get_consent_level() is ConsentLevel.FUNCTIONAL


def test_invalid_value_overrides_a_programmatic_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed means NONE even when code had chosen a more permissive level."""
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
    set_consent_level(ConsentLevel.FULL)
    with pytest.warns(RuntimeWarning):
        _load_consent_from_env()
    assert get_consent_level() is ConsentLevel.NONE


def test_invalid_value_warning_names_the_raw_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "  noen ")
    with pytest.warns(RuntimeWarning) as caught:
        _load_consent_from_env()
    assert len(caught) == 1
    assert str(caught[0].message) == (
        "PROVIDE_CONSENT_LEVEL='  noen ' is not one of FULL, FUNCTIONAL, MINIMAL, NONE; "
        "consent set to NONE (fail-closed)"
    )
    assert get_consent_level() is ConsentLevel.NONE


def test_invalid_value_warns_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setup and the lazy logger both call the loader; the operator hears about it once."""
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
    with pytest.warns(RuntimeWarning) as caught:
        _load_consent_from_env()
        _load_consent_from_env()
    assert len(caught) == 1
    assert get_consent_level() is ConsentLevel.NONE


def test_second_invalid_load_still_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence after the first warning must not mean the level stops being applied."""
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
    with pytest.warns(RuntimeWarning):
        _load_consent_from_env()
    set_consent_level(ConsentLevel.FULL)
    _load_expecting_no_warning()
    assert get_consent_level() is ConsentLevel.NONE


def test_reset_rearms_the_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
    with pytest.warns(RuntimeWarning):
        _load_consent_from_env()
    _reset_consent_for_tests()
    with pytest.warns(RuntimeWarning):
        _load_consent_from_env()


def test_setup_telemetry_fails_closed_on_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.setup import setup_telemetry

    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
    with pytest.warns(RuntimeWarning):
        setup_telemetry()
    assert get_consent_level() is ConsentLevel.NONE


def test_lazy_get_logger_fails_closed_on_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.logger.core import _reset_logging_for_tests, get_logger

    _reset_logging_for_tests()
    monkeypatch.setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
    with pytest.warns(RuntimeWarning):
        get_logger("consent.lazy.invalid")
    assert get_consent_level() is ConsentLevel.NONE
