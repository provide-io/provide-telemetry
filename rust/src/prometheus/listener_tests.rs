// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The listener over real sockets: every listener_web_config case in
//! spec/prometheus_fixtures.yaml, paths, methods, restarts, bind failures and
//! certificate rotation.

use super::*;

use std::path::Path;

use crate::test_certs::TestCerts;
use crate::testing::{acquire_test_state_lock, reset_telemetry_state};

const PASSWORD: &str = "e2e-test-only-password";
// bcrypt of PASSWORD, as ci/prometheus-tls-setup.sh writes it.
const PASSWORD_HASH: &str = "$2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq";

#[mutants::skip] // test helper
fn config(path: &str, web_config: &str) -> TelemetryConfig {
    let mut config = TelemetryConfig::default();
    config.tracing.enabled = false;
    config.metrics.exporters = vec!["prometheus".to_string()];
    config.metrics.prometheus.listen = "true".to_string();
    config.metrics.prometheus.port = 0;
    config.metrics.prometheus.path = path.to_string();
    config.metrics.prometheus.web_config = web_config.to_string();
    config
}

#[mutants::skip] // test helper
fn start(config: TelemetryConfig) -> Option<SocketAddr> {
    reset_telemetry_state();
    crate::setup_telemetry(Some(config)).expect("listener problems never fail setup");
    address()
}

#[mutants::skip] // test helper
fn client(certs: Option<&TestCerts>, client_cert: bool) -> reqwest::blocking::Client {
    let mut builder = reqwest::blocking::Client::builder().timeout(Duration::from_secs(5));
    if let Some(certs) = certs {
        let ca = std::fs::read(&certs.ca).unwrap();
        builder = builder
            .tls_built_in_root_certs(false)
            .add_root_certificate(reqwest::Certificate::from_pem(&ca).unwrap());
        if client_cert {
            let pem = [
                std::fs::read(&certs.client_key).unwrap(),
                std::fs::read(&certs.client_cert).unwrap(),
            ]
            .concat();
            builder = builder.identity(reqwest::Identity::from_pem(&pem).unwrap());
        }
    }
    builder.build().unwrap()
}

#[mutants::skip] // test helper
fn raw(address: SocketAddr, request: &[u8]) -> String {
    let mut stream = TcpStream::connect(address).unwrap();
    stream.write_all(request).unwrap();
    let mut out = String::new();
    let _ = stream.read_to_string(&mut out);
    out
}

/// Substitute the fixture placeholders and write the web config, if any.
#[mutants::skip] // test helper
fn web_config_for(case: &serde_yaml::Value, certs: &TestCerts) -> String {
    let missing = certs.dir.join("missing.pem").display().to_string();
    if let Some(path) = case["web_config_path"].as_str() {
        return path.replace("{missing}", &missing);
    }
    if case["web_config"].is_null() {
        return String::new();
    }
    let text = serde_yaml::to_string(&case["web_config"])
        .unwrap()
        .replace("{cert}", &certs.cert.display().to_string())
        .replace("{key}", &certs.key.display().to_string())
        .replace("{ca}", &certs.ca.display().to_string())
        .replace("{missing}", &missing)
        .replace("bcrypt_of_e2e_test_only_password", PASSWORD_HASH);
    let path = certs.dir.join("web-config.yml");
    std::fs::write(&path, text).unwrap();
    path.display().to_string()
}

#[mutants::skip] // test helper
fn fixture_cases() -> Vec<serde_yaml::Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../spec/prometheus_fixtures.yaml"
    );
    let doc: serde_yaml::Value =
        serde_yaml::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    doc["listener_web_config"].as_sequence().unwrap().clone()
}

