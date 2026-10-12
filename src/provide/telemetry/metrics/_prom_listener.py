# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Tier 3 standalone Prometheus listener.

Serves prometheus.response_for at PROVIDE_METRICS_PROMETHEUS_PATH on
OTEL_EXPORTER_PROMETHEUS_HOST:PORT, optionally secured by a Prometheus web
config (TLS, client certificates, bcrypt basic auth) restricted to the keys
prometheus_metrics.listener_security lists. It fails closed: any problem with
the web config keeps it from starting. Failures are logged and recorded as the
health snapshot's setup_error; they never fail setup.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import socket
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from provide.telemetry.metrics import prometheus

_logger = logging.getLogger(__name__)

READ_TIMEOUT_SECONDS = 10.0
INSTALL_HINT = "install provide-telemetry[prometheus] to use PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG"

_TOP_KEYS = frozenset({"tls_server_config", "basic_auth_users"})
_TLS_KEYS = frozenset({"cert_file", "key_file", "client_ca_file", "client_auth_type", "min_version"})
_CLIENT_AUTH = {
    "NoClientCert": ssl.CERT_NONE,
    "RequireAndVerifyClientCert": ssl.CERT_REQUIRED,
    "VerifyClientCertIfGiven": ssl.CERT_OPTIONAL,
}
_MIN_VERSIONS = {"TLS12": ssl.TLSVersion.TLSv1_2, "TLS13": ssl.TLSVersion.TLSv1_3}
# Compared against when the user is unknown, so a wrong user name costs the same
# as a wrong password. Any well-formed cost-10 hash will do.
_CACHE_KEY_BYTES = 32  # pragma: no mutate — any key length works; 32 bytes matches SHA-256
_DUMMY_HASH = b"$2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq"
# bcrypt.checkpw raises ValueError for a malformed hash whatever the password.
_HASH_PROBE = b""

_AUTHORIZATION = "Authorization"
_ACCEPT = "Accept"
_PLAIN_TEXT = (b"content-type", b"text/plain; charset=utf-8")
_NOT_FOUND = (404, [_PLAIN_TEXT], b"not found\n")
_UNAUTHORIZED = (401, [(b"www-authenticate", b"Basic"), _PLAIN_TEXT], b"unauthorized\n")


class WebConfigError(Exception):
    """The web config cannot be used; the listener must not start."""


