// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Throwaway PEM files for the TLS tests: a CA, a server certificate for
//! localhost and 127.0.0.1, and a client certificate, all signed by the CA.

use std::path::PathBuf;

use rcgen::{
    BasicConstraints, CertificateParams, DnType, ExtendedKeyUsagePurpose, IsCa, KeyPair,
    KeyUsagePurpose,
};

/// Paths to freshly generated PEM files in a private temp directory.
// The server pair is only read by the listener tests.
#[cfg_attr(not(feature = "prometheus-listener"), allow(dead_code))]
pub(crate) struct TestCerts {
    pub(crate) dir: PathBuf,
    pub(crate) ca: PathBuf,
    pub(crate) cert: PathBuf,
    pub(crate) key: PathBuf,
    pub(crate) client_cert: PathBuf,
    pub(crate) client_key: PathBuf,
}

#[mutants::skip] // test helper
fn leaf(
    names: &[&str],
    usage: ExtendedKeyUsagePurpose,
    ca: &rcgen::Certificate,
    ca_key: &KeyPair,
) -> (String, String) {
    let key = KeyPair::generate().expect("key");
    let names: Vec<String> = names.iter().map(|n| (*n).to_string()).collect();
    let mut params = CertificateParams::new(names).expect("params");
    params.extended_key_usages = vec![usage];
    params.distinguished_name.push(DnType::CommonName, "leaf");
    let cert = params.signed_by(&key, ca, ca_key).expect("sign");
    (cert.pem(), key.serialize_pem())
}

impl TestCerts {
    #[mutants::skip] // test helper
    pub(crate) fn generate() -> Self {
        let dir = std::env::temp_dir().join(format!("provide-certs-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).expect("temp dir");
        let ca_key = KeyPair::generate().expect("ca key");
        let mut params = CertificateParams::new(Vec::<String>::new()).expect("ca params");
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        params
            .distinguished_name
            .push(DnType::CommonName, "provide test CA");
        params.key_usages = vec![KeyUsagePurpose::KeyCertSign, KeyUsagePurpose::CrlSign];
        let ca = params.self_signed(&ca_key).expect("ca");
        let (cert, key) = leaf(
            &["localhost", "127.0.0.1"],
            ExtendedKeyUsagePurpose::ServerAuth,
            &ca,
            &ca_key,
        );
        let (client_cert, client_key) = leaf(
            &["client"],
            ExtendedKeyUsagePurpose::ClientAuth,
            &ca,
            &ca_key,
        );
        let write = |name: &str, text: &str| {
            let path = dir.join(name);
            std::fs::write(&path, text).expect("write pem");
            path
        };
        Self {
            ca: write("ca.crt", &ca.pem()),
            cert: write("server.crt", &cert),
            key: write("server.key", &key),
            client_cert: write("client.crt", &client_cert),
            client_key: write("client.key", &client_key),
            dir,
        }
    }
}

impl Drop for TestCerts {
    #[mutants::skip] // test helper
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// Sets environment variables for one test and removes them when dropped.
/// Hold the test state lock while it lives: the environment is process-wide.
#[derive(Default)]
pub(crate) struct EnvGuard(Vec<String>);

impl EnvGuard {
    #[mutants::skip] // test helper
    pub(crate) fn set(&mut self, name: &str, value: impl AsRef<std::ffi::OsStr>) {
        std::env::set_var(name, value);
        self.0.push(name.to_string());
    }
}

impl Drop for EnvGuard {
    #[mutants::skip] // test helper
    fn drop(&mut self) {
        for name in &self.0 {
            std::env::remove_var(name);
        }
    }
}
