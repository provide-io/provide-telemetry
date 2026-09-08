# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""``service``/``env``/``version`` earn their place only where something reads them.

A JSON record is ingested: the identity fields are how a backend tells one
service's lines from another's, so they belong on every one. A console line is
read by a person at a terminal who already knows which process they started,
and three constant fields repeated on every line push the message itself off
the right-hand side.

They stay ``optional_fields`` in ``spec/behavioral_fixtures.yaml`` and no
fixture pins them for a console renderer, so this is a Python-side rendering
choice rather than a change to the wire contract.
"""

from __future__ import annotations

from typing import Any

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.processors import add_standard_fields

_IDENTITY = ("service", "env", "version")


def _record(fmt: str) -> dict[str, Any]:
    config = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": fmt})
    assert config.logging.fmt == fmt, f"config did not take fmt={fmt!r}"
    return add_standard_fields(config)(None, "info", {"event": "auth.login.success"})


def test_json_carries_the_identity_fields() -> None:
    record = _record("json")

    for field in _IDENTITY:
        assert field in record, f"{field} missing from a json record"


def test_console_omits_the_identity_fields() -> None:
    record = _record("console")

    assert [f for f in _IDENTITY if f in record] == []


def test_pretty_omits_the_identity_fields() -> None:
    record = _record("pretty")

    assert [f for f in _IDENTITY if f in record] == []


def test_a_value_the_caller_supplied_is_kept_whatever_the_format() -> None:
    """Omitting a default is not licence to drop what the caller passed."""
    config = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "console"})

    record = add_standard_fields(config)(None, "info", {"event": "e", "service": "checkout"})

    assert record["service"] == "checkout"
