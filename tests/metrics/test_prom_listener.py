# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The standalone Prometheus listener: web config, TLS, basic auth, lifecycle."""

from __future__ import annotations

import base64
import contextlib
import datetime
import ipaddress
import logging
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import bcrypt
import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.metrics import _prom_listener as listener
from provide.telemetry.metrics import _prom_render as render
from provide.telemetry.metrics import prometheus as prom
from provide.telemetry.metrics.provider import _set_meter_for_test

_PASSWORD = "e2e-test-only-password"  # pragma: allowlist secret — the fixtures' test-only basic-auth password


def _repo_root() -> Path:
    """The directory holding VERSION; mutmut runs these tests from a copy under mutants/."""
    return next(p for p in Path(__file__).resolve().parents if (p / "VERSION").exists())


_CASES: list[dict[str, Any]] = yaml.safe_load(
    (_repo_root() / "spec" / "prometheus_fixtures.yaml").read_text(encoding="utf-8")
)["listener_web_config"]


@pytest.fixture(autouse=True)
def _clean() -> Any:
    listener.stop()
    _set_meter_for_test(None)
    yield
    listener.stop()
    _set_meter_for_test(None)


class _Reader:
    def snapshot(self) -> None:
        return None


def _ready() -> None:
    prom.mark_ready(_Reader(), render.RenderOptions("UnderscoreEscapingWithSuffixes"))


# ── a throwaway PKI ─────────────────────────────────────────────────────────


class _PKI:
    def __init__(self, tmp: Path) -> None:
        self.dir = tmp
        now = datetime.datetime.now(datetime.UTC)
        self._now = now
        self.ca_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")])
        ski = x509.SubjectKeyIdentifier.from_public_key(self.ca_key.public_key())
        self.ca = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self.ca_key.public_key())
            .serial_number(1)
            .not_valid_before(now - datetime.timedelta(hours=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(ski, critical=False)
            .sign(self.ca_key, hashes.SHA256())
        )
        self.ca_file = self._write("ca.crt", self.ca.public_bytes(serialization.Encoding.PEM))
        self.cert_file, self.key_file = self.issue("server", ExtendedKeyUsageOID.SERVER_AUTH)
        self.client_cert, self.client_key = self.issue("client", ExtendedKeyUsageOID.CLIENT_AUTH)

    def _write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def issue(self, name: str, usage: x509.ObjectIdentifier) -> tuple[Path, Path]:
        key = ec.generate_private_key(ec.SECP256R1())
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(self.ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self._now - datetime.timedelta(hours=1))
            .not_valid_after(self._now + datetime.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                critical=False,
            )
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.ca_key.public_key()), critical=False)
            .sign(self.ca_key, hashes.SHA256())
        )
        key_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        return self._write(f"{name}.crt", cert.public_bytes(serialization.Encoding.PEM)), self._write(
            f"{name}.key", key_pem
        )


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> _PKI:
    return _PKI(tmp_path_factory.mktemp("pki"))


def _write_config(tmp: Path, pki: _PKI, config: dict[str, Any]) -> str:
    hashed = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    text = (
        yaml.safe_dump(config)
        .replace("'{cert}'", str(pki.cert_file))
        .replace("'{key}'", str(pki.key_file))
        .replace("'{ca}'", str(pki.ca_file))
        .replace("'{missing}'", str(tmp / "missing.pem"))
        .replace("bcrypt_of_e2e_test_only_password", f"'{hashed}'")
    )
    path = tmp / "web.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _config(**env: str) -> TelemetryConfig:
    base = {
        "OTEL_METRICS_EXPORTER": "prometheus",
        "PROVIDE_METRICS_PROMETHEUS_LISTEN": "true",
        "OTEL_EXPORTER_PROMETHEUS_PORT": "0",
    }
    return TelemetryConfig.from_env({**base, **env})


def _start(**env: str) -> list[str]:
    reports: list[str] = []
    listener.sync(_config(**env), reports.append)
    return reports


