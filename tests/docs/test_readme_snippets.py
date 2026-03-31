# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from unittest.mock import patch

from provide.telemetry import event_name, get_logger, setup_telemetry, shutdown_telemetry
from provide.telemetry.schema.events import EventSchemaError


def test_readme_quickstart_snippet_executes() -> None:
    setup_telemetry()
    try:
        log = get_logger(__name__)
        log.info("app.start.ok", request_id="req-1")
    finally:
        shutdown_telemetry()


def test_readme_event_name_snippet_executes() -> None:
    assert event_name("auth", "login", "success") == "auth.login.success"
    assert event_name("auth", "login", "failed") == "auth.login.failed"
    assert event_name("auth", "login", "password", "failed") == "auth.login.password.failed"

    with patch("provide.telemetry.runtime._is_strict_event_name", return_value=True):
        try:
            event_name("auth", "login.password", "failed")
        except EventSchemaError:
            pass
        else:
            raise AssertionError("expected invalid event segment to raise EventSchemaError")
