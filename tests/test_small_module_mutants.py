# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants across several small modules.

Covers:
  _endpoint._check_port:            the IPv6-safe rsplit("]", 1) trailing-colon guard
  consent.should_allow:             the sub-threshold sentinel default for unknown levels
  consent._load_consent_from_env:   the FULL default is uppercase before ConsentLevel()
  _config_validation:               endpoint join, warning category and stacklevel
  sampling._should_sample_unchecked: the 1.0 / 0.0 fast-path boundaries
  sampling._normalize_rate:         the clamp warning's event name
  cardinality.guard_attributes:     the prune-cadence comparison
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import pytest

from provide.telemetry import cardinality as cardinality_mod
from provide.telemetry import consent as consent_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry._config_validation import resolve_otlp_endpoint, warn_on_endpoint_shadowing
from provide.telemetry._endpoint import _check_port
from provide.telemetry.consent import ConsentLevel

# ── _endpoint._check_port ───────────────────────────────────────────────────


def test_trailing_colon_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid OTLP endpoint port"):
        _check_port(urlparse("http://host:"), "http://host:")


def test_ipv6_host_without_a_port_is_accepted() -> None:
    """rsplit("]", 1)[-1] must look only *after* the IPv6 bracket.

    A plain split, a maxsplit of 2, or a missing maxsplit changes which segment
    is inspected, making the colons inside the address look like a trailing-colon
    endpoint and rejecting a perfectly valid URL.
    """
    endpoint = "http://[2001:db8::1]"
    _check_port(urlparse(endpoint), endpoint)


def test_ipv6_host_with_a_trailing_colon_is_still_rejected() -> None:
    endpoint = "http://[2001:db8::1]:"
    with pytest.raises(ValueError, match="invalid OTLP endpoint port"):
        _check_port(urlparse(endpoint), endpoint)


def test_ipv6_host_with_a_real_port_is_accepted() -> None:
    endpoint = "http://[2001:db8::1]:4318"
    _check_port(urlparse(endpoint), endpoint)


def test_bracket_in_userinfo_is_split_from_the_right() -> None:
    """Only the segment after the LAST "]" may be inspected for a trailing colon.

    netloc here is 'a]b@[::1]': splitting from the left leaves 'b@[::1]', whose
    IPv6 colons look like a trailing-colon endpoint and wrongly reject the URL.
    Splitting from the right leaves '', which correctly accepts it.
    """
    endpoint = "http://a]b@[::1]"
    _check_port(urlparse(endpoint), endpoint)


# ── consent.should_allow ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_consent() -> Iterator[None]:
    consent_mod._reset_consent_for_tests()
    yield
    consent_mod._reset_consent_for_tests()


@pytest.mark.parametrize(
    ("level", "expected"),
    [(ConsentLevel.FUNCTIONAL, False), (ConsentLevel.MINIMAL, False)],
)
def test_unknown_log_level_falls_below_every_threshold(level: ConsentLevel, expected: bool) -> None:
    """The `.get(..., 0)` default must sort below WARNING and ERROR.

    A default of 1 (DEBUG) still sorts below both, but an empty-string lookup key
    mutated to "XXXX" would miss the map the same way — so the pairing that pins
    this is the None case here against the known-level cases below.
    """
    consent_mod.set_consent_level(level)

    assert consent_mod.should_allow("logs", None) is expected
    assert consent_mod.should_allow("logs", "totally-unknown") is expected


def test_functional_consent_allows_warning_and_above() -> None:
    consent_mod.set_consent_level(ConsentLevel.FUNCTIONAL)

    assert consent_mod.should_allow("logs", "INFO") is False
    assert consent_mod.should_allow("logs", "WARNING") is True
    assert consent_mod.should_allow("logs", "warning") is True, "level must be upper-cased"


def test_minimal_consent_allows_only_error_and_above() -> None:
    consent_mod.set_consent_level(ConsentLevel.MINIMAL)

    assert consent_mod.should_allow("logs", "WARNING") is False
    assert consent_mod.should_allow("logs", "ERROR") is True
    assert consent_mod.should_allow("logs", "error") is True, "level must be upper-cased"


