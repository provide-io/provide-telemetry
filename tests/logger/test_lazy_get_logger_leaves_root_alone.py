# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""``get_logger()`` is a getter, and a getter may not evict the host's handlers.

Its lazy path configures logging when the SDK has not been set up, and that
configuration went through ``basicConfig(force=True)`` -- which removes *and
closes* every handler on the root logger, including ones the SDK never
installed.

Importing a module that holds ``log = get_logger(__name__)`` at module scope is
enough to trigger it. Under pytest that closes the capture handler, and the
damage surfaces somewhere unrelated: in pyvider, 49 CLI tests began reporting an
empty ``result.output`` from ``CliRunner.invoke()`` while the command's real
output went to pytest's own capture.

Owning the root is defensible for ``setup_telemetry()``, which the host calls on
purpose. It is not defensible for a getter.
"""

from __future__ import annotations

import logging

from provide.telemetry.logger.core import _reset_logging_for_tests, get_logger


class _Marker(logging.Handler):
    """A handler standing in for whatever the host had installed."""

    def __init__(self) -> None:
        super().__init__()
        self.closed_by_someone_else = False

    def emit(self, record: logging.LogRecord) -> None:
        pass

    def close(self) -> None:
        self.closed_by_someone_else = True
        super().close()


def _install_host_handler() -> _Marker:
    handler = _Marker()
    logging.getLogger().addHandler(handler)
    return handler


def test_the_hosts_handler_survives_a_lazy_get_logger() -> None:
    _reset_logging_for_tests()
    root = logging.getLogger()
    handler = _install_host_handler()
    try:
        get_logger("probe")

        assert handler in root.handlers, "the host's handler was evicted from the root logger"
    finally:
        root.removeHandler(handler)


def test_the_hosts_handler_is_not_closed_by_a_lazy_get_logger() -> None:
    _reset_logging_for_tests()
    root = logging.getLogger()
    handler = _install_host_handler()
    try:
        get_logger("probe")

        assert not handler.closed_by_someone_else, "the host's handler was closed by the SDK"
    finally:
        root.removeHandler(handler)


def test_the_sdk_still_installs_its_own_handler_on_the_lazy_path() -> None:
    """The guard above must not be satisfied by installing nothing at all."""
    from provide.telemetry.logger.core import _installed_fanout

    _reset_logging_for_tests()

    get_logger("probe")

    assert _installed_fanout() is not None, "the SDK installed no handler, so nothing would emit"


def test_the_setup_path_does_claim_the_root() -> None:
    """The counterpart: setup was asked for, so it owns the handler list.

    Without this, nothing distinguishes the two paths and `claim_root=True` at
    the setup call site could be anything.
    """
    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.logger.core import configure_logging

    _reset_logging_for_tests()
    root = logging.getLogger()
    handler = _install_host_handler()
    try:
        configure_logging(TelemetryConfig.from_env(), force=True)

        assert handler not in root.handlers, "setup left a handler it was entitled to replace"
    finally:
        root.removeHandler(handler)


def test_the_lazy_path_does_not_reconfigure_once_configured() -> None:
    """It passes force=False, so a second get_logger() is a no-op.

    Reconfiguring on every call would rebuild the pipeline behind any host that
    had adjusted it, and would make the handler count grow with the number of
    modules importing a logger.
    """
    from provide.telemetry.logger.core import _installed_fanout

    _reset_logging_for_tests()
    get_logger("probe")
    first = _installed_fanout()

    get_logger("probe.again")

    assert _installed_fanout() is first, "the lazy path rebuilt an already-installed pipeline"


def test_the_lazy_path_sets_the_root_level() -> None:
    """Attaching a handler is not enough; the root must pass records to it."""
    _reset_logging_for_tests()
    logging.getLogger().setLevel(logging.CRITICAL)

    get_logger("probe")

    assert logging.getLogger().level != logging.CRITICAL, "root level left where it would drop records"
