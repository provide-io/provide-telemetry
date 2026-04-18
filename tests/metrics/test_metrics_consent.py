# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving consent-related mutants in metrics/fallback.py.

Mutants addressed:
  Counter.add   mutmut_1/2/3/5/6/7
  Gauge.add     mutmut_1/2/3/5/6/7
  Gauge.set     mutmut_1/2/3/5/6/7
  Histogram.record mutmut_1/2/3/5/6/7

mutmut_1: should_allow = None (fallback lambda replaced with None)
mutmut_2: should_allow = lambda ... : None (returns None = falsy → blocks metrics)
mutmut_3: should_allow = lambda ... : False (fallback returns False → blocks metrics)
mutmut_5: should_allow(None) instead of should_allow("metrics")
mutmut_6: should_allow("XXmetricsXX") instead of should_allow("metrics")
mutmut_7: should_allow("METRICS") instead of should_allow("metrics")

For mutmut_5/6/7: we mock the consent module's should_allow and assert it is called
with exactly "metrics" (not None, "XXmetricsXX", or "METRICS").

For mutmut_1/2/3: the fallback lambda only runs when the consent module is absent
(ImportError path). We test by patching the consent import to fail, then verifying
that operations still proceed (fallback must return True, not None/False).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from provide.telemetry.metrics import fallback as fallback_mod
from provide.telemetry.metrics.fallback import Counter, Gauge, Histogram