def _get(
    url: str, *, pki: _PKI | None = None, client_cert: bool = False, auth: bool = False, method: str = "GET"
) -> int:
    context = None
    if pki is not None:
        context = ssl.create_default_context(cafile=str(pki.ca_file))
        if client_cert:
            context.load_cert_chain(pki.client_cert, pki.client_key)
    request = urllib.request.Request(url, method=method)
    if auth:
        request.add_header("Authorization", "Basic " + base64.b64encode(f"e2e:{_PASSWORD}".encode()).decode())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    # Bound to a name so the text-I/O encoding check does not read this HTTP
    # request as a file open().
    fetch = opener.open
    try:
        with fetch(request, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _url(scheme: str = "http", path: str = "/metrics") -> str:
    bound = listener.address()
    assert bound is not None
    return f"{scheme}://127.0.0.1:{bound[1]}{path}"


# ── the shared web config cases ─────────────────────────────────────────────


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_web_config_fixture(case: dict[str, Any], pki: _PKI, tmp_path: Path) -> None:
    _ready()
    path = ""
    if case.get("web_config_path"):
        path = case["web_config_path"].replace("{missing}", str(tmp_path / "missing.yml"))
    elif case.get("web_config") is not None:
        path = _write_config(tmp_path, pki, case["web_config"])
    reports = _start(PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG=path)
    assert (listener.address() is not None) is case["listener"]
    if case.get("error"):
        assert len(reports) == 1 and reports[0].startswith("prometheus listener: ")
        return
    assert reports == []
    https = case["scheme"] == "https"
    url = _url(case["scheme"])
    if case.get("client_cert_required"):
        with pytest.raises((urllib.error.URLError, ssl.SSLError, ConnectionError)):
            _get(url, pki=pki)
    client_cert = bool(case.get("client_cert_required"))
    if case.get("auth"):
        assert _get(url, pki=pki if https else None, client_cert=client_cert) == 401
    assert _get(url, pki=pki if https else None, client_cert=client_cert, auth=bool(case.get("auth"))) == 200


# ── requests ────────────────────────────────────────────────────────────────


def test_paths_methods_and_query_strings() -> None:
    _ready()
    _start(PROVIDE_METRICS_PROMETHEUS_PATH="/internal/metrics")
    assert _get(_url(path="/internal/metrics")) == 200
    assert _get(_url(path="/internal/metrics?debug=1")) == 200
    assert _get(_url(path="/metrics")) == 404
    assert _get(_url(path="/internal/metrics/x")) == 404
    assert _get(_url(path="/internal/metrics"), method="HEAD") == 200
    for method in ("POST", "PUT", "DELETE"):
        assert _get(_url(path="/internal/metrics"), method=method) == 405


def test_not_ready_is_served_as_503() -> None:
    _start()
    assert _get(_url()) == 503


def test_failed_tls_handshake_does_not_stop_the_listener(pki: _PKI, tmp_path: Path) -> None:
    _ready()
    _start(
        PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG=_write_config(
            tmp_path, pki, {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}"}}
        )
    )
    bound = listener.address()
    assert bound is not None
    with socket.create_connection(("127.0.0.1", bound[1]), timeout=5) as raw:
        raw.sendall(b"GET /metrics HTTP/1.1\r\n\r\n")  # plain HTTP to a TLS port
        with contextlib.suppress(ConnectionError):  # the server drops the failed handshake
            raw.recv(1024)
    assert _get(_url("https"), pki=pki) == 200


# ── lifecycle ───────────────────────────────────────────────────────────────


def test_keeps_restarts_and_stops() -> None:
    _start()
    first = listener._running
    _start()
    assert listener._running is first
    _start(PROVIDE_METRICS_PROMETHEUS_PATH="/other")
    assert listener._running is not first and listener._running is not None
    listener.sync(TelemetryConfig.from_env({}), lambda _msg: None)
    assert listener.address() is None
    listener.stop()  # stopping twice is a no-op


def test_bind_failure_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with caplog.at_level(logging.WARNING, logger=listener.__name__):
            reports = _start(OTEL_EXPORTER_PROMETHEUS_PORT=str(busy.getsockname()[1]))
    assert listener.address() is None
    assert len(reports) == 1 and reports[0].startswith("prometheus listener: ")
    assert [r.message for r in caplog.records] == ["metrics.prometheus_listener.failed"]


def test_ipv6_loopback() -> None:
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    try:
        reports = _start(OTEL_EXPORTER_PROMETHEUS_HOST="::1")
    except OSError:
        pytest.skip("IPv6 loopback unavailable")
    if reports:
        pytest.skip(f"IPv6 loopback unavailable: {reports}")
    assert listener._running is not None and listener._running.server.address_family == socket.AF_INET6


@pytest.mark.parametrize(
    ("host", "loopback"),
    [("localhost", True), ("127.0.0.1", True), ("::1", True), ("0.0.0.0", False), ("example.com", False)],
)
def test_is_loopback(host: str, loopback: bool) -> None:
    assert listener._is_loopback(host) is loopback


def test_address_family() -> None:
    assert listener._family("::1") == socket.AF_INET6
    assert listener._family("fe80::1%eth0") == socket.AF_INET6
    assert listener._family("127.0.0.1") == socket.AF_INET
    assert listener._family("localhost") == socket.AF_INET


def test_exposure_warnings(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=listener.__name__):
        listener._warn_exposure("0.0.0.0", listener.WebSecurity(users={"u": b"h"}))
        listener._warn_exposure("127.0.0.1", listener.WebSecurity())
    assert [r.message for r in caplog.records] == [
        "metrics.prometheus_listener.exposed",
        "metrics.prometheus_listener.cleartext_auth",
    ]


def test_setup_and_shutdown_drive_the_listener(pki: _PKI, tmp_path: Path) -> None:
    from provide.telemetry import get_health_snapshot, setup_telemetry, shutdown_telemetry
    from provide.telemetry.setup import _reset_all_for_tests

    _reset_all_for_tests()
    try:
        setup_telemetry(_config(PROVIDE_TRACE_ENABLED="false"))
        assert listener.address() is not None
        shutdown_telemetry()
        assert listener.address() is None
        _reset_all_for_tests()
        bad = _write_config(tmp_path, pki, {"unknown_key": 1})
        setup_telemetry(_config(PROVIDE_TRACE_ENABLED="false", PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG=bad))
        assert listener.address() is None
        assert (get_health_snapshot().setup_error or "").startswith("prometheus listener: web config")
    finally:
        shutdown_telemetry()
        _reset_all_for_tests()


# ── certificate rotation ────────────────────────────────────────────────────


def test_rotated_certificate_is_picked_up_and_a_broken_one_fails(pki: _PKI, tmp_path: Path) -> None:
    cert, key = tmp_path / "s.crt", tmp_path / "s.key"
    cert.write_bytes(pki.cert_file.read_bytes())
    key.write_bytes(pki.key_file.read_bytes())
    reloader = listener._TLSReloader(cert, key, None, ssl.CERT_NONE, ssl.TLSVersion.TLSv1_2)
    first = reloader.context()
    assert reloader.context() is first
    new_cert, new_key = pki.issue("rotated", ExtendedKeyUsageOID.SERVER_AUTH)
    cert.write_bytes(new_cert.read_bytes())
    key.write_bytes(new_key.read_bytes())
    later = os.stat(cert).st_mtime_ns + 10**9
    os.utime(cert, ns=(later, later))
    assert reloader.context() is not first
    key.write_bytes(b"garbage")
    os.utime(key, ns=(later + 10**9, later + 10**9))
    with pytest.raises(ssl.SSLError):
        reloader.context()


# ── web config validation ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ([1, 2], "only ['basic_auth_users', 'tls_server_config'] are supported"),
        ({"tls_server_config": "x"}, "tls_server_config: only"),
        ({"tls_server_config": {"cert_file": "{cert}", "cipher_suites": []}}, "tls_server_config: only"),
        ({"tls_server_config": {"cert_file": "{cert}"}}, "needs cert_file and key_file"),
        (
            {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}", "min_version": "TLS10"}},
            "want TLS12 or TLS13",
        ),
        (
            {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}", "client_auth_type": "Sometimes"}},
            "is not supported",
        ),
        (
            {
                "tls_server_config": {
                    "cert_file": "{cert}",
                    "key_file": "{key}",
                    "client_auth_type": "VerifyClientCertIfGiven",
                }
            },
            "needs client_ca_file",
        ),
        ({"tls_server_config": {"cert_file": "{cert}", "key_file": "{missing}"}}, "tls_server_config: "),
        ({"basic_auth_users": ["e2e"]}, "must map user names to bcrypt hashes"),
        ({"basic_auth_users": {"e2e": "plaintext"}}, "basic_auth_users[e2e] is not a bcrypt hash"),
    ],
)
def test_invalid_web_configs_are_rejected(config: Any, message: str, pki: _PKI, tmp_path: Path) -> None:
    with pytest.raises(listener.WebConfigError) as excinfo:
        listener.load_web_config(_write_config(tmp_path, pki, config))
    assert message in str(excinfo.value)