#[test]
fn listener_web_config_fixture_cases() {
    let _guard = acquire_test_state_lock();
    let cases = fixture_cases();
    assert_eq!(cases.len(), 9);
    for case in cases {
        let id = case["id"].as_str().unwrap();
        let certs = TestCerts::generate();
        let web_config = web_config_for(&case, &certs);
        let address = start(config("/metrics", &web_config));
        if !case["listener"].as_bool().unwrap() {
            assert_eq!(address, None, "{id}");
            let error = crate::health::get_health_snapshot().setup_error.unwrap();
            assert!(error.starts_with("prometheus listener: "), "{id}: {error}");
            continue;
        }
        let address = address.unwrap_or_else(|| panic!("{id}: listener should run"));
        assert_eq!(
            crate::health::get_health_snapshot().setup_error,
            None,
            "{id}"
        );
        let https = case["scheme"].as_str() == Some("https");
        let url = if https {
            format!("https://localhost:{}/metrics", address.port())
        } else {
            format!("http://{address}/metrics")
        };
        let trust = https.then_some(&certs);
        if case["client_cert_required"].as_bool() == Some(true) {
            assert!(client(trust, false).get(&url).send().is_err(), "{id}");
            let ok = client(trust, true).get(&url).send().unwrap();
            assert_eq!(ok.status(), 200, "{id}");
            continue;
        }
        let anonymous = client(trust, false).get(&url).send().unwrap();
        if case["auth"].as_bool().unwrap() {
            assert_eq!(anonymous.status(), 401, "{id}");
            assert_eq!(anonymous.headers()["www-authenticate"], "Basic", "{id}");
            assert_eq!(anonymous.text().unwrap(), "unauthorized\n");
            let wrong = client(trust, false)
                .get(&url)
                .basic_auth("e2e", Some("wrong"))
                .send()
                .unwrap();
            assert_eq!(wrong.status(), 401, "{id}");
            let ok = client(trust, false)
                .get(&url)
                .basic_auth("e2e", Some(PASSWORD))
                .send()
                .unwrap();
            assert_eq!(ok.status(), 200, "{id}");
        } else {
            assert_eq!(anonymous.status(), 200, "{id}");
            assert!(anonymous
                .text()
                .unwrap()
                .contains("provide_telemetry_setup_error 0\n"));
        }
        let warns = case["warning"].as_bool() == Some(true);
        let security = if web_config.is_empty() {
            WebSecurity::default()
        } else {
            load_web_config(&web_config).unwrap()
        };
        assert_eq!(
            exposure_warnings("127.0.0.1", &security).contains(&WARN_CLEARTEXT_AUTH),
            warns,
            "{id}"
        );
    }
    reset_telemetry_state();
}

#[test]
fn paths_methods_and_malformed_requests() {
    let _guard = acquire_test_state_lock();
    let address = start(config("/internal/metrics", "")).unwrap();
    let http = client(None, false);
    let url = format!("http://{address}/internal/metrics");
    let ok = http.get(format!("{url}?x=1")).send().unwrap();
    assert_eq!(ok.status(), 200);
    assert_eq!(
        ok.headers()["content-type"],
        "text/plain; version=0.0.4; charset=utf-8; escaping=underscores"
    );
    let head = http.head(&url).send().unwrap();
    assert_eq!(head.status(), 200);
    let post = http.post(&url).body("x").send().unwrap();
    assert_eq!(post.status(), 405);
    assert_eq!(post.headers()["allow"], "GET, HEAD");
    assert_eq!(post.text().unwrap(), "method not allowed\n");
    let other = http
        .get(format!("http://{address}/metrics"))
        .send()
        .unwrap();
    assert_eq!(other.status(), 404);
    assert_eq!(other.headers()["content-type"], "text/plain; charset=utf-8");
    assert_eq!(other.text().unwrap(), "not found\n");

    let bad = raw(address, b"garbage\r\n\r\n");
    assert!(bad.starts_with("HTTP/1.1 400 Bad Request\r\n"), "{bad}");
    assert!(bad.ends_with("\r\n\r\nbad request\n"), "{bad}");
    // A client that closes without a complete head gets nothing.
    assert_eq!(raw(address, b"GET /internal/metrics HTTP/1.1\r\n"), "");
    let utf8 = raw(
        address,
        b"GET /internal/metrics HTTP/1.1\r\nAccept: text/plain;escaping=allow-utf-8\r\n\r\n",
    );
    assert!(
        utf8.contains(
            "content-type: text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8\r\n"
        ),
        "{utf8}"
    );
    reset_telemetry_state();
    assert_eq!(address_after_shutdown(), None);
}

#[mutants::skip] // test helper
fn address_after_shutdown() -> Option<SocketAddr> {
    address()
}

#[test]
fn sync_keeps_restarts_and_stops_the_listener() {
    let _guard = acquire_test_state_lock();
    let first = start(config("/metrics", "")).unwrap();
    let mut same = config("/metrics", "");
    same.metrics.prometheus.port = first.port();
    sync(&same);
    sync(&same);
    assert_eq!(address(), Some(first));
    let mut moved = same.clone();
    moved.metrics.prometheus.path = "/other".to_string();
    sync(&moved);
    assert_eq!(address(), Some(first), "the freed port is bound again");
    let response = client(None, false)
        .get(format!("http://{first}/other"))
        .send()
        .unwrap();
    assert_eq!(response.status(), 200);

    let mut off = moved.clone();
    off.metrics.prometheus.listen = "false".to_string();
    sync(&off);
    assert_eq!(address(), None);
    assert!(TcpStream::connect(first).is_err());

    // Metrics disabled stops it too.
    sync(&moved);
    assert!(address().is_some());
    let mut disabled = moved;
    disabled.metrics.enabled = false;
    sync(&disabled);
    assert_eq!(address(), None);
    reset_telemetry_state();
}

