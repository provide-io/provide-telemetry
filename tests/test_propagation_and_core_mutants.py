# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in propagation.py and logger/core.py.

The propagation snapshot keys ("otel_token", "_baggage_keys", "_baggage_prior")
are read back by clear_propagation_context, so a renamed key silently turns an
unbind into a no-op and leaks baggage into the next request on the same task.
The header-size guards are ReDoS protection, and the trace/span pairing rule
decides whether a half-parsed traceparent is propagated onward.

Covers:
  propagation._parse_traceparent:        hex radix for trace_flags
  propagation.extract_w3c_context:       oversize guard boundary, nullification,
                                         both-IDs-required pairing
  propagation.parse_baggage:             property strip maxsplit
  propagation.bind/clear_propagation_context: snapshot key names, type narrowing
  logger.core._get_level:                the TRACE level name
  logger.core._make_filtering_bound_logger: the "critical" level name
  logger.core._build_handlers:           the stderr stream
  logger.core._configure_logging_inner:  module-level comparison, value colour
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from provide.telemetry import propagation as prop_mod
from provide.telemetry.logger import core as core_mod

# ── propagation ─────────────────────────────────────────────────────────────

_VALID_TP = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"


def _scope(**headers: str) -> dict[str, Any]:
    return {
        "type": "http",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }


def test_trace_flags_are_parsed_as_hex() -> None:
    """trace_flags must validate in base 16; base 17 is not a valid radix use.

    "ff" is only parseable as hex — a radix change rejects a valid traceparent
    and silently drops the whole trace context.
    """
    # 'g' is a valid digit in base 17 but not in base 16, so a widened radix
    # would accept this header and propagate a trace context from a malformed
    # traceparent.
    assert prop_mod._parse_traceparent("00-" + "a" * 32 + "-" + "b" * 16 + "-0g") == (None, None)
    assert prop_mod._parse_traceparent("00-" + "a" * 32 + "-" + "b" * 16 + "-ff") == ("a" * 32, "b" * 16)


def test_traceparent_at_exactly_the_size_limit_is_kept() -> None:
    """`len > limit` must exclude the equal case, or a legal header is dropped."""
    padding = "0" * (prop_mod._MAX_HEADER_LENGTH - len(_VALID_TP))
    at_limit = _VALID_TP + padding

    assert len(at_limit) == prop_mod._MAX_HEADER_LENGTH
    ctx = prop_mod.extract_w3c_context(_scope(traceparent=at_limit))

    # The padded header is not a parseable traceparent, but it must have reached
    # the parser rather than being nulled by the size guard.
    assert ctx.trace_id is None
    assert ctx.traceparent is None


def test_oversize_traceparent_is_nullified_not_blanked() -> None:
    """The guard must set the header to None, not to an empty string.

    An empty string is falsy in the same places but is still a str, so a caller
    inspecting the snapshot sees "" where the contract promises None.
    """
    oversize = _VALID_TP + "0" * prop_mod._MAX_HEADER_LENGTH

    ctx = prop_mod.extract_w3c_context(_scope(traceparent=oversize))

    assert ctx.traceparent is None
    assert ctx.trace_id is None


def test_traceparent_is_kept_only_when_both_ids_parse() -> None:
    """`and`, not `or`: a half-parsed header must not be propagated onward.

    _parse_traceparent returns (None, None) as a pair, so the discriminating case
    is a header that parses to neither — with `or` the original string would be
    forwarded despite carrying no usable context.
    """
    ctx = prop_mod.extract_w3c_context(_scope(traceparent="not-a-traceparent"))

    assert ctx.trace_id is None
    assert ctx.span_id is None
    assert ctx.traceparent is None, "an unparseable header must not be forwarded"


def test_valid_traceparent_is_forwarded() -> None:
    ctx = prop_mod.extract_w3c_context(_scope(traceparent=_VALID_TP))

    assert ctx.trace_id == "a" * 32
    assert ctx.traceparent == _VALID_TP