def test_unreadable_and_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(listener.WebConfigError, match="web config"):
        listener.load_web_config(str(tmp_path / "absent.yml"))
    broken = tmp_path / "broken.yml"
    broken.write_text("tls_server_config: [unclosed\n", encoding="utf-8")
    with pytest.raises(listener.WebConfigError, match="web config"):
        listener.load_web_config(str(broken))


def test_the_credential_cache_is_keyed_per_config_and_never_shown() -> None:
    first, second = listener.WebSecurity(), listener.WebSecurity()
    assert len(first._cache_key) == 32
    assert first._cache_key != second._cache_key
    assert first._cache_key.hex() not in repr(first)
    assert "_cache_key" not in repr(first)


def test_empty_file_and_empty_users_mean_no_security(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yml"
    empty.write_text("", encoding="utf-8")
    assert listener.load_web_config(str(empty)) == listener.WebSecurity()
    no_users = tmp_path / "no-users.yml"
    no_users.write_text("basic_auth_users: {}\n", encoding="utf-8")
    assert listener.load_web_config(str(no_users)).users == {}


def test_relative_paths_and_optional_tls_settings(pki: _PKI) -> None:
    config = pki.dir / "relative.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "tls_server_config": {
                    "cert_file": pki.cert_file.name,
                    "key_file": pki.key_file.name,
                    "client_ca_file": pki.ca_file.name,
                    "client_auth_type": "VerifyClientCertIfGiven",
                    "min_version": "TLS13",
                }
            }
        ),
        encoding="utf-8",
    )
    security = listener.load_web_config(str(config))
    assert security.tls is not None
    context = security.tls.context()
    assert context.minimum_version == ssl.TLSVersion.TLSv1_3
    assert context.verify_mode == ssl.CERT_OPTIONAL


