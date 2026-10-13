# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Plain stdlib records get the hardening and PII sanitization structlog records get.

The fan-out handler sits on the root logger, so ``logging.getLogger("x").info``
from any third-party library reaches the console and the OTLP exporter. Before
this, those records went out untouched: a secret in the message, an argument or
an ``extra`` attribute left the process verbatim.
"""

from __future__ import annotations

import io
import json
import logging
import threading
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from provide.telemetry import pii
from provide.telemetry import receipts as receipts_mod
from provide.telemetry.config import LoggingConfig, SecurityConfig, TelemetryConfig
from provide.telemetry.logger import _foreign_records
from provide.telemetry.logger._foreign_records import sanitize_foreign_record
from provide.telemetry.logger.core import _reset_logging_for_tests, configure_logging
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler
from provide.telemetry.logger.processors import _PIPELINE_RECORD_KEY, _PIPELINE_RECORD_MARKER
from provide.telemetry.logger.sink import clear_log_output, set_log_output

_TOKEN = "ghp_" + "A" * 36  # matches the github_token secret pattern
_AWS = "AKIA" + "B" * 16
_PASSWORD = "hunter2"  # pragma: allowlist secret
_OTHER_PASSWORD = "hunter3"  # pragma: allowlist secret


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        # Attributes as they were when this handler saw the record: a fan-out
        # further up the hierarchy pops its marker off the same object.
        self.attributes: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.attributes.append(dict(record.__dict__))


class _Unprintable:
    def __str__(self) -> str:
        raise RuntimeError("str escaped")


class _ItemsMapping(Mapping[Any, Any]):
    def __init__(self, items: Any) -> None:
        self._items = items

    def __getitem__(self, key: Any) -> Any:
        raise KeyError(key)

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __len__(self) -> int:
        return 1

    def items(self) -> Any:
        if isinstance(self._items, BaseException):
            raise self._items
        return self._items


def _record(msg: object, args: Any = None, **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord("third_party", logging.INFO, __file__, 1, msg, args, None)
    record.__dict__.update(extra)
    return record


def _use_config(monkeypatch: pytest.MonkeyPatch, config: TelemetryConfig) -> None:
    monkeypatch.setattr(_foreign_records, "_get_active_config", lambda: config)


# ── end to end: console and OTel ──────────────────────────────────────────────


@pytest.fixture
def _clean_root() -> Iterator[None]:
    root = logging.getLogger()
    saved, saved_level = list(root.handlers), root.level
    _reset_logging_for_tests()
    yield
    clear_log_output()
    _reset_logging_for_tests()
    root.handlers[:] = saved
    root.setLevel(saved_level)


@pytest.mark.parametrize("fmt", ["json", "console"])
def test_a_third_party_record_is_redacted_on_the_console(_clean_root: None, fmt: str) -> None:
    buffer = io.StringIO()
    set_log_output(buffer)
    configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": fmt}), force=True)
    log = logging.getLogger("third_party")

    log.info("msg " + _TOKEN)
    log.info("arg %s", _AWS)
    log.info("user=%(user)s password=%(password)s", {"user": "bob", "password": _PASSWORD})
    log.info("with extra", extra={"password": _OTHER_PASSWORD, "note": "key " + _TOKEN})

    out = buffer.getvalue()
    for leaked in (_TOKEN, _AWS, _PASSWORD, _OTHER_PASSWORD):
        assert leaked not in out
    assert "msg ***" in out
    assert "arg ***" in out
    assert "user=bob password=***" in out
    assert "with extra" in out


def test_a_pipeline_record_is_not_processed_twice(_clean_root: None) -> None:
    """A rendered JSON line is longer than the attribute cap; a second pass would truncate it."""
    buffer = io.StringIO()
    set_log_output(buffer)
    configure_logging(
        TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "json", "PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH": "40"}),
        force=True,
    )
    from provide.telemetry.logger.core import get_logger

    get_logger("structured").info("app.event.ok", a="x" * 30, b="y" * 30)

    line = json.loads(buffer.getvalue().strip())
    assert line["a"] == "x" * 30
    assert line["b"] == "y" * 30
    assert _PIPELINE_RECORD_KEY not in buffer.getvalue()


@pytest.mark.otel
def test_a_third_party_record_is_redacted_before_the_otel_handler() -> None:
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor

    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    fanout = _BackpressureFanoutHandler([LoggingHandler(level=logging.DEBUG, logger_provider=provider)])
    record = logging.LogRecord("third_party", logging.INFO, __file__, 1, "token=%s user=%s", (_TOKEN, "bob"), None)
    record.__dict__.update({"password": _PASSWORD, "note": "aws " + _AWS})

    fanout.handle(record)
    provider.force_flush()

    (exported,) = exporter.get_finished_logs()
    body = exported.log_record.body
    attributes = dict(exported.log_record.attributes or {})
    assert body == "token=*** user=bob"
    assert attributes["password"] == "***"
    assert attributes["note"] == "aws ***"
    assert _TOKEN not in repr(attributes) and _AWS not in repr(attributes)


def test_a_receipt_logged_through_stdlib_does_not_feed_back_into_redaction(_clean_root: None) -> None:
    """LoggingReceiptSink writes through stdlib logging, so it reaches the fan-out.

    Sanitized as a foreign record, the receipt line's digest looked like a secret,
    was redacted, emitted a receipt of its own, and so on without end.
    """
    buffer = io.StringIO()
    set_log_output(buffer)
    configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "DEBUG"}), force=True)
    receipts_mod._reset_receipts_for_tests()
    with receipts_mod._lock:
        receipts_mod._test_mode = False
    receipts_mod.enable_receipts(
        enabled=True, signing_key="k", service_name="svc", sink=receipts_mod.LoggingReceiptSink()
    )
    try:
        logging.getLogger("third_party").warning("leak %s", _TOKEN)
    finally:
        receipts_mod._reset_receipts_for_tests()

    lines = buffer.getvalue().splitlines()
    assert [line for line in lines if "telemetry.receipt" in line] == [lines[0]]
    assert lines[1] == "leak ***"
    assert len(lines) == 2


class _BoundedReceiptSink(receipts_mod.LoggingReceiptSink):
    """Stops logging receipts after a few, so a broken guard fails the test.

    Without the bound, a guard that no longer holds turns the receipt cycle into
    a loop that never returns, and the test hangs instead of failing.
    """

    def __init__(self) -> None:
        self.calls = 0

    def emit(self, receipt: receipts_mod.RedactionReceipt, /) -> bool:
        self.calls += 1
        return self.calls <= 20 and super().emit(receipt)


def test_a_record_logged_during_sanitization_fails_closed_instead_of_recursing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two SDK fan-outs on the root: the second finds the receipt line's marker gone."""
    first, second = _Capture(), _Capture()
    root = logging.getLogger()
    fanouts = [_BackpressureFanoutHandler([first]), _BackpressureFanoutHandler([second])]
    saved_level = root.level
    for fanout in fanouts:
        root.addHandler(fanout)
    root.setLevel(logging.DEBUG)
    receipts_mod._reset_receipts_for_tests()
    with receipts_mod._lock:
        receipts_mod._test_mode = False
    sink = _BoundedReceiptSink()
    receipts_mod.enable_receipts(enabled=True, signing_key="k", service_name="svc", sink=sink)
    try:
        logging.getLogger("third_party").warning("pw %(password)s", {"password": _PASSWORD})
    finally:
        receipts_mod._reset_receipts_for_tests()
        for fanout in fanouts:
            root.removeHandler(fanout)
        root.setLevel(saved_level)

    first_lines = [record.getMessage() for record in first.records]
    second_lines = [record.getMessage() for record in second.records]
    # Each fan-out sanitizes the third-party record once; the first passes the
    # receipt line through, the second fails it closed instead of looping.
    assert first_lines.count("pw ***") == 1
    assert second_lines.count("pw ***") == 1
    assert sum(line.startswith("telemetry.receipt ") for line in first_lines) == 2
    assert "***" in second_lines
    assert all(_PASSWORD not in line for line in first_lines + second_lines)
    assert sink.calls == 2