def test_trace_level_is_distinguished_from_a_missing_level() -> None:
    """TRACE maps to 0 — the same integer as the sentinel default.

    Mutating the sentinel to 1 makes an unknown level outrank TRACE, which this
    pins by requiring both to be refused at FUNCTIONAL while DEBUG-and-below stay
    refused too.
    """
    consent_mod.set_consent_level(ConsentLevel.FUNCTIONAL)

    assert consent_mod.should_allow("logs", "TRACE") is False
    assert consent_mod.should_allow("logs", "DEBUG") is False


def test_consent_env_default_is_full(monkeypatch: Any) -> None:
    """The literal default must already be a valid ConsentLevel name.

    ConsentLevel("full") raises ValueError, which the caller swallows — so a
    lower-cased default would silently leave consent at whatever it was.
    """
    monkeypatch.delenv("PROVIDE_CONSENT_LEVEL", raising=False)
    consent_mod.set_consent_level(ConsentLevel.NONE)

    consent_mod._load_consent_from_env()

    assert consent_mod.get_consent_level() is ConsentLevel.FULL


# ── _config_validation ──────────────────────────────────────────────────────


def test_shared_endpoint_join_strips_only_slashes() -> None:
    """rstrip('/') must strip the separator, not an arbitrary character set."""
    data = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318///"}

    assert resolve_otlp_endpoint(data, "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "v1/logs") == (
        "http://collector:4318/v1/logs"
    )


def test_shared_endpoint_join_keeps_a_trailing_non_slash_character() -> None:
    """rstrip takes a character SET, so the argument must contain only "/".

    A path ending in an upper-case X catches a widened set such as "XX/XX",
    which would strip the X and then the separator, silently dropping a path
    segment from every resolved signal endpoint.
    """
    data = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/X"}

    assert resolve_otlp_endpoint(data, "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "v1/logs") == (
        "http://collector:4318/X/v1/logs"
    )


def test_endpoint_shadowing_warning_category_and_stacklevel(monkeypatch: Any) -> None:
    """The category must be UserWarning and the blame must land on the caller.

    Captured off warnings.warn directly rather than off the recorded frame:
    mutmut's trampoline adds a stack frame, so frame identity is not stable
    under mutation while the passed stacklevel literal is.
    """
    calls: list[dict[str, Any]] = []

    def fake_warn(message: object, category: object = None, stacklevel: int = 1, **kw: Any) -> None:
        calls.append({"message": str(message), "category": category, "stacklevel": stacklevel})

    monkeypatch.setattr(warnings, "warn", fake_warn)

    warn_on_endpoint_shadowing(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://general",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs-specific",
        }
    )

    assert len(calls) == 1
    assert calls[0]["category"] is UserWarning
    assert calls[0]["stacklevel"] == 3
    assert "shadows" in calls[0]["message"]


# ── sampling ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_sampling() -> Iterator[None]:
    sampling_mod.reset_sampling_for_tests()
    yield
    sampling_mod.reset_sampling_for_tests()


def test_rate_of_exactly_one_always_samples() -> None:
    """`rate >= 1.0` must include 1.0 itself — `> 1.0` would drop the always-on case."""
    sampling_mod.set_sampling_policy("logs", sampling_mod.SamplingPolicy(default_rate=1.0))

    assert all(sampling_mod.should_sample("logs") for _ in range(50))


def test_rate_just_below_one_is_not_forced_on(monkeypatch: Any) -> None:
    """A `>= 2.0` mutant would send every sub-1.0 rate down the random path.

    Pinning the fast path: with a rate of 1.0 the random source must never be
    consulted at all.
    """
    monkeypatch.setattr("provide.telemetry.sampling.random.random", _no_rng)
    sampling_mod.set_sampling_policy("logs", sampling_mod.SamplingPolicy(default_rate=1.0))

    assert sampling_mod.should_sample("logs") is True


def test_rate_of_exactly_zero_never_samples(monkeypatch: Any) -> None:
    """`rate <= 0.0` must include 0.0 — `< 0.0` would fall through to the rng."""
    monkeypatch.setattr("provide.telemetry.sampling.random.random", _no_rng)
    sampling_mod.set_sampling_policy("logs", sampling_mod.SamplingPolicy(default_rate=0.0))

    assert sampling_mod.should_sample("logs") is False


