// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The Tier 3 standalone Prometheus listener.
//!
//! Serves [`super::metrics_handler`] at `PROVIDE_METRICS_PROMETHEUS_PATH` on
//! `OTEL_EXPORTER_PROMETHEUS_HOST:PORT`, optionally secured by a Prometheus web
//! config (TLS, client certificates, bcrypt basic auth; see
//! [`super::web_config`]). It runs on its own threads, one accepting and one per
//! connection, so it needs no async runtime from the host. It fails closed: any
//! problem with the web config keeps it from starting. Failures are logged and
//! recorded as the health snapshot's `setup_error`; they never fail setup.

use std::io::{Read, Write};
use std::net::{IpAddr, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread::JoinHandle;
use std::time::Duration;

use super::web_config::{load_web_config, WebSecurity};
use crate::config::TelemetryConfig;

const READ_TIMEOUT: Duration = Duration::from_secs(10);
const ACCEPT_POLL: Duration = Duration::from_millis(20);
const MAX_HEAD_BYTES: usize = 64 * 1024;
const PLAIN_TEXT: &str = "text/plain; charset=utf-8";
pub(crate) const WARN_EXPOSED: &str = "metrics.prometheus_listener.exposed";
pub(crate) const WARN_CLEARTEXT_AUTH: &str = "metrics.prometheus_listener.cleartext_auth";

/// What decides whether a running listener can be kept: host, port, path, web config.
type Key = (String, u16, String, String);

struct Running {
    key: Key,
    #[cfg_attr(not(test), allow(dead_code))] // read by address()
    address: SocketAddr,
    stop: Arc<AtomicBool>,
    thread: JoinHandle<()>,
}

static RUNNING: OnceLock<Mutex<Option<Running>>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only swap in Mutex::default().
fn empty_running() -> Mutex<Option<Running>> {
    Mutex::new(None)
}

fn running() -> &'static Mutex<Option<Running>> {
    RUNNING.get_or_init(empty_running)
}

/// Make the listener match `config`: start, stop, restart on a changed key, or leave it.
pub(crate) fn sync(config: &TelemetryConfig) {
    let mut slot = crate::_lock::lock(running());
    if !config.metrics.prometheus_listener_enabled() {
        stop_locked(&mut slot);
        return;
    }
    let p = &config.metrics.prometheus;
    let key: Key = (
        p.host.clone(),
        p.port,
        p.path.clone(),
        p.web_config.clone(),
    );
    if slot.as_ref().is_some_and(|r| r.key == key) {
        return;
    }
    stop_locked(&mut slot);
    match start(key) {
        Ok(started) => *slot = Some(started),
        Err(err) => {
            let message = format!("prometheus listener: {err}");
            eprintln!("provide_telemetry: metrics.prometheus_listener.failed error={err}");
            crate::health::set_setup_error(Some(message));
        }
    }
}

/// Stop the listener, if one runs.
pub(crate) fn stop() {
    stop_locked(&mut crate::_lock::lock(running()));
}

fn stop_locked(slot: &mut Option<Running>) {
    if let Some(running) = slot.take() {
        running.stop.store(true, Ordering::Release);
        let _ = running.thread.join();
    }
}

/// The bound address of the running listener, if any; how tests find a port-0 listener.
#[cfg_attr(not(test), allow(dead_code))]
pub(crate) fn address() -> Option<SocketAddr> {
    crate::_lock::lock(running()).as_ref().map(|r| r.address)
}

/// The warnings a listener on `host` secured by `security` logs at start.
pub(crate) fn exposure_warnings(host: &str, security: &WebSecurity) -> Vec<&'static str> {
    let mut warnings = Vec::new();
    if !is_loopback(host) {
        warnings.push(WARN_EXPOSED);
    }
    if security.has_users() && security.tls.is_none() {
        warnings.push(WARN_CLEARTEXT_AUTH);
    }
    warnings
}

fn is_loopback(host: &str) -> bool {
    host == "localhost" || host.parse::<IpAddr>().is_ok_and(|ip| ip.is_loopback())
}

struct Context {
    path: String,
    security: WebSecurity,
}

fn start(key: Key) -> Result<Running, String> {
    let (host, port, path, web_config) = key.clone();
    let security = if web_config.is_empty() {
        WebSecurity::default()
    } else {
        load_web_config(&web_config)?
    };
    let listener = TcpListener::bind((host.as_str(), port))
        .map_err(|err| format!("bind {host}:{port}: {err}"))?;
    let address = listener
        .local_addr()
        .and_then(|address| listener.set_nonblocking(true).map(|()| address))
        .map_err(|err| format!("bind {host}:{port}: {err}"))?;
    for warning in exposure_warnings(&host, &security) {
        eprintln!("provide_telemetry: {warning} host={host}");
    }
    let stop = Arc::new(AtomicBool::new(false));
    let context = Arc::new(Context { path, security });
    let flag = Arc::clone(&stop);
    let thread = std::thread::Builder::new()
        .name("provide-prometheus-listener".to_string())
        .spawn(move || accept_loop(&listener, &flag, &context))
        .map_err(|err| format!("spawn: {err}"))?;
    Ok(Running {
        key,
        address,
        stop,
        thread,
    })
}

fn accept_loop(listener: &TcpListener, stop: &AtomicBool, context: &Arc<Context>) {
    while !stop.load(Ordering::Acquire) {
        match listener.accept() {
            Ok((stream, _)) => {
                let context = Arc::clone(context);
                // A refused spawn drops the connection; the scraper retries.
                let _ = std::thread::Builder::new()
                    .name("provide-prometheus-conn".to_string())
                    .spawn(move || serve_connection(stream, &context));
            }
            Err(_) => std::thread::sleep(ACCEPT_POLL),
        }
    }
}