def test_the_guard_is_released_after_a_record(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise RuntimeError("sanitizer escaped")

    with monkeypatch.context() as patched:
        patched.setattr(pii, "sanitize_payload", _boom)
        assert sanitize_foreign_record(_record("m %s", ("x",))).msg == "***"
    assert sanitize_foreign_record(_record("m %s", ("x",))).msg == "m x"


def test_a_thread_that_never_sanitized_starts_unguarded() -> None:
    results: list[object] = []
    worker = threading.Thread(target=lambda: results.append(sanitize_foreign_record(_record("m %s", ("x",))).msg))
    worker.start()
    worker.join()
    assert results == ["m x"]


def test_the_receipt_sink_marks_its_record_as_the_sdks_own() -> None:
    capture = _Capture()
    receipts_logger = logging.getLogger("provide.telemetry.receipts")
    receipts_logger.addHandler(capture)
    saved_level = receipts_logger.level
    receipts_logger.setLevel(logging.DEBUG)
    try:
        receipt = receipts_mod.RedactionReceipt("i", "t", "s", "f", "redact", "h" * 64, "m" * 64)
        assert receipts_mod.LoggingReceiptSink().emit(receipt) is True
    finally:
        receipts_logger.removeHandler(capture)
        receipts_logger.setLevel(saved_level)
    (attributes,) = capture.attributes
    assert attributes[_PIPELINE_RECORD_KEY] is _PIPELINE_RECORD_MARKER


# ── fan-out boundary ──────────────────────────────────────────────────────────


def test_fanout_hands_children_a_sanitized_copy_and_leaves_the_original() -> None:
    capture = _Capture()
    record = _record("secret %s", (_TOKEN,), note=_TOKEN)

    _BackpressureFanoutHandler([capture]).handle(record)

    (delivered,) = capture.records
    assert delivered is not record
    assert delivered.getMessage() == "secret ***"
    assert delivered.__dict__["note"] == "***"
    assert record.args == (_TOKEN,)
    assert record.__dict__["note"] == _TOKEN


def test_fanout_passes_a_marked_record_through_untouched_and_drops_the_marker() -> None:
    capture = _Capture()
    record = _record("rendered " + _TOKEN, **{_PIPELINE_RECORD_KEY: _PIPELINE_RECORD_MARKER})

    _BackpressureFanoutHandler([capture]).handle(record)

    (delivered,) = capture.records
    assert delivered is record
    assert delivered.msg == "rendered " + _TOKEN
    assert _PIPELINE_RECORD_KEY not in delivered.__dict__


def test_a_forged_marker_value_does_not_skip_sanitization() -> None:
    capture = _Capture()
    record = _record("forged " + _TOKEN, **{_PIPELINE_RECORD_KEY: object()})

    _BackpressureFanoutHandler([capture]).handle(record)

    (delivered,) = capture.records
    assert delivered.msg == "forged ***"
    assert _PIPELINE_RECORD_KEY not in delivered.__dict__


# ── message without arguments ─────────────────────────────────────────────────


def test_plain_message_is_hardened_and_redacted() -> None:
    clean = sanitize_foreign_record(_record("a\x00b " + _TOKEN))
    assert clean.msg == "ab ***"
    assert clean.args == ()


def test_plain_message_keeps_secrets_when_sanitizing_is_off_but_is_still_hardened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, TelemetryConfig(logging=LoggingConfig(sanitize=False)))
    clean = sanitize_foreign_record(_record("a\x00b " + _TOKEN, None, password=_PASSWORD))
    assert clean.msg == "ab " + _TOKEN
    assert clean.__dict__["password"] == _PASSWORD


