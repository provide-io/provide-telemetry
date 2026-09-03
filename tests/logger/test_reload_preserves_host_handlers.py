# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A reload leaves handlers the host installed alone.

Python is the one SDK with no log sink of its own, and that is deliberate: a
host redirects with the stdlib's own mechanism instead, which is recorded in
`log_output` in the spec. This is where that premise used to break. Setup
configures the root logger with `basicConfig(force=True)`, which removes and
closes every handler already attached, and every runtime reload re-entered it —
so a handler the host installed after setup vanished at the next config change,
silently, and its records went to stderr instead.

Setup keeps its clean slate. A reload no longer touches the root's handler list
at all: the SDK's fan-out handler stays where it is and its children are
swapped inside it.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.core import _reset_logging_for_tests, configure_logging
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler


@pytest.fixture
def _clean_root() -> Iterator[None]:
    """Restore the root logger, since these tests reconfigure it for real."""
    root = logging.getLogger()
    saved, saved_level = list(root.handlers), root.level
    _reset_logging_for_tests()
    yield
    _reset_logging_for_tests()
    root.handlers[:] = saved
    root.setLevel(saved_level)


def _config(level: str = "INFO") -> TelemetryConfig:
    return TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": level})


def _sdk_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if isinstance(h, _BackpressureFanoutHandler)]


def test_a_reload_keeps_a_handler_the_host_installed(_clean_root: None) -> None:
    configure_logging(_config(), force=True)

    sink = io.StringIO()
    host = logging.StreamHandler(sink)
    logging.getLogger().addHandler(host)

    configure_logging(_config("DEBUG"), force=True)

    assert host in logging.getLogger().handlers, (
        "the reload removed the host's handler; its records now go to a stream it is not reading"
    )


def test_the_host_handler_still_receives_records_after_a_reload(_clean_root: None) -> None:
    """Present in the list is not enough — it has to still be fed."""
    configure_logging(_config(), force=True)

    sink = io.StringIO()
    logging.getLogger().addHandler(logging.StreamHandler(sink))

    configure_logging(_config("DEBUG"), force=True)
    logging.getLogger("reload.check").warning("after the reload")

    assert "after the reload" in sink.getvalue()


def test_a_reload_still_applies_the_new_configuration(_clean_root: None) -> None:
    """Preserving foreign handlers must not cost the reload its effect."""
    configure_logging(_config("WARNING"), force=True)
    assert logging.getLogger().level == logging.WARNING

    configure_logging(_config("DEBUG"), force=True)
    assert logging.getLogger().level == logging.DEBUG


def test_a_reload_does_not_accumulate_sdk_handlers(_clean_root: None) -> None:
    """The fan-out handler is reused, not stacked."""
    configure_logging(_config(), force=True)
    first = _sdk_handlers()
    assert len(first) == 1

    configure_logging(_config("DEBUG"), force=True)
    second = _sdk_handlers()

    assert len(second) == 1
    assert second[0] is first[0], "the reload installed a second fan-out handler instead of reusing one"


def test_setup_keeps_its_clean_slate(_clean_root: None) -> None:
    """A handler present before the SDK configures logging is still cleared.

    Setup owns the pipeline. Preserving a handler installed beforehand would
    double every record for a host that had called basicConfig() already.
    """
    stale = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(stale)

    configure_logging(_config(), force=True)

    assert stale not in logging.getLogger().handlers


def test_a_removed_fanout_handler_is_rebuilt_past_a_foreign_one(_clean_root: None) -> None:
    """The search walks past handlers that are not ours before giving up."""
    configure_logging(_config(), force=True)
    root = logging.getLogger()
    for handler in _sdk_handlers():
        root.removeHandler(handler)
    root.addHandler(logging.StreamHandler(io.StringIO()))
    assert _sdk_handlers() == []

    configure_logging(_config("DEBUG"), force=True)

    assert len(_sdk_handlers()) == 1


def test_children_are_swapped_when_the_handler_carries_no_formatter() -> None:
    """replace_children is reached with formatter unset as well as set.

    A fan-out handler built directly — as the first configure does, before
    basicConfig hands it the '%(message)s' formatter — has none, and a child
    that arrives without one is left without one rather than given None
    explicitly.
    """
    old, new = logging.StreamHandler(io.StringIO()), logging.StreamHandler(io.StringIO())
    fanout = _BackpressureFanoutHandler([old])
    assert fanout.formatter is None

    fanout.replace_children([new])

    assert fanout._handlers == [new]
    assert new.formatter is None


def test_incoming_children_inherit_the_handler_formatter() -> None:
    """A child swapped in gets the formatter the fan-out handler carries.

    basicConfig sets '%(message)s' on the fan-out handler at setup. Without
    this the children installed by every later reload would render under the
    stdlib default instead of the format the SDK configured.
    """
    formatter = logging.Formatter("%(message)s")
    fanout = _BackpressureFanoutHandler([logging.StreamHandler(io.StringIO())])
    fanout.setFormatter(formatter)

    incoming = logging.StreamHandler(io.StringIO())
    fanout.replace_children([incoming])

    assert incoming.formatter is formatter


def test_swapping_in_no_children_leaves_the_level_at_notset() -> None:
    """`min` over an empty child list falls back rather than raising."""
    fanout = _BackpressureFanoutHandler([logging.StreamHandler(io.StringIO())])
    fanout.setLevel(logging.ERROR)

    fanout.replace_children([])

    assert fanout.level == logging.NOTSET


def test_a_removed_fanout_handler_is_rebuilt(_clean_root: None) -> None:
    """A host that tore the SDK's handler out gets a working pipeline back."""
    configure_logging(_config(), force=True)
    root = logging.getLogger()
    for handler in _sdk_handlers():
        root.removeHandler(handler)
    assert _sdk_handlers() == []

    configure_logging(_config("DEBUG"), force=True)

    assert len(_sdk_handlers()) == 1
