# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""An advisory exception without a live expiry and a reason is not an exception."""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.check_advisory_expiry import validate

pytestmark = pytest.mark.tooling

_TODAY = dt.date(2026, 8, 20)


def test_no_exceptions_is_clean() -> None:
    assert validate({"advisories": {"ignore": []}}, _TODAY) == []


def test_missing_advisories_table_is_clean() -> None:
    assert validate({}, _TODAY) == []


def test_live_exception_with_reason_is_clean() -> None:
    config = {
        "advisories": {
            "ignore": [
                {
                    "id": "RUSTSEC-2026-0001",
                    "reason": "no patched release yet; upstream #42",
                    "expires": "2026-10-01",
                }
            ]
        }
    }
    assert validate(config, _TODAY) == []


def test_expired_exception_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "stale", "expires": "2026-08-19"}]}}
    assert any("expired" in error for error in validate(config, _TODAY))


def test_exception_expiring_today_is_still_live() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok", "expires": "2026-08-20"}]}}
    assert validate(config, _TODAY) == []


def test_missing_expiry_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok"}]}}
    assert any("expires" in error for error in validate(config, _TODAY))


def test_missing_reason_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "expires": "2026-10-01"}]}}
    assert any("reason" in error for error in validate(config, _TODAY))


def test_blank_reason_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "   ", "expires": "2026-10-01"}]}}
    assert any("reason" in error for error in validate(config, _TODAY))


def test_expiry_further_out_than_ninety_days_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok", "expires": "2027-01-01"}]}}
    assert any("90 days" in error for error in validate(config, _TODAY))


def test_non_iso_expiry_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok", "expires": "next tuesday"}]}}
    assert any("ISO date" in error for error in validate(config, _TODAY))


def test_bare_string_entry_is_an_error() -> None:
    config = {"advisories": {"ignore": ["RUSTSEC-2026-0001"]}}
    assert any("must be a table" in error for error in validate(config, _TODAY))


def test_non_table_advisories_section_is_an_error() -> None:
    assert any("must be a table" in error for error in validate({"advisories": []}, _TODAY))


def test_non_array_ignore_is_an_error() -> None:
    config = {"advisories": {"ignore": "RUSTSEC-2026-0001"}}
    assert any("must be an array" in error for error in validate(config, _TODAY))