def test_plain_message_uses_the_live_length_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(monkeypatch, TelemetryConfig(security=SecurityConfig(max_attr_value_length=5)))
    assert sanitize_foreign_record(_record("abcdef")).msg == "abcde..."
    assert sanitize_foreign_record(_record("abcde")).msg == "abcde"


def test_non_string_message_is_stringified() -> None:
    assert sanitize_foreign_record(_record(12345)).msg == "12345"


def test_structured_message_stays_structured_and_is_sanitized() -> None:
    clean = sanitize_foreign_record(_record({"password": _PASSWORD, "user": "bob", "n": [_TOKEN]}))
    assert clean.msg == {"password": "***", "user": "bob", "n": ["***"]}
    assert sanitize_foreign_record(_record([_TOKEN, "ok"])).msg == ["***", "ok"]


def test_structured_message_dropped_by_a_classification_hook_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pii, "_classification_hook", lambda key, _value: "secret" if key == "msg" else None)
    monkeypatch.setattr(pii, "_policy_hook", lambda _label: "drop")
    assert sanitize_foreign_record(_record({"a": 1})).msg == "***"


def test_unprintable_message_fails_closed() -> None:
    assert sanitize_foreign_record(_record(_Unprintable())).msg == "***"
    assert sanitize_foreign_record(_record(_Unprintable(), ("x",))).msg == "***"


def test_unencodable_message_fails_closed() -> None:
    assert sanitize_foreign_record(_record("lone \ud800")).msg == "***"


# ── positional arguments ──────────────────────────────────────────────────────


def test_tuple_args_are_formatted_from_sanitized_values() -> None:
    clean = sanitize_foreign_record(_record("%s|%s|%d", (_TOKEN, "a\x01b", 7)))
    assert clean.msg == "***|ab|7"
    assert clean.args == ()
    assert clean.getMessage() == "***|ab|7"


def test_secret_assembled_by_formatting_is_redacted() -> None:
    clean = sanitize_foreign_record(_record("ghp_%s", ("A" * 36,)))
    assert clean.msg == "***"


