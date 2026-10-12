// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The web config subset: every way it fails closed, relative paths,
//! certificate reload, and bcrypt basic auth.

use super::*;

use base64::engine::general_purpose::STANDARD;

use crate::test_certs::TestCerts;

#[mutants::skip] // test helper
fn write(certs: &TestCerts, name: &str, text: &str) -> String {
    let path = certs.dir.join(name);
    std::fs::write(&path, text).expect("write web config");
    path.display().to_string()
}

#[mutants::skip] // test helper
fn tls_yaml(extra: &str) -> String {
    format!("tls_server_config:\n  cert_file: server.crt\n  key_file: server.key\n{extra}")
}

#[mutants::skip] // test helper
fn load_err(certs: &TestCerts, text: &str) -> String {
    load_web_config(&write(certs, "web.yml", text)).expect_err("must fail closed")
}

#[mutants::skip] // test helper
fn basic(credentials: &str) -> String {
    format!("Basic {}", STANDARD.encode(credentials))
}

#[test]
fn an_empty_document_means_plain_http_without_auth() {
    let certs = TestCerts::generate();
    let security = load_web_config(&write(&certs, "web.yml", "")).unwrap();
    assert!(!security.has_users());
    assert!(security.tls.is_none());
    assert!(security.authorized(None));
    let security = load_web_config(&write(&certs, "web.yml", "basic_auth_users:\n")).unwrap();
    assert!(!security.has_users());
}

#[test]
fn malformed_files_and_unsupported_keys_fail_closed() {
    let certs = TestCerts::generate();
    let err = load_web_config("/nonexistent/web.yml").unwrap_err();
    assert!(
        err.starts_with("web config /nonexistent/web.yml: "),
        "{err}"
    );
    assert!(load_err(&certs, "a: [").contains("web.yml: "));
    let only = "only [\"basic_auth_users\", \"tls_server_config\"] are supported";
    for text in [
        "- a list\n",
        "http_server_config:\n  http2: false\n",
        "1: x\n",
        "plain scalar\n",
    ] {
        let err = load_err(&certs, text);
        assert!(err.ends_with(only), "{text:?}: {err}");
    }
    assert!(load_err(&certs, "basic_auth_users: [a]\n")
        .ends_with("basic_auth_users must map user names to bcrypt hashes"));
}

#[test]
fn basic_auth_users_need_well_formed_bcrypt_hashes() {
    let certs = TestCerts::generate();
    for hash in [
        "plain-text",
        "$2a$10$short",
        // cost outside 4..=31
        "$2a$03$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq",
        "$2a$32$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq",
    ] {
        let err = load_err(&certs, &format!("basic_auth_users:\n  scraper: '{hash}'\n"));
        assert!(
            err.ends_with("basic_auth_users[scraper] is not a bcrypt hash"),
            "{hash}: {err}"
        );
    }
    let err = load_err(&certs, "basic_auth_users:\n  scraper: 12\n");
    assert!(err.ends_with("basic_auth_users[scraper] is not a bcrypt hash"));
    let err = load_err(&certs, "basic_auth_users:\n  scraper: [a]\n");
    assert!(err.ends_with("basic_auth_users[scraper] is not a bcrypt hash"));

    for cost in ["04", "31"] {
        let hash = format!("$2b${cost}$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq");
        let ok = load_web_config(&write(
            &certs,
            "web.yml",
            &format!("basic_auth_users:\n  scraper: '{hash}'\n"),
        ));
        assert!(ok.unwrap().has_users(), "cost {cost}");
    }
}

#[test]
fn tls_server_config_is_validated() {
    let certs = TestCerts::generate();
    let only = "tls_server_config: only [\"cert_file\", \"client_auth_type\", \"client_ca_file\", \"key_file\", \"min_version\"] are supported";
    assert_eq!(load_err(&certs, "tls_server_config:\n"), only);
    assert_eq!(load_err(&certs, "tls_server_config: [a]\n"), only);
    assert_eq!(load_err(&certs, &tls_yaml("  cipher_suites: []\n")), only);
    let needs = "tls_server_config needs cert_file and key_file";
    assert_eq!(
        load_err(&certs, "tls_server_config:\n  cert_file: server.crt\n"),
        needs
    );
    assert_eq!(
        load_err(&certs, "tls_server_config:\n  key_file: server.key\n"),
        needs
    );
    assert_eq!(
        load_err(
            &certs,
            "tls_server_config:\n  cert_file: ''\n  key_file: server.key\n"
        ),
        needs
    );
    assert_eq!(
        load_err(&certs, &tls_yaml("  min_version: SSL3\n")),
        "tls_server_config.min_version \"SSL3\": want TLS12 or TLS13"
    );
    assert_eq!(
        load_err(&certs, &tls_yaml("  client_auth_type: RequestClientCert\n")),
        "tls_server_config.client_auth_type \"RequestClientCert\" is not supported"
    );
    for auth in ["RequireAndVerifyClientCert", "VerifyClientCertIfGiven"] {
        assert_eq!(
            load_err(&certs, &tls_yaml(&format!("  client_auth_type: {auth}\n"))),
            format!("tls_server_config.client_auth_type {auth} needs client_ca_file")
        );
    }
}

