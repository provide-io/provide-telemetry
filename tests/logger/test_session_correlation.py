# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for session correlation."""

from __future__ import annotations

from provide.telemetry.logger.context import (
    bind_session_context,
    clear_context,
    clear_session_context,
    get_context,
    get_session_id,
)


class TestSessionCorrelation:
    def setup_method(self) -> None:
        clear_context()
        clear_session_context()

    def test_bind_and_get_session_id(self) -> None:
        bind_session_context("sess-123")
        assert get_session_id() == "sess-123"

    def test_session_id_in_context(self) -> None:
        bind_session_context("sess-456")
        ctx = get_context()
        assert ctx["session_id"] == "sess-456"

    def test_clear_session_context(self) -> None:
        bind_session_context("sess-789")
        clear_session_context()
        assert get_session_id() is None
        assert "session_id" not in get_context()

    def test_default_session_id_is_none(self) -> None:
        assert get_session_id() is None