@pytest.fixture(autouse=True)
def _patch_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass sampling/backpressure/health so we only test consent behaviour."""
    monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", lambda signal, name: True)
    monkeypatch.setattr(
        fallback_mod,
        "_try_acquire_unchecked",
        lambda signal: SimpleNamespace(signal=signal, token=1),
    )
    monkeypatch.setattr(fallback_mod, "release", lambda ticket: None)
    monkeypatch.setattr(fallback_mod, "increment_emitted", lambda signal: None)


# ── should_allow is called with exactly "metrics" ──────────────────────────


class TestConsentSignalArgument:
    """Kill mutmut_5 (None), mutmut_6 ("XXmetricsXX"), mutmut_7 ("METRICS").

    We intercept the call to consent.should_allow inside each method and
    assert the first positional argument is exactly the string "metrics".
    """

    def _make_consent_spy(self) -> tuple[list[tuple[str, ...]], MagicMock]:
        """Return a list to collect calls and a mock that always allows."""
        calls: list[tuple[str, ...]] = []
        mock = MagicMock(return_value=True)

        def _spy(*args: str) -> bool:
            calls.append(args)
            return True

        return calls, _spy  # type: ignore

    def test_counter_add_calls_should_allow_with_metrics(self) -> None:
        """Counter.add must call should_allow("metrics")."""
        with patch("provide.telemetry.consent.should_allow") as mock_allow:
            mock_allow.return_value = True
            Counter("c").add(1)
        # Check it was called with "metrics" as first arg
        assert mock_allow.called, "should_allow must be called"
        first_call_args = mock_allow.call_args_list[0]
        signal_arg = first_call_args[0][0] if first_call_args[0] else first_call_args[1].get("_signal")
        assert signal_arg == "metrics", (
            f"should_allow must be called with 'metrics', got {signal_arg!r}"
        )

    def test_gauge_add_calls_should_allow_with_metrics(self) -> None:
        """Gauge.add must call should_allow("metrics")."""
        with patch("provide.telemetry.consent.should_allow") as mock_allow:
            mock_allow.return_value = True
            Gauge("g").add(1)
        assert mock_allow.called
        signal_arg = mock_allow.call_args_list[0][0][0]
        assert signal_arg == "metrics", f"Expected 'metrics', got {signal_arg!r}"

    def test_gauge_set_calls_should_allow_with_metrics(self) -> None:
        """Gauge.set must call should_allow("metrics")."""
        with patch("provide.telemetry.consent.should_allow") as mock_allow:
            mock_allow.return_value = True
            Gauge("g").set(5)
        assert mock_allow.called
        signal_arg = mock_allow.call_args_list[0][0][0]
        assert signal_arg == "metrics", f"Expected 'metrics', got {signal_arg!r}"

    def test_histogram_record_calls_should_allow_with_metrics(self) -> None:
        """Histogram.record must call should_allow("metrics")."""
        with patch("provide.telemetry.consent.should_allow") as mock_allow:
            mock_allow.return_value = True
            Histogram("h").record(1.0)
        assert mock_allow.called
        signal_arg = mock_allow.call_args_list[0][0][0]
        assert signal_arg == "metrics", f"Expected 'metrics', got {signal_arg!r}"

    def test_counter_add_blocked_when_consent_denies_metrics(self) -> None:
        """Counter.add must NOT record value when should_allow returns False.

        This confirms the should_allow result is actually used (not ignored).
        Kills mutmut_1/2/3 indirectly: if fallback returns True always, the
        no-consent case would still record values.
        """
        with patch("provide.telemetry.consent.should_allow", return_value=False):
            c = Counter("blocked.counter")
            c.add(10)
        # value must remain at 0 since operation was blocked by consent
        assert c.value == 0, f"Counter.add must be blocked by consent, got value={c.value}"

    def test_gauge_add_blocked_when_consent_denies(self) -> None:
        """Gauge.add must NOT record when consent returns False."""
        with patch("provide.telemetry.consent.should_allow", return_value=False):
            g = Gauge("blocked.gauge")
            g.add(10)
        assert g.value == 0, f"Gauge.add must be blocked by consent, got value={g.value}"

    def test_gauge_set_blocked_when_consent_denies(self) -> None:
        """Gauge.set must NOT record when consent returns False."""
        with patch("provide.telemetry.consent.should_allow", return_value=False):
            g = Gauge("blocked.gauge.set")
            g.set(10)
        assert g.value == 0, f"Gauge.set must be blocked by consent, got value={g.value}"

    def test_histogram_record_blocked_when_consent_denies(self) -> None:
        """Histogram.record must NOT record when consent returns False."""
        with patch("provide.telemetry.consent.should_allow", return_value=False):
            h = Histogram("blocked.hist")
            h.record(42.0)
        assert h.count == 0, f"Histogram.record must be blocked by consent, got count={h.count}"


# ── Fallback lambda: must return True (not None/False) ────────────────────────


class TestConsentFallbackLambda:
    """Kill mutmut_1 (lambda→None), mutmut_2 (returns None), mutmut_3 (returns False).

    These mutants affect the ImportError fallback lambda. We simulate the
    ImportError path by temporarily removing the consent module from sys.modules
    and patching the import to fail.
    """

    def _run_without_consent_module(self, fn: object) -> None:
        """Run fn() with consent module absent from sys.modules."""
        original = sys.modules.pop("provide.telemetry.consent", None)
        try:
            # Reload fallback module with builtins.__import__ patched to raise ImportError
            import builtins

            real_import = builtins.__import__

            def _failing_import(name: str, *args: object, **kwargs: object) -> object:
                if name == "provide.telemetry.consent":
                    raise ImportError("governance stripped")
                return real_import(name, *args, **kwargs)

            with patch.object(builtins, "__import__", side_effect=_failing_import):
                fn()  # type: ignore[call-arg]
        finally:
            if original is not None:
                sys.modules["provide.telemetry.consent"] = original

    def test_counter_add_proceeds_when_consent_module_absent(self) -> None:
        """Counter.add must proceed (not be silently blocked) when consent is stripped.

        Kills mutmut_3: fallback lambda returns False → add is blocked.
        Kills mutmut_2: returns None → `not None` is True → add is blocked.
        Kills mutmut_1: fallback=None → calling None("metrics") raises TypeError.
        """
        c = Counter("fallback.counter")

        def _do_add() -> None:
            c.add(5)

        self._run_without_consent_module(_do_add)
        assert c.value == 5, (
            f"Counter.add must proceed when consent module is absent (fallback should return True), "
            f"got value={c.value}"
        )

    def test_gauge_add_proceeds_when_consent_module_absent(self) -> None:
        """Gauge.add must proceed when consent module is absent."""
        g = Gauge("fallback.gauge")

        def _do_add() -> None:
            g.add(7)

        self._run_without_consent_module(_do_add)
        assert g.value == 7, f"Gauge.add must proceed with absent consent, got value={g.value}"

    def test_gauge_set_proceeds_when_consent_module_absent(self) -> None:
        """Gauge.set must proceed when consent module is absent."""
        g = Gauge("fallback.gauge.set")

        def _do_set() -> None:
            g.set(3)

        self._run_without_consent_module(_do_set)
        assert g.value == 3, f"Gauge.set must proceed with absent consent, got value={g.value}"

    def test_histogram_record_proceeds_when_consent_module_absent(self) -> None:
        """Histogram.record must proceed when consent module is absent."""
        h = Histogram("fallback.hist")

        def _do_record() -> None:
            h.record(9.9)

        self._run_without_consent_module(_do_record)
        assert h.count == 1, (
            f"Histogram.record must proceed with absent consent, got count={h.count}"
        )
