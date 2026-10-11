# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The OTLP push TLS files must be readable before an exporter is built.

See prometheus_metrics.push_security in spec/telemetry-api.yaml. The OTel
exporters read OTEL_EXPORTER_OTLP_[SIGNAL_]CERTIFICATE, CLIENT_CERTIFICATE and
CLIENT_KEY themselves, but an unreadable file only shows up as a failure on
every export. Each builder asks tls_ready() first: a file that cannot be read
leaves that signal's exporter unbuilt, and setup reports it as setup_error.
"""

from __future__ import annotations

import logging
import os
import ssl
import threading
from collections.abc import Mapping
from pathlib import Path

_logger = logging.getLogger(__name__)

_SEPARATOR = "; "

_lock = threading.Lock()
_problems: list[str] = []


def _resolve(signal: str, kind: str, env: Mapping[str, str]) -> tuple[str, str]:
    """(path, variable name): the per-signal variable when set, else the shared one."""
    name = f"OTEL_EXPORTER_OTLP_{signal.upper()}_{kind}"
    if not env.get(name):
        name = f"OTEL_EXPORTER_OTLP_{kind}"
    return env.get(name) or "", name


def unreadable(signal: str, env: Mapping[str, str]) -> str | None:
    """The first configured TLS file for signal that cannot be read or loaded, described, or None.

    The CA file must hold at least one certificate, and a client certificate and
    key, when both are set, must form a pair.
    """
    ca, ca_name = _resolve(signal, "CERTIFICATE", env)
    cert, cert_name = _resolve(signal, "CLIENT_CERTIFICATE", env)
    key, key_name = _resolve(signal, "CLIENT_KEY", env)
    for name, path in ((ca_name, ca), (cert_name, cert), (key_name, key)):
        if path:
            try:
                Path(path).read_bytes()
            except OSError as exc:
                return f"{name}={path}: {exc.strerror}"
    if ca:
        try:
            ssl.create_default_context(cafile=ca)
        except ssl.SSLError:
            return f"{ca_name}={ca}: no PEM certificates"
    if cert and key:
        try:
            ssl.create_default_context().load_cert_chain(cert, key)
        except ssl.SSLError as exc:
            return f"{cert_name}={cert}, {key_name}={key}: {exc.reason}"
    return None


def tls_ready(signal: str) -> bool:
    """Whether signal's exporter may be built; records the reason when it may not."""
    problem = unreadable(signal, os.environ)
    if problem is None:
        return True
    with _lock:
        _problems.append(problem)
    _logger.warning("otlp.tls_file_unreadable", extra={"signal": signal, "error": problem})
    return False


def take_problems() -> str | None:
    """The problems recorded since the last call, joined, or None; clears them."""
    with _lock:
        joined = _SEPARATOR.join(_problems)
        _problems.clear()
    return joined or None