#[test]
fn a_bind_failure_is_recorded_and_never_fails_setup() {
    let _guard = acquire_test_state_lock();
    let taken = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = taken.local_addr().unwrap().port();
    let mut busy = config("/metrics", "");
    busy.metrics.prometheus.port = port;
    assert_eq!(start(busy), None);
    let error = crate::health::get_health_snapshot().setup_error.unwrap();
    assert!(
        error.starts_with(&format!("prometheus listener: bind 127.0.0.1:{port}: ")),
        "{error}"
    );
    let mut unresolvable = config("/metrics", "");
    unresolvable.metrics.prometheus.host = "no-such-host.invalid".to_string();
    assert_eq!(start(unresolvable), None);
    // A successful setup clears the stale error.
    assert!(start(config("/metrics", "")).is_some());
    assert_eq!(crate::health::get_health_snapshot().setup_error, None);
    reset_telemetry_state();
}

#[test]
fn exposure_warnings_follow_host_and_security() {
    let plain = WebSecurity::default();
    for host in ["127.0.0.1", "::1", "localhost", "127.1.2.3"] {
        assert!(exposure_warnings(host, &plain).is_empty(), "{host}");
    }
    for host in ["0.0.0.0", "::", "10.0.0.1", "example.com"] {
        assert_eq!(
            exposure_warnings(host, &plain),
            vec![WARN_EXPOSED],
            "{host}"
        );
    }
}

#[test]
fn a_non_loopback_listener_still_starts() {
    let _guard = acquire_test_state_lock();
    let mut open = config("/metrics", "");
    open.metrics.prometheus.host = "0.0.0.0".to_string();
    let address = start(open).unwrap();
    let local = SocketAddr::from(([127, 0, 0, 1], address.port()));
    let response = client(None, false)
        .get(format!("http://{local}/metrics"))
        .send()
        .unwrap();
    assert_eq!(response.status(), 200);
    reset_telemetry_state();
}

#[mutants::skip] // test helper
fn tls_web_config(certs: &TestCerts, extra: &str) -> String {
    let path = certs.dir.join("web.yml");
    std::fs::write(
        &path,
        format!(
            "tls_server_config:\n  cert_file: {}\n  key_file: {}\n{extra}",
            certs.cert.display(),
            certs.key.display()
        ),
    )
    .unwrap();
    path.display().to_string()
}

#[mutants::skip] // test helper
fn bump_mtime(path: &Path, seconds: u64) {
    let file = std::fs::File::options().write(true).open(path).unwrap();
    file.set_modified(std::time::SystemTime::now() + Duration::from_secs(seconds))
        .unwrap();
}

#[test]
fn tls13_only_refuses_a_tls12_client() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let address = start(config(
        "/metrics",
        &tls_web_config(&certs, "  min_version: TLS13\n"),
    ))
    .unwrap();
    let url = format!("https://localhost:{}/metrics", address.port());
    let ca = std::fs::read(&certs.ca).unwrap();
    let tls12 = reqwest::blocking::Client::builder()
        .tls_built_in_root_certs(false)
        .add_root_certificate(reqwest::Certificate::from_pem(&ca).unwrap())
        .max_tls_version(reqwest::tls::Version::TLS_1_2)
        .build()
        .unwrap();
    assert!(tls12.get(&url).send().is_err());
    assert_eq!(
        client(Some(&certs), false)
            .get(&url)
            .send()
            .unwrap()
            .status(),
        200
    );
    reset_telemetry_state();
}

#[test]
fn tls12_is_accepted_by_default() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let address = start(config("/metrics", &tls_web_config(&certs, ""))).unwrap();
    let ca = std::fs::read(&certs.ca).unwrap();
    let tls12 = reqwest::blocking::Client::builder()
        .tls_built_in_root_certs(false)
        .add_root_certificate(reqwest::Certificate::from_pem(&ca).unwrap())
        .max_tls_version(reqwest::tls::Version::TLS_1_2)
        .build()
        .unwrap();
    let url = format!("https://localhost:{}/metrics", address.port());
    assert_eq!(tls12.get(&url).send().unwrap().status(), 200);
    reset_telemetry_state();
}

#[test]
fn an_optional_client_certificate_is_verified_when_given() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let extra = format!(
        "  client_ca_file: {}\n  client_auth_type: VerifyClientCertIfGiven\n",
        certs.ca.display()
    );
    let address = start(config("/metrics", &tls_web_config(&certs, &extra))).unwrap();
    let url = format!("https://localhost:{}/metrics", address.port());
    assert_eq!(
        client(Some(&certs), false)
            .get(&url)
            .send()
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        client(Some(&certs), true)
            .get(&url)
            .send()
            .unwrap()
            .status(),
        200
    );
    reset_telemetry_state();
}