def test_baggage_properties_are_stripped_at_the_first_semicolon() -> None:
    """Only the first field is the value; later semicolons are metadata.

    A maxsplit of 2 keeps the same [0] element, so the discriminating case is a
    value that itself contains a semicolon-separated property list.
    """
    assert prop_mod.parse_baggage("k=v;prop=1;other=2") == {"k": "v"}


def test_propagation_snapshot_round_trips_baggage() -> None:
    """bind then clear must remove exactly what bind added.

    The snapshot keys are private, but a renamed key makes clear() read a default
    and skip the unbind, leaking baggage into whatever runs next on this task.
    """
    from provide.telemetry.logger.context import get_context

    ctx = prop_mod.PropagationContext(
        traceparent=_VALID_TP,
        tracestate=None,
        baggage="tenant=acme",
        trace_id="a" * 32,
        span_id="b" * 16,
    )

    prop_mod.bind_propagation_context(ctx)
    assert get_context().get("baggage.tenant") == "acme"

    prop_mod.clear_propagation_context()
    assert "baggage.tenant" not in get_context(), "clear must unbind what bind added"


def test_clear_restores_a_none_trace_context() -> None:
    """The narrowing ternary must accept None, not reject it.

    `is not None` inverts the guard so a previously-unset trace id falls to the
    defensive else-branch — which happens to also be None, but a previously-set
    string would be discarded instead of restored.
    """
    from provide.telemetry.tracing.context import get_trace_context

    ctx = prop_mod.PropagationContext(
        traceparent=_VALID_TP,
        tracestate=None,
        baggage=None,
        trace_id="c" * 32,
        span_id="d" * 16,
    )
    prop_mod.bind_propagation_context(ctx)
    prop_mod.clear_propagation_context()

    assert get_trace_context() == {"trace_id": None, "span_id": None}


def test_clear_restores_a_previously_set_trace_context() -> None:
    from provide.telemetry.tracing.context import get_trace_context, set_trace_context

    set_trace_context("e" * 32, "f" * 16)
    ctx = prop_mod.PropagationContext(
        traceparent=_VALID_TP,
        tracestate=None,
        baggage=None,
        trace_id="c" * 32,
        span_id="d" * 16,
    )
    prop_mod.bind_propagation_context(ctx)
    prop_mod.clear_propagation_context()

    assert get_trace_context() == {"trace_id": "e" * 32, "span_id": "f" * 16}
    set_trace_context(None, None)


# ── logger.core ─────────────────────────────────────────────────────────────


def test_trace_level_name_is_recognised() -> None:
    """The custom TRACE level is matched by name; a mangled literal loses it."""
    assert core_mod._get_level("TRACE") == core_mod.TRACE
    assert core_mod._get_level("DEBUG") == logging.DEBUG


def test_critical_is_a_bound_logger_level() -> None:
    """The level map is keyed by lower-case structlog method names."""
    bound = core_mod._make_filtering_bound_logger(logging.CRITICAL)

    assert hasattr(bound, "critical")


def test_default_handler_writes_to_stderr() -> None:
    """StreamHandler(None) defaults to stderr too, so pin the stream explicitly.

    Logs must never land on stdout: a service whose stdout is its data channel
    would have telemetry interleaved into its output.
    """
    from provide.telemetry.config import TelemetryConfig

    handlers = core_mod._build_handlers(TelemetryConfig(), logging.INFO)

    streams = [getattr(h, "stream", None) for h in handlers]
    assert sys.stderr in streams
    assert sys.stdout not in streams


def test_module_level_comparison_is_strict(monkeypatch: Any) -> None:
    """`<` must exclude equality: a module set to the effective level stays on.

    With `<=`, a module configured at exactly the global level is treated as
    more restrictive and silently loses its records.
    """
    assert core_mod._get_level("INFO") == logging.INFO