@pytest.mark.parametrize("module", ["yaml", "bcrypt"])
def test_missing_optional_dependencies_fail_closed(
    module: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "web.yml"
    config.write_text("basic_auth_users: {e2e: '$2b$04$abcdefghijklmnopqrstuv'}\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(listener.WebConfigError, match=r"install provide-telemetry\[prometheus\]"):
        listener.load_web_config(str(config))


# ── basic auth ──────────────────────────────────────────────────────────────


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_authorization_header_handling() -> None:
    security = listener.WebSecurity(users={"e2e": bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4))})
    assert listener.WebSecurity().authorized(None) is True
    assert security.authorized(None) is False
    assert security.authorized("Bearer abc") is False
    assert security.authorized("Basic !!!") is False
    assert security.authorized("Basic " + base64.b64encode(b"\xff\xfe").decode()) is False
    assert security.authorized("Basic " + base64.b64encode(b"no-colon").decode()) is False
    assert security.authorized(_basic("nobody", _PASSWORD)) is False
    assert security.authorized(_basic("e2e", "wrong")) is False
    assert security.authorized("basic " + base64.b64encode(f"e2e:{_PASSWORD}".encode()).decode()) is True
    assert len(security._verified) == 1
    assert security.authenticate("e2e", _PASSWORD) is True  # from the cache this time


def test_dummy_hash_is_a_real_bcrypt_hash() -> None:
    assert bcrypt.checkpw(b"anything", listener._DUMMY_HASH) is False


def test_address_is_none_when_stopped() -> None:
    assert listener.address() is None


# ── exact responses and details ─────────────────────────────────────────────


def _raw(method: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    import http.client

    bound = listener.address()
    assert bound is not None
    connection = http.client.HTTPConnection("127.0.0.1", bound[1], timeout=5)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def test_exact_error_responses() -> None:
    _ready()
    hashed = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4))
    _start()
    assert listener._running is not None
    status, headers, body = _raw("GET", "/nope")
    assert (status, body) == (404, b"not found\n")
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert headers["content-length"] == "10"
    status, headers, body = _raw("POST", "/metrics")
    assert (status, headers["allow"], body) == (405, "GET, HEAD", b"method not allowed\n")
    for method in ("PATCH", "DELETE", "PUT"):
        assert _raw(method, "/metrics")[0] == 405
    listener._running.server.security.users = {"e2e": hashed}
    status, headers, body = _raw("GET", "/metrics")
    assert (status, headers["www-authenticate"], body) == (401, "Basic", b"unauthorized\n")
    assert headers["content-type"] == "text/plain; charset=utf-8"
    status, headers, body = _raw("GET", "/metrics", {"Authorization": _basic("e2e", _PASSWORD)})
    assert status == 200 and headers["content-length"] == str(len(body))
    status, headers, _ = _raw(
        "GET",
        "/metrics",
        {"Authorization": _basic("e2e", _PASSWORD), "Accept": "text/plain;version=1.0.0;escaping=allow-utf-8"},
    )
    assert headers["content-type"] == render.CONTENT_TYPE_UTF8