def test_formatted_message_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(monkeypatch, TelemetryConfig(security=SecurityConfig(max_attr_value_length=4)))
    assert sanitize_foreign_record(_record("%s%s", ("ab", "cd"))).msg == "abcd"
    assert sanitize_foreign_record(_record("%s%s", ("ab", "cde"))).msg == "abcd..."


def test_args_that_do_not_fit_the_template_fail_closed() -> None:
    assert sanitize_foreign_record(_record("%s %s", ("one",))).msg == "***"
    assert sanitize_foreign_record(_record("%s", ("a", "b"))).msg == "***"


def test_an_unprintable_argument_fails_closed() -> None:
    assert sanitize_foreign_record(_record("%s", (_Unprintable(),))).msg == "***"


def test_unencodable_formatted_message_fails_closed() -> None:
    assert sanitize_foreign_record(_record("%s", ("\udfff",))).msg == "***"


def test_args_collapsed_by_the_depth_limit_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_config(monkeypatch, TelemetryConfig(security=SecurityConfig(max_nesting_depth=0)))
    assert sanitize_foreign_record(_record("%s", ("x",))).msg == "***"


def test_args_of_an_unexpected_type_fail_closed() -> None:
    record = _record("%s")
    record.args = ["x"]  # type: ignore[assignment]
    assert sanitize_foreign_record(record).msg == "***"


# ── mapping arguments ─────────────────────────────────────────────────────────


def test_mapping_args_redact_sensitive_keys_and_secret_values() -> None:
    clean = sanitize_foreign_record(
        _record("%(user)s %(password)s %(note)s", ({"user": "b\x02ob", "password": _PASSWORD, "note": _AWS},))
    )
    assert clean.msg == "bob *** ***"
    assert clean.args == ()


def test_mapping_args_ignore_keys_that_are_not_exact_strings() -> None:
    class _Key(str):
        pass

    hostile = {_Unprintable(): "x", _Key("k"): "y", "a": "z"}
    assert sanitize_foreign_record(_record("%(a)s", (hostile,))).msg == "z"
    # A placeholder naming a key that was set aside cannot be filled: fail closed.
    assert sanitize_foreign_record(_record("%(k)s", (hostile,))).msg == "***"


@pytest.mark.parametrize(
    "items",
    [RuntimeError("items escaped"), [("only-one",)], [("a", "b", "c")], [object()]],
    ids=["items-raises", "short-entry", "long-entry", "non-iterable-entry"],
)
def test_malformed_mapping_args_fail_closed(items: Any) -> None:
    clean = sanitize_foreign_record(_record("%(a)s", (_ItemsMapping(items),)))
    assert clean.msg == "***"
    assert clean.args == ()


# ── extra attributes ──────────────────────────────────────────────────────────


def test_extras_are_hardened_and_sanitized() -> None:
    clean = sanitize_foreign_record(
        _record("m", None, password=_PASSWORD, note="aws " + _AWS, **{"ke\x00y": "v\x01", "nested": {"token": "t"}})
    )
    assert clean.__dict__["password"] == "***"
    assert clean.__dict__["note"] == "aws ***"
    assert clean.__dict__["key"] == "v"
    assert clean.__dict__["nested"] == {"token": "***"}
    assert "ke\x00y" not in clean.__dict__


def test_extras_use_the_live_pii_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    nested = {"outer": {"password": _PASSWORD}}
    assert sanitize_foreign_record(_record("m", None, **nested)).__dict__["outer"] == {"password": "***"}
    _use_config(monkeypatch, TelemetryConfig(pii_max_depth=1))
    assert sanitize_foreign_record(_record("m", None, **nested)).__dict__["outer"] == {"password": _PASSWORD}


def test_an_extra_that_cleans_to_a_standard_field_cannot_overwrite_it() -> None:
    clean = sanitize_foreign_record(_record("real", None, **{"ms\x00g": "forged", "level\x00no": 99}))
    assert clean.msg == "real"
    assert clean.levelno == logging.INFO


def test_a_record_without_extras_gains_none() -> None:
    record = _record("m")
    clean = sanitize_foreign_record(record)
    assert set(clean.__dict__) == set(record.__dict__)


def test_any_failure_inside_sanitization_fails_the_whole_record_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise RuntimeError("sanitizer escaped")

    monkeypatch.setattr(pii, "sanitize_payload", _boom)
    clean = sanitize_foreign_record(_record("m %s", (_TOKEN,), note=_TOKEN))

    assert clean.msg == "***"
    assert clean.args == ()
    assert "note" not in clean.__dict__