#[test]
fn unloadable_certificates_and_keys_fail_closed() {
    let certs = TestCerts::generate();
    let err = load_err(
        &certs,
        "tls_server_config:\n  cert_file: server.crt\n  key_file: missing.key\n",
    );
    assert!(err.starts_with("tls_server_config: "), "{err}");
    assert!(err.contains("missing.key"), "{err}");
    let err = load_err(
        &certs,
        "tls_server_config:\n  cert_file: missing.crt\n  key_file: server.key\n",
    );
    assert!(err.contains("missing.crt"), "{err}");

    write(&certs, "empty.crt", "no pem here\n");
    let err = load_err(
        &certs,
        "tls_server_config:\n  cert_file: empty.crt\n  key_file: server.key\n",
    );
    assert!(err.ends_with("empty.crt: no certificate found"), "{err}");
    let err = load_err(
        &certs,
        "tls_server_config:\n  cert_file: server.crt\n  key_file: empty.crt\n",
    );
    assert!(err.contains("empty.crt"), "{err}");
    // A key that does not match the certificate.
    let err = load_err(
        &certs,
        "tls_server_config:\n  cert_file: server.crt\n  key_file: client.key\n",
    );
    assert!(err.starts_with("tls_server_config: "), "{err}");
    let err = load_err(&certs, &tls_yaml("  client_ca_file: empty.crt\n"));
    assert!(err.ends_with("empty.crt: no certificate found"), "{err}");
    write(
        &certs,
        "broken.crt",
        "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n",
    );
    let err = load_err(&certs, &tls_yaml("  client_ca_file: broken.crt\n"));
    assert!(err.contains("broken.crt"), "{err}");
    // Not even base64 between the markers.
    write(
        &certs,
        "garbled.crt",
        "-----BEGIN CERTIFICATE-----\n!!!!\n-----END CERTIFICATE-----\n",
    );
    let err = load_err(
        &certs,
        "tls_server_config:\n  cert_file: garbled.crt\n  key_file: server.key\n",
    );
    assert!(err.starts_with("tls_server_config: "), "{err}");
    assert!(err.contains("garbled.crt: "), "{err}");
}

#[test]
fn relative_paths_resolve_against_the_config_file() {
    let certs = TestCerts::generate();
    let nested = certs.dir.join("conf");
    std::fs::create_dir_all(&nested).unwrap();
    let path = nested.join("web.yml");
    std::fs::write(
        &path,
        "tls_server_config:\n  cert_file: ../server.crt\n  key_file: ../server.key\n  client_ca_file: ../ca.crt\n  min_version: TLS13\n",
    )
    .unwrap();
    let security = load_web_config(&path.display().to_string()).unwrap();
    let tls = security.tls.as_ref().expect("tls configured");
    assert_eq!(tls.settings.cert, nested.join("../server.crt"));
    assert_eq!(tls.settings.ca, Some(nested.join("../ca.crt")));
    assert_eq!(tls.settings.client_auth, ClientAuth::Require);
    assert!(tls.settings.tls13_only);

    // A bare file name has an empty parent; paths stay relative to the cwd.
    let err = load_web_config("no-such-relative-web.yml").unwrap_err();
    assert!(
        err.starts_with("web config no-such-relative-web.yml: "),
        "{err}"
    );
}

#[test]
fn defaults_and_explicit_client_auth() {
    let certs = TestCerts::generate();
    let load = |text: &str| load_web_config(&write(&certs, "web.yml", text)).unwrap();
    let plain = load(&tls_yaml(""));
    let settings = &plain.tls.as_ref().unwrap().settings;
    assert_eq!(settings.client_auth, ClientAuth::None);
    assert!(!settings.tls13_only);
    assert_eq!(settings.ca, None);

    let explicit = load(&tls_yaml(
        "  min_version: TLS12\n  client_ca_file: ca.crt\n  client_auth_type: NoClientCert\n",
    ));
    assert_eq!(
        explicit.tls.as_ref().unwrap().settings.client_auth,
        ClientAuth::None
    );
    let optional = load(&tls_yaml(
        "  client_ca_file: ca.crt\n  client_auth_type: VerifyClientCertIfGiven\n",
    ));
    assert_eq!(
        optional.tls.as_ref().unwrap().settings.client_auth,
        ClientAuth::IfGiven
    );
}