def test_listener_thread_and_address(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=listener.__name__):
        _start()
    assert caplog.records == []  # loopback without users: nothing to warn about
    running = listener._running
    assert running is not None
    assert running.thread.daemon is True
    assert running.thread.name == "provide-prometheus-listener"
    assert running.server.address_family == socket.AF_INET
    assert running.server.daemon_threads is True
    bound = listener.address()
    assert bound is not None and bound[0] == "127.0.0.1" and isinstance(bound[1], int) and bound[1] > 0
    assert listener._Handler.timeout == listener.READ_TIMEOUT_SECONDS == 10.0


def test_slow_client_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    _ready()
    monkeypatch.setattr(listener._Handler, "timeout", 0.2)
    _start()
    bound = listener.address()
    assert bound is not None
    with socket.create_connection(("127.0.0.1", bound[1]), timeout=5) as raw:
        raw.sendall(b"GET /metrics HTTP/1.1\r\n")  # never finishes the headers
        assert raw.recv(1024) == b""  # the server closed it after the read timeout


def test_failure_and_exposure_log_extras(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    with caplog.at_level(logging.WARNING, logger=listener.__name__):
        reports = _start(PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG=str(tmp_path / "absent.yml"))
        listener._warn_exposure("0.0.0.0", listener.WebSecurity())
        listener._warn_exposure("127.0.0.1", listener.WebSecurity(users={"u": b"h"}, tls=cast(Any, object())))
    failed, exposed = caplog.records
    assert failed.levelno == exposed.levelno == logging.WARNING
    assert reports == [f"prometheus listener: {failed.__dict__['error']}"]
    assert str(tmp_path / "absent.yml") in failed.__dict__["error"]
    assert exposed.message == "metrics.prometheus_listener.exposed"
    assert exposed.__dict__["host"] == "0.0.0.0"


def test_tls_reloader_builds_a_server_context(pki: _PKI) -> None:
    reloader = listener._TLSReloader(
        pki.cert_file, pki.key_file, pki.ca_file, ssl.CERT_REQUIRED, ssl.TLSVersion.TLSv1_2
    )
    initial = reloader._context
    context = reloader.context()
    assert context is initial  # built once in __init__; unchanged files are not rebuilt
    assert context.protocol == ssl.PROTOCOL_TLS_SERVER
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()["x509_ca"] == 1


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"basic_auth_users": ["e2e"]}, "web config {path}: basic_auth_users must map user names to bcrypt hashes"),
        ({"basic_auth_users": {"e2e": "x"}}, "web config {path}: basic_auth_users[e2e] is not a bcrypt hash"),
        ({"other": 1}, "web config {path}: only ['basic_auth_users', 'tls_server_config'] are supported"),
        (
            {"tls_server_config": {"cert_file": "a"}},
            "tls_server_config needs cert_file and key_file",
        ),
        (
            {"tls_server_config": {"key_file": "a"}},
            "tls_server_config needs cert_file and key_file",
        ),
        (
            {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}", "min_version": "TLS11"}},
            "tls_server_config.min_version 'TLS11': want TLS12 or TLS13",
        ),
        (
            {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}", "client_auth_type": "X"}},
            "tls_server_config.client_auth_type 'X' is not supported",
        ),
        (
            {
                "tls_server_config": {
                    "cert_file": "{cert}",
                    "key_file": "{key}",
                    "client_auth_type": "RequireAndVerifyClientCert",
                }
            },
            "tls_server_config.client_auth_type RequireAndVerifyClientCert needs client_ca_file",
        ),
        (
            {"tls_server_config": {"x": 1}},
            "tls_server_config: only ['cert_file', 'client_auth_type', 'client_ca_file', 'key_file', 'min_version']"
            " are supported",
        ),
    ],
)
def test_exact_web_config_messages(config: Any, message: str, pki: _PKI, tmp_path: Path) -> None:
    path = _write_config(tmp_path, pki, config)
    with pytest.raises(listener.WebConfigError) as excinfo:
        listener.load_web_config(path)
    assert str(excinfo.value) == message.format(path=path)