def test_clamping_an_out_of_range_rate_logs_its_event_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=sampling_mod.__name__):
        assert sampling_mod._normalize_rate(1.5) == 1.0

    assert [r.getMessage() for r in caplog.records if r.name == sampling_mod.__name__] == [
        "sampling.rate.clamped.warning"
    ]


def test_in_range_rate_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=sampling_mod.__name__):
        assert sampling_mod._normalize_rate(0.25) == 0.25

    assert [r for r in caplog.records if r.name == sampling_mod.__name__] == []


# ── cardinality prune cadence ───────────────────────────────────────────────


def test_prune_runs_on_the_first_sight_of_a_key(monkeypatch: Any) -> None:
    """An unseen key defaults to 0.0, so `now - 0.0 >= INTERVAL` prunes immediately.

    `now + last` would compare a sum instead of an elapsed time, a default of 1.0
    shifts the very first sweep, and `>` instead of `>=` skips the exact-boundary
    sweep. All three change when the first prune happens.
    """
    cardinality_mod.clear_cardinality_limits()
    cardinality_mod.register_cardinality_limit("k", max_values=2, ttl_seconds=1.0)
    collected: list[float] = []
    monkeypatch.setattr(
        cardinality_mod,
        "_collect_expired",
        _record_and_empty(collected),
    )
    monkeypatch.setattr(
        "provide.telemetry.cardinality.time.monotonic",
        lambda: cardinality_mod._PRUNE_INTERVAL,
    )

    cardinality_mod.guard_attributes({"k": "v"})

    assert collected == [cardinality_mod._PRUNE_INTERVAL], "first sweep must fire at the boundary"


def test_prune_is_skipped_just_below_the_interval(monkeypatch: Any) -> None:
    cardinality_mod.clear_cardinality_limits()
    cardinality_mod.register_cardinality_limit("k", max_values=2, ttl_seconds=1.0)
    cardinality_mod._last_prune["k"] = 100.0
    collected: list[float] = []
    monkeypatch.setattr(
        cardinality_mod,
        "_collect_expired",
        _record_and_empty(collected),
    )
    monkeypatch.setattr(
        "provide.telemetry.cardinality.time.monotonic",
        lambda: 100.0 + cardinality_mod._PRUNE_INTERVAL - 0.01,
    )

    cardinality_mod.guard_attributes({"k": "v"})

    assert collected == [], "a sweep must not run before the interval elapses"


def test_unregistered_signal_samples_rather_than_dropping() -> None:
    """The defensive `policy is None` branch must fail open, not closed.

    should_sample() validates the signal first, so this is only reachable by
    calling the unchecked hot path directly — but returning False there would
    silently drop every record for a signal whose policy went missing.
    """
    assert sampling_mod._should_sample_unchecked("not-a-signal") is True


# ── resilient_exporter: OTel version shim ───────────────────────────────────


def test_log_export_result_prefers_the_current_otel_name() -> None:
    """OTel >= 1.42 exposes LogRecordExportResult; it must win when present."""
    from provide.telemetry.resilient_exporter import _resolve_log_export_result

    assert _resolve_log_export_result({"LogRecordExportResult": "new", "LogExportResult": "old"}) == "new"


def test_log_export_result_falls_back_to_the_deprecated_name() -> None:
    """On the supported floor (1.27) only the old name exists."""
    from provide.telemetry.resilient_exporter import _resolve_log_export_result

    assert _resolve_log_export_result({"LogExportResult": "old"}) == "old"


def test_log_export_result_raises_when_neither_name_exists() -> None:
    """A future SDK dropping both names must fail loudly, not silently.

    The `or` must not become `and`: with `and` a present new name would be
    discarded in favour of indexing the old one.
    """
    from provide.telemetry.resilient_exporter import _resolve_log_export_result

    with pytest.raises(KeyError):
        _resolve_log_export_result({})


def _record_and_pass(sink: list[Any]) -> Any:
    def _fn(_signal: str, key: Any) -> bool:
        sink.append(key)
        return True

    return _fn


def _record_and_empty(sink: list[Any]) -> Any:
    def _fn(_key: str, now: float) -> list[Any]:
        sink.append(now)
        return []

    return _fn


def _no_rng() -> float:
    raise AssertionError("the fast path must not consult the random source")