#[test]
fn certificates_are_reread_when_they_change() {
    let certs = TestCerts::generate();
    let security = load_web_config(&write(&certs, "web.yml", &tls_yaml(""))).unwrap();
    let tls = security.tls.as_ref().unwrap();
    let first = tls.config().unwrap();
    assert!(Arc::ptr_eq(&first, &tls.config().unwrap()));

    let rotated = TestCerts::generate();
    for (from, to) in [(&rotated.cert, &certs.cert), (&rotated.key, &certs.key)] {
        std::fs::copy(from, to).unwrap();
        let file = std::fs::File::options().write(true).open(to).unwrap();
        file.set_modified(SystemTime::now() + std::time::Duration::from_secs(60))
            .unwrap();
    }
    let second = tls.config().unwrap();
    assert!(!Arc::ptr_eq(&first, &second));
    assert!(Arc::ptr_eq(&second, &tls.config().unwrap()));

    std::fs::write(&certs.key, "broken").unwrap();
    let file = std::fs::File::options()
        .write(true)
        .open(&certs.key)
        .unwrap();
    file.set_modified(SystemTime::now() + std::time::Duration::from_secs(120))
        .unwrap();
    assert!(tls.config().is_err());
    std::fs::remove_file(&certs.cert).unwrap();
    let err = tls.config().unwrap_err();
    assert!(err.contains("server.crt"), "{err}");
}

#[test]
fn basic_auth_checks_bcrypt_and_caches_successes() {
    let hash = bcrypt::hash("s3cret", 4).unwrap();
    let security = WebSecurity {
        users: HashMap::from([("scraper".to_string(), hash)]),
        tls: None,
        verified: Mutex::default(),
    };
    assert!(security.has_users());
    assert!(!security.authorized(None));
    assert!(!security.authorized(Some("")));
    assert!(!security.authorized(Some(&format!(
        "Bearer {}",
        STANDARD.encode("scraper:s3cret")
    ))));
    assert!(!security.authorized(Some("Basic !!!")));
    assert!(!security.authorized(Some(&format!("Basic {}", STANDARD.encode([0xff, 0xfe])))));
    assert!(!security.authorized(Some(&basic("scraper"))));
    assert!(!security.authorized(Some(&basic("scraper:wrong"))));
    assert!(!security.authorized(Some(&basic("nobody:s3cret"))));
    assert!(crate::_lock::lock(&security.verified).is_empty());

    assert!(security.authorized(Some(&basic("scraper:s3cret"))));
    assert!(security.authorized(Some(&format!(
        "basic {}",
        STANDARD.encode("scraper:s3cret")
    ))));
    assert_eq!(crate::_lock::lock(&security.verified).len(), 1);
    // A password containing ':' keeps everything after the first one.
    let colon = WebSecurity {
        users: HashMap::from([("u".to_string(), bcrypt::hash("a:b", 4).unwrap())]),
        tls: None,
        verified: Mutex::default(),
    };
    assert!(colon.authorized(Some(&basic("u:a:b"))));
}

#[test]
fn yaml_scalars_become_text() {
    assert_eq!(scalar(&Value::String("x".into())), Some("x".to_string()));
    assert_eq!(scalar(&Value::Number(5.into())), Some("5".to_string()));
    assert_eq!(scalar(&Value::Bool(true)), Some("true".to_string()));
    assert_eq!(scalar(&Value::Null), None);
    assert_eq!(scalar(&Value::Sequence(Vec::new())), None);
}

#[test]
fn the_credential_cache_is_keyed_and_tells_credentials_apart() {
    use sha2::Digest as _;
    assert_ne!(cache_key(), &[0u8; 32]);
    assert_eq!(cache_key(), cache_key());
    let digest = cache_digest("scraper", "s3cret");
    assert_eq!(digest, cache_digest("scraper", "s3cret"));
    assert_ne!(digest, cache_digest("scraper", "wrong"));
    let plain: [u8; 32] = Sha256::digest("scraper\0s3cret").into();
    assert_ne!(digest, plain);

    // A cached success admits that credential only.
    let security = WebSecurity {
        users: HashMap::from([("scraper".to_string(), bcrypt::hash("s3cret", 4).unwrap())]),
        tls: None,
        verified: Mutex::default(),
    };
    assert!(security.authorized(Some(&basic("scraper:s3cret"))));
    assert!(!security.authorized(Some(&basic("scraper:wrong"))));
}