def test_tls_defaults(pki: _PKI, tmp_path: Path) -> None:
    plain = listener.load_web_config(
        _write_config(tmp_path, pki, {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}"}})
    )
    assert plain.tls is not None and plain.users == {}
    context = plain.tls.context()
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_NONE
    mtls = listener.load_web_config(
        _write_config(
            tmp_path, pki, {"tls_server_config": {"cert_file": "{cert}", "key_file": "{key}", "client_ca_file": "{ca}"}}
        )
    )
    assert mtls.tls is not None and mtls.tls.context().verify_mode == ssl.CERT_REQUIRED


# ── the handler, run in the test's own thread ───────────────────────────────
# mutmut attributes code to tests only when it runs in the test's thread, and
# the listener serves from its own; these drive _Handler directly.


def _handle(request: bytes, *, users: dict[str, bytes] | None = None, path: str = "/metrics") -> bytes:
    import types

    server: Any = types.SimpleNamespace(metrics_path=path, security=listener.WebSecurity(users=users or {}))
    ours, theirs = socket.socketpair()
    with ours, theirs:
        ours.sendall(request)
        listener._Handler(theirs, ("test", 0), server)
        theirs.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := ours.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def _head_and_body(response: bytes) -> tuple[list[str], bytes]:
    head, _, body = response.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    return [lines[0]] + [line for line in lines[1:] if not line.startswith(("Server:", "Date:"))], body


def test_handler_not_found_in_thread() -> None:
    lines, body = _head_and_body(_handle(b"GET /other HTTP/1.0\r\n\r\n"))
    assert lines == ["HTTP/1.0 404 Not Found", "content-type: text/plain; charset=utf-8", "Content-Length: 10"]
    assert body == b"not found\n"


def test_handler_unauthorized_and_authorized_in_thread() -> None:
    users = {"e2e": bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4))}
    lines, body = _head_and_body(_handle(b"GET /metrics HTTP/1.0\r\n\r\n", users=users))
    assert lines == [
        "HTTP/1.0 401 Unauthorized",
        "www-authenticate: Basic",
        "content-type: text/plain; charset=utf-8",
        "Content-Length: 13",
    ]
    assert body == b"unauthorized\n"
    _ready()
    request = f"GET /metrics?x=1 HTTP/1.0\r\nAuthorization: {_basic('e2e', _PASSWORD)}\r\n\r\n".encode()
    lines, body = _head_and_body(_handle(request, users=users))
    assert lines[0] == "HTTP/1.0 200 OK"
    assert f"content-type: {render.CONTENT_TYPE_TEXT}" in lines
    assert f"Content-Length: {len(body)}" in lines
    assert b"# TYPE provide_telemetry_setup_error gauge\n" in body


def test_handler_methods_and_accept_in_thread() -> None:
    _ready()
    lines, body = _head_and_body(
        _handle(b"GET /metrics HTTP/1.0\r\nAccept: text/plain;version=1.0.0;escaping=allow-utf-8\r\n\r\n")
    )
    assert f"content-type: {render.CONTENT_TYPE_UTF8}" in lines and body
    lines, body = _head_and_body(_handle(b"HEAD /metrics HTTP/1.0\r\n\r\n"))
    assert lines[0] == "HTTP/1.0 200 OK" and "Content-Length: 0" in lines and body == b""
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        lines, body = _head_and_body(_handle(f"{method} /metrics HTTP/1.0\r\n\r\n".encode()))
        assert lines[0] == "HTTP/1.0 405 Method Not Allowed" and "allow: GET, HEAD" in lines
        assert body == b"method not allowed\n"
    assert _head_and_body(_handle(b"GET /metrics HTTP/1.0\r\n\r\n", path="/elsewhere"))[0][0].endswith("404 Not Found")


def test_handler_wraps_tls_in_thread(pki: _PKI) -> None:
    import threading
    import types

    _ready()
    reloader = listener._TLSReloader(pki.cert_file, pki.key_file, None, ssl.CERT_NONE, ssl.TLSVersion.TLSv1_2)
    server: Any = types.SimpleNamespace(metrics_path="/metrics", security=listener.WebSecurity(tls=reloader))
    ours, theirs = socket.socketpair()
    received: list[bytes] = []

    def client() -> None:
        context = ssl.create_default_context(cafile=str(pki.ca_file))
        with context.wrap_socket(ours, server_hostname="localhost") as tls:
            tls.sendall(b"GET /metrics HTTP/1.0\r\n\r\n")
            while chunk := tls.recv(65536):
                received.append(chunk)

    thread = threading.Thread(target=client)
    thread.start()
    with theirs:
        handler = listener._Handler(theirs, ("test", 0), server)
        assert isinstance(handler.request, ssl.SSLSocket)
        handler.request.close()  # EOF for the client
    thread.join(5)
    assert b"".join(received).startswith(b"HTTP/1.0 200 OK\r\n")