class _TLSReloader:
    """Builds the server SSLContext, rebuilding it when the cert or key file changes."""

    def __init__(
        self, cert: Path, key: Path, ca: Path | None, verify_mode: ssl.VerifyMode, minimum: ssl.TLSVersion
    ) -> None:
        self._cert, self._key, self._ca = cert, key, ca
        self._verify_mode, self._minimum = verify_mode, minimum
        self._lock = threading.Lock()
        self._stamp = self._mtimes()
        self._context = self._build()

    def _mtimes(self) -> tuple[int, int]:
        return os.stat(self._cert).st_mtime_ns, os.stat(self._key).st_mtime_ns

    def _build(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = self._minimum
        context.load_cert_chain(self._cert, self._key)
        if self._ca is not None:
            context.load_verify_locations(self._ca)
        context.verify_mode = self._verify_mode
        return context

    def context(self) -> ssl.SSLContext:
        """The current context; checked on each new connection, so rotation needs no restart."""
        with self._lock:
            stamp = self._mtimes()
            if stamp != self._stamp:
                self._context, self._stamp = self._build(), stamp
            return self._context


@dataclass
class WebSecurity:
    users: dict[str, bytes] = field(default_factory=dict)
    tls: _TLSReloader | None = None
    _verified: set[bytes] = field(default_factory=set)  # _cache_digest(user, password) of successful checks
    # Keys the verified-credentials cache. A plain hash of user and password in
    # memory could be guessed at hash speed, far faster than bcrypt; a keyed one
    # cannot be without this key, which never leaves the process.
    _cache_key: bytes = field(default_factory=lambda: secrets.token_bytes(_CACHE_KEY_BYTES), compare=False, repr=False)

    def authorized(self, header: str | None) -> bool:
        """Whether an Authorization header satisfies basic auth (always, with no users)."""
        if not self.users:
            return True
        scheme, _, encoded = (header or "").partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            user, sep, password = base64.b64decode(encoded, validate=True).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return False
        return bool(sep) and self.authenticate(user, password)

    def authenticate(self, user: str, password: str) -> bool:
        import bcrypt

        digest = hmac.new(self._cache_key, f"{user}\0{password}".encode(), hashlib.sha256).digest()
        if digest in self._verified:
            return True
        hashed = self.users.get(user)
        if hashed is None:
            bcrypt.checkpw(password.encode(), _DUMMY_HASH)
            return False
        if not bcrypt.checkpw(password.encode(), hashed):
            return False
        self._verified.add(digest)
        return True


def load_web_config(path: str) -> WebSecurity:
    """Read and validate a web config file; any problem raises WebConfigError."""
    try:
        import yaml
    except ImportError:
        raise WebConfigError(INSTALL_HINT) from None
    config_path = Path(path)
    try:
        data = yaml.safe_load(config_path.read_bytes())
    except (OSError, yaml.YAMLError) as exc:
        raise WebConfigError(f"web config {path}: {exc}") from None
    if data is None:
        return WebSecurity()
    if not isinstance(data, dict) or set(data) - _TOP_KEYS:
        raise WebConfigError(f"web config {path}: only {sorted(_TOP_KEYS)} are supported")
    return WebSecurity(
        users=_users(data.get("basic_auth_users") or {}, path),
        tls=_tls(data["tls_server_config"], config_path.parent) if "tls_server_config" in data else None,
    )


def _users(raw: Any, path: str) -> dict[str, bytes]:
    if not isinstance(raw, dict):
        raise WebConfigError(f"web config {path}: basic_auth_users must map user names to bcrypt hashes")
    if not raw:
        return {}
    try:
        import bcrypt
    except ImportError:
        raise WebConfigError(INSTALL_HINT) from None
    users = {}
    for user, hashed in raw.items():
        encoded = str(hashed).encode()
        try:
            bcrypt.checkpw(_HASH_PROBE, encoded)
        except ValueError:
            raise WebConfigError(f"web config {path}: basic_auth_users[{user}] is not a bcrypt hash") from None
        users[str(user)] = encoded
    return users


def _tls(raw: Any, base: Path) -> _TLSReloader:
    if not isinstance(raw, dict) or set(raw) - _TLS_KEYS:
        raise WebConfigError(f"tls_server_config: only {sorted(_TLS_KEYS)} are supported")
    if not raw.get("cert_file") or not raw.get("key_file"):
        raise WebConfigError("tls_server_config needs cert_file and key_file")
    min_version = raw.get("min_version") or "TLS12"
    minimum = _MIN_VERSIONS.get(min_version)
    if minimum is None:
        raise WebConfigError(f"tls_server_config.min_version {min_version!r}: want TLS12 or TLS13")
    ca_file = raw.get("client_ca_file")
    auth_name = raw.get("client_auth_type") or ("RequireAndVerifyClientCert" if ca_file else "NoClientCert")
    verify_mode = _CLIENT_AUTH.get(auth_name)
    if verify_mode is None:
        raise WebConfigError(f"tls_server_config.client_auth_type {auth_name!r} is not supported")
    if verify_mode != ssl.CERT_NONE and not ca_file:
        raise WebConfigError(f"tls_server_config.client_auth_type {auth_name} needs client_ca_file")
    try:
        return _TLSReloader(
            base / raw["cert_file"], base / raw["key_file"], base / ca_file if ca_file else None, verify_mode, minimum
        )
    except (OSError, ssl.SSLError) as exc:
        raise WebConfigError(f"tls_server_config: {exc}") from None


def _family(host: str) -> socket.AddressFamily:
    return socket.AF_INET6 if ":" in host else socket.AF_INET


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], path: str, security: WebSecurity) -> None:
        self.metrics_path = path
        self.security = security
        self.address_family = _family(address[0])
        super().__init__(address, _Handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A failed handshake or a dropped client is not worth a traceback on stderr."""
        del request, client_address


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    timeout = READ_TIMEOUT_SECONDS  # applied to the connection by StreamRequestHandler.setup

    def setup(self) -> None:
        # Runs in the per-connection thread, so a slow TLS handshake cannot stall accept().
        tls = self.server.security.tls
        if tls is not None:
            self.request = tls.context().wrap_socket(self.request, server_side=True)
        super().setup()

    def _dispatch(self) -> None:
        if urlsplit(self.path).path != self.server.metrics_path:
            self._send(*_NOT_FOUND)
        elif not self.server.security.authorized(self.headers.get(_AUTHORIZATION)):
            self._send(*_UNAUTHORIZED)
        else:
            self._send(*prometheus.response_for(self.command, self.headers.get(_ACCEPT)))

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = _dispatch

    def _send(self, status: int, headers: list[tuple[bytes, bytes]], body: bytes) -> None:
        self.send_response(status)
        for name, value in headers:
            self.send_header(name.decode(), value.decode())
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # the signature is http.server's
        """Scrapes are not logged; Prometheus records its own scrape results."""


@dataclass
class _Running:
    key: tuple[str, int, str, str]
    server: _Server
    thread: threading.Thread


_lock = threading.Lock()
_running: _Running | None = None


def sync(config: Any, report: Callable[[str], None]) -> None:
    """Make the listener match config: start, stop, restart on a changed key, or leave it."""
    global _running
    with _lock:
        if not config.metrics.prometheus_listener_enabled:
            _stop_locked()
            return
        p = config.metrics.prometheus
        key = (p.host, p.port, p.path, p.web_config)
        if _running is not None and _running.key == key:
            return
        _stop_locked()
        try:
            _running = _start(key)
        except (WebConfigError, OSError) as exc:
            report(f"prometheus listener: {exc}")
            _logger.warning("metrics.prometheus_listener.failed", extra={"error": str(exc)})


def _start(key: tuple[str, int, str, str]) -> _Running:
    host, port, path, web_config = key
    security = load_web_config(web_config) if web_config else WebSecurity()
    server = _Server((host, port), path, security)
    _warn_exposure(host, security)
    thread = threading.Thread(target=server.serve_forever, name="provide-prometheus-listener", daemon=True)  # fmt: skip  # pragma: no mutate — without serve_forever running, server.shutdown() waits forever, so mutmut can only see a timeout; the name and daemon flag are asserted by test_listener_thread_and_address
    thread.start()
    return _Running(key, server, thread)


def _warn_exposure(host: str, security: WebSecurity) -> None:
    if not _is_loopback(host):
        _logger.warning("metrics.prometheus_listener.exposed", extra={"host": host})
    if security.users and security.tls is None:
        _logger.warning("metrics.prometheus_listener.cleartext_auth")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _stop_locked() -> None:
    global _running
    if _running is None:
        return
    _running.server.shutdown()  # returns once serve_forever has stopped
    _running.server.server_close()
    _running.thread.join()
    _running = None


def stop() -> None:
    with _lock:
        _stop_locked()


def address() -> tuple[str, int] | None:
    """The bound (host, port) of the running listener, or None."""
    with _lock:
        if _running is None:
            return None
        bound = _running.server.server_address
        return str(bound[0]), int(bound[1])
