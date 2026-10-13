# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Hardening and PII sanitization for records that bypassed the structlog chain.

``configure_logging`` puts the fan-out handler on the root logger, so a plain
``logging.getLogger("third_party").info(...)`` reaches the console and the OTLP
exporter too. Those records never ran the processor chain: their message, args
and ``extra`` attributes would leave the process exactly as the caller wrote
them, secrets and control characters included.

A foreign record is rebuilt rather than edited: the message is formatted here
from hardened and sanitized arguments, the result is hardened and sanitized
once more, and ``args`` is emptied so no child handler formats the raw ones
again. Anything this cannot do safely -- a mapping whose ``items()`` raises, a
template the arguments do not fit, an argument whose ``__str__`` raises --
fails closed to the redaction marker rather than raising out of ``emit`` (which
would hand the raw record to ``handleError``) or leaking.
"""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.processors import _HARDENED_PLACEHOLDER, _get_active_config, harden_input

# Attributes every LogRecord carries, plus the two a Formatter adds. An extra
# key that cleans down to one of these must not overwrite the real field.
_STANDARD_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

# Limits for a record that arrives before any setup has published a config --
# the lazy get_logger() path. The same defaults the pipeline itself would use.
_DEFAULT_CONFIG = TelemetryConfig()

_Harden = Callable[[Any, Any, dict[str, Any]], dict[str, Any]]


class _Cleaner:
    """One record's worth of limits, resolved once from the live config."""

    def __init__(self) -> None:
        # Imported here rather than at module level: a bare `import
        # provide.telemetry` must not load the PII engine.
        from provide.telemetry import pii

        self._sanitize_payload = pii.sanitize_payload
        self._redact_secret_spans = pii.redact_secret_spans
        live = _get_active_config()
        config = live if live is not None else _DEFAULT_CONFIG
        security = config.security
        self._harden: _Harden = harden_input(
            security.max_attr_value_length, security.max_attr_count, security.max_nesting_depth
        )
        self._sanitize = config.logging.sanitize
        self._pii_depth = config.pii_max_depth

    def attributes(self, attributes: dict[str, Any]) -> dict[str, Any]:
        """Harden keys and values the way harden_input hardens an event."""
        # harden_input's processor ignores the logger and method name it is given.
        return self._harden(None, "", attributes)  # pragma: no mutate — equivalent, see above

    def value(self, value: object) -> object:
        """Harden one value the way harden_input hardens an attribute."""
        return self.attributes({"value": value})["value"]

    def payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run *payload* through the PII engine, honouring the sanitize switch."""
        return self._sanitize_payload(payload, self._sanitize, max_depth=self._pii_depth)

    def text(self, text: str) -> str:
        hardened = str(self.value(text))
        return self._redact_secret_spans(hardened) if self._sanitize else hardened

    def args(self, args: object) -> object:
        """Hardened, sanitized arguments, or None when they cannot be read safely."""
        if isinstance(args, Mapping):
            return self._mapping_args(args)
        if isinstance(args, tuple):
            cleaned = self.payload({"args": self.value(list(args))}).get("args")
            # A list collapsed to the placeholder (too deep, or a cycle) is
            # not arguments any more.
            return tuple(cleaned) if isinstance(cleaned, list) else None
        # LogRecord only ever stores a tuple or a mapping; anything else was
        # put there by hand and is not formatted.
        return None

    def _mapping_args(self, args: Mapping[Any, Any]) -> dict[str, Any] | None:
        # Keys are kept exactly as given so `%(name)s` still finds them; the
        # formatted message is hardened afterwards. A key that is not an exact
        # str cannot be named by a `%(...)s` placeholder anyway, and asking a
        # str subclass or any other object for its text runs caller code.
        try:
            entries = {key: self.value(item) for key, item in args.items() if type(key) is str}
        except Exception:
            return None
        return self.payload(entries)


def _safe_str(value: object) -> str | None:
    try:
        text = str(value)
        text.encode("utf-8")  # pragma: no mutate — codec names are case-insensitive aliases
    except Exception:
        return None
    return text


def _message(record: logging.LogRecord, cleaner: _Cleaner) -> object:
    """The record's message, formatted from cleaned arguments and cleaned again."""
    if not record.args:
        if isinstance(record.msg, dict | list):
            # OTel's handler exports a structured msg as a structured body, so
            # it is sanitized as a structure rather than flattened to text.
            return cleaner.payload({"msg": cleaner.value(record.msg)}).get("msg", _HARDENED_PLACEHOLDER)
        text = _safe_str(record.msg)
        return _HARDENED_PLACEHOLDER if text is None else cleaner.text(text)
    template = _safe_str(record.msg)
    args = cleaner.args(record.args)
    if template is None or args is None:
        return _HARDENED_PLACEHOLDER
    try:
        formatted = template % args
        formatted.encode("utf-8")  # pragma: no mutate — codec names are case-insensitive aliases
    except Exception:
        return _HARDENED_PLACEHOLDER
    return cleaner.text(formatted)


def _extras(record: logging.LogRecord, cleaner: _Cleaner) -> dict[str, Any]:
    custom = {key: value for key, value in record.__dict__.items() if key not in _STANDARD_RECORD_KEYS}
    if not custom:
        return {}
    hardened = cleaner.attributes(custom)
    kept = {key: value for key, value in hardened.items() if key not in _STANDARD_RECORD_KEYS}
    # The PII engine only ever adds `__<key>__class` names, never a standard one.
    return cleaner.payload(kept)


# Set while this thread is sanitizing a foreign record. Sanitizing can redact,
# redacting emits a receipt, and a receipt sink -- LoggingReceiptSink, or a
# host's own -- may log through stdlib, which lands back here. The SDK's own
# receipt line carries the pipeline marker, but a second SDK fan-out on the
# root (the lazy get_logger() path attaches beside what is there) finds it
# already popped. Without this the nested record is sanitized, its digest is
# redacted into another receipt, and the cycle never ends.
class _ThreadState(threading.local):
    # A class attribute rather than a getattr default: every thread starts idle,
    # and the release below deletes the flag rather than storing another falsy
    # value beside it.
    busy = False


_active = _ThreadState()


def sanitize_foreign_record(record: logging.LogRecord) -> logging.LogRecord:
    """A copy of *record* with its message, args and extras hardened and sanitized.

    A record logged *while* this thread is already sanitizing one is not
    sanitized in turn -- that is the receipt cycle -- and fails closed instead.
    """
    clean = copy.copy(record)
    for key in [key for key in clean.__dict__ if key not in _STANDARD_RECORD_KEYS]:
        del clean.__dict__[key]
    clean.args = ()
    clean.msg = _HARDENED_PLACEHOLDER
    if _active.busy:
        return clean
    _active.busy = True
    try:
        cleaner = _Cleaner()
        message = _message(record, cleaner)
        extras = _extras(record, cleaner)
    except Exception:
        return clean
    finally:
        del _active.busy
    clean.msg = message
    clean.__dict__.update(extras)
    return clean