#[test]
fn rotated_certificates_are_served_without_a_restart() {
    let _guard = acquire_test_state_lock();
    let certs = TestCerts::generate();
    let address = start(config("/metrics", &tls_web_config(&certs, ""))).unwrap();
    let url = format!("https://localhost:{}/metrics", address.port());
    assert_eq!(
        client(Some(&certs), false)
            .get(&url)
            .send()
            .unwrap()
            .status(),
        200
    );

    let rotated = TestCerts::generate();
    std::fs::copy(&rotated.cert, &certs.cert).unwrap();
    std::fs::copy(&rotated.key, &certs.key).unwrap();
    bump_mtime(&certs.cert, 60);
    bump_mtime(&certs.key, 60);
    assert!(client(Some(&certs), false).get(&url).send().is_err());
    assert_eq!(
        client(Some(&rotated), false)
            .get(&url)
            .send()
            .unwrap()
            .status(),
        200
    );

    // Unusable files fail the connection rather than serving an old certificate.
    std::fs::remove_file(&certs.key).unwrap();
    assert!(client(Some(&rotated), false).get(&url).send().is_err());
    reset_telemetry_state();
}

#[test]
fn request_heads_are_parsed_leniently_but_must_be_http() {
    let request = parse_request(
        b"GET /metrics?x=1 HTTP/1.1\r\nACCEPT: text/plain\r\naccept: second\r\nno colon\r\nAuthorization:  Basic abc \r\n\r\n",
    )
    .unwrap();
    assert_eq!(
        request,
        Request {
            method: "GET".to_string(),
            path: "/metrics".to_string(),
            authorization: Some("Basic abc".to_string()),
            accept: Some("text/plain".to_string()),
        }
    );
    for bad in [
        &b"\r\n\r\n"[..],
        b"GET\r\n\r\n",
        b"GET /\r\n\r\n",
        b"GET / FTP/1.0\r\n\r\n",
        b"GET / HTTP/1.1 extra\r\n\r\n",
        b" / HTTP/1.1\r\n\r\n",
    ] {
        assert_eq!(
            parse_request(bad),
            None,
            "{:?}",
            String::from_utf8_lossy(bad)
        );
    }
    assert_eq!(request_path("/m#frag"), "/m");
    assert_eq!(request_path("http://host:9464/metrics?q"), "/metrics");
    assert_eq!(request_path("https://host"), "");
    assert_eq!(request_path("/"), "/");
}

#[test]
fn oversized_or_truncated_heads_are_dropped() {
    let mut huge = std::io::Cursor::new(vec![b'a'; MAX_HEAD_BYTES + 8192]);
    assert_eq!(read_head(&mut huge), None);
    let mut truncated = std::io::Cursor::new(b"GET / HTTP/1.1\r\n".to_vec());
    assert_eq!(read_head(&mut truncated), None);
    let mut complete = std::io::Cursor::new(b"GET / HTTP/1.1\r\n\r\n".to_vec());
    assert_eq!(
        read_head(&mut complete),
        Some(b"GET / HTTP/1.1\r\n\r\n".to_vec())
    );
}

#[test]
fn responses_are_encoded_with_length_and_close() {
    let bytes = encode(
        404,
        &[("content-type", "text/plain".to_string())],
        b"not found\n",
    );
    assert_eq!(
        String::from_utf8(bytes).unwrap(),
        "HTTP/1.1 404 Not Found\r\ncontent-type: text/plain\r\ncontent-length: 10\r\nconnection: close\r\n\r\nnot found\n"
    );
    for (status, phrase) in [
        (200, "OK"),
        (400, "Bad Request"),
        (401, "Unauthorized"),
        (405, "Method Not Allowed"),
        (503, "Service Unavailable"),
    ] {
        assert_eq!(reason(status), phrase);
    }
}

#[test]
fn the_listener_serves_503_until_the_reader_is_ready() {
    let _guard = acquire_test_state_lock();
    let address = start(config("/metrics", "")).unwrap();
    crate::prometheus::set_status(crate::prometheus::Status::SetupFailed);
    let response = client(None, false)
        .get(format!("http://{address}/metrics"))
        .send()
        .unwrap();
    assert_eq!(response.status(), 503);
    assert_eq!(
        response.text().unwrap(),
        "provide-telemetry: the metrics provider failed to start\n"
    );
    reset_telemetry_state();
}