/// Serve one request on `stream`, over TLS when the web config asks for it.
/// Errors (a failed handshake, a slow or vanished client) just drop the connection.
fn serve_connection(stream: TcpStream, context: &Context) {
    // Accepted sockets inherit non-blocking mode on some platforms.
    let configured = stream
        .set_nonblocking(false)
        .and_then(|()| stream.set_read_timeout(Some(READ_TIMEOUT)))
        .and_then(|()| stream.set_write_timeout(Some(READ_TIMEOUT)));
    if configured.is_err() {
        return;
    }
    match &context.security.tls {
        None => {
            let mut stream = stream;
            serve(&mut stream, context);
        }
        Some(tls) => {
            let Ok(config) = tls.config() else {
                return;
            };
            let Ok(connection) = rustls::ServerConnection::new(config) else {
                return;
            };
            let mut tls_stream = rustls::StreamOwned::new(connection, stream);
            serve(&mut tls_stream, context);
            tls_stream.conn.send_close_notify();
            let _ = tls_stream.flush();
        }
    }
}

/// The parts of a request the listener looks at.
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Request {
    pub(crate) method: String,
    pub(crate) path: String,
    pub(crate) authorization: Option<String>,
    pub(crate) accept: Option<String>,
}

/// Read a request head; `None` when the client sent nothing usable in time.
fn read_head(io: &mut impl Read) -> Option<Vec<u8>> {
    let mut head = Vec::new();
    let mut buf = [0u8; 4096];
    while !head.windows(4).any(|w| w == b"\r\n\r\n") {
        if head.len() > MAX_HEAD_BYTES {
            return None;
        }
        match io.read(&mut buf) {
            Ok(0) | Err(_) => return None,
            Ok(n) => head.extend_from_slice(&buf[..n]),
        }
    }
    Some(head)
}

/// Parse a request head; `None` when it is not HTTP.
pub(crate) fn parse_request(head: &[u8]) -> Option<Request> {
    let text = String::from_utf8_lossy(head);
    let mut lines = text.split("\r\n");
    let mut parts = lines.next()?.split(' ');
    let (method, target, version) = (parts.next()?, parts.next()?, parts.next()?);
    if method.is_empty() || !version.starts_with("HTTP/") || parts.next().is_some() {
        return None;
    }
    let mut request = Request {
        method: method.to_string(),
        path: request_path(target),
        authorization: None,
        accept: None,
    };
    for line in lines {
        let Some((name, value)) = line.split_once(':') else {
            continue;
        };
        let slot = if name.eq_ignore_ascii_case("authorization") {
            &mut request.authorization
        } else if name.eq_ignore_ascii_case("accept") {
            &mut request.accept
        } else {
            continue;
        };
        slot.get_or_insert_with(|| value.trim().to_string());
    }
    Some(request)
}

/// The path of a request target, without query or fragment; an absolute-form
/// target (`http://host/metrics`) contributes its path.
fn request_path(target: &str) -> String {
    let without_scheme = target
        .split_once("://")
        .map_or(target, |(_, rest)| rest.find('/').map_or("", |i| &rest[i..]));
    let end = without_scheme
        .find(['?', '#'])
        .unwrap_or(without_scheme.len());
    without_scheme[..end].to_string()
}

/// `(status, headers, body)` for one request.
pub(crate) fn respond(
    request: &Request,
    path: &str,
    security: &WebSecurity,
) -> (u16, Vec<(&'static str, String)>, Vec<u8>) {
    if request.path != path {
        return (
            404,
            vec![("content-type", PLAIN_TEXT.to_string())],
            b"not found\n".to_vec(),
        );
    }
    if !security.authorized(request.authorization.as_deref()) {
        return (
            401,
            vec![
                ("www-authenticate", "Basic".to_string()),
                ("content-type", PLAIN_TEXT.to_string()),
            ],
            b"unauthorized\n".to_vec(),
        );
    }
    let response = super::metrics_handler(&request.method, request.accept.as_deref());
    (response.status, response.headers, response.body)
}

fn reason(status: u16) -> &'static str {
    match status {
        200 => "OK",
        401 => "Unauthorized",
        404 => "Not Found",
        405 => "Method Not Allowed",
        503 => "Service Unavailable",
        _ => "Bad Request",
    }
}

/// The bytes of one HTTP/1.1 response that closes the connection.
pub(crate) fn encode(status: u16, headers: &[(&'static str, String)], body: &[u8]) -> Vec<u8> {
    let mut out = format!("HTTP/1.1 {status} {}\r\n", reason(status));
    for (name, value) in headers {
        out.push_str(&format!("{name}: {value}\r\n"));
    }
    out.push_str(&format!(
        "content-length: {}\r\nconnection: close\r\n\r\n",
        body.len()
    ));
    [out.into_bytes(), body.to_vec()].concat()
}

fn serve(io: &mut (impl Read + Write), context: &Context) {
    let Some(head) = read_head(io) else {
        return;
    };
    let (status, headers, body) = match parse_request(&head) {
        Some(request) => respond(&request, &context.path, &context.security),
        None => (
            400,
            vec![("content-type", PLAIN_TEXT.to_string())],
            b"bad request\n".to_vec(),
        ),
    };
    let _ = io.write_all(&encode(status, &headers, &body));
    let _ = io.flush();
}

#[cfg(test)]
#[path = "listener_tests.rs"]
mod tests;
