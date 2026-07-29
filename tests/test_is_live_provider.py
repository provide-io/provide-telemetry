# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for :func:`provide.telemetry._otel.is_live_provider`.

The predicate that decides whether the OTel global holds a real SDK provider or
the API's placeholder. Both halves of the lifecycle pair are required: a partial
implementation is not something we can treat as an exporting provider, and the
absent half must read as False rather than raising.
"""

from __future__ import annotations

from provide.telemetry._otel import is_live_provider


class _Live:
    def force_flush(self, *_a: object, **_k: object) -> None: ...

    def shutdown(self, *_a: object, **_k: object) -> None: ...


class _FlushOnly:
    def force_flush(self, *_a: object, **_k: object) -> None: ...


class _ShutdownOnly:
    def shutdown(self, *_a: object, **_k: object) -> None: ...


class _NonCallableAttrs:
    force_flush = "not callable"
    shutdown = "not callable"


def test_accepts_a_provider_with_the_full_lifecycle_pair() -> None:
    assert is_live_provider(_Live()) is True


def test_rejects_the_api_placeholder() -> None:
    assert is_live_provider(object()) is False


def test_rejects_a_provider_that_can_flush_but_not_shut_down() -> None:
    """Also pins the absent-attribute default: this must be False, not AttributeError."""
    assert is_live_provider(_FlushOnly()) is False


def test_rejects_a_provider_that_can_shut_down_but_not_flush() -> None:
    assert is_live_provider(_ShutdownOnly()) is False


def test_rejects_non_callable_lifecycle_attributes() -> None:
    assert is_live_provider(_NonCallableAttrs()) is False
