// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! The Prometheus web config subset the Tier 3 listener reads.
//!
//! Only the keys `prometheus_metrics.listener_security` lists are accepted:
//! `tls_server_config` (cert_file, key_file, client_ca_file, client_auth_type,
//! min_version) and `basic_auth_users` (bcrypt hashes). Anything else, or any
//! file that cannot be read, is an error and the listener does not start.
//! Relative paths resolve against the config file's directory, and the
//! certificate and key are re-read whenever their modification time changes.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::SystemTime;

use base64::Engine as _;
use hmac::{Hmac, Mac};
use rustls::pki_types::pem::PemObject;
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use rustls::server::WebPkiClientVerifier;
use rustls::{RootCertStore, ServerConfig, SupportedProtocolVersion};
use serde_yaml::Value;
use sha2::Sha256;

const TOP_KEYS: [&str; 2] = ["basic_auth_users", "tls_server_config"];
const TLS_KEYS: [&str; 5] = [
    "cert_file",
    "client_auth_type",
    "client_ca_file",
    "key_file",
    "min_version",
];
// Compared against when the user is unknown, so a wrong user name costs the
// same as a wrong password. Any well-formed cost-10 hash will do.
const DUMMY_HASH: &str = "$2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ClientAuth {
    None,
    Require,
    IfGiven,
}

/// Where the TLS material lives and how clients are checked.
#[derive(Debug)]
struct TlsSettings {
    cert: PathBuf,
    key: PathBuf,
    ca: Option<PathBuf>,
    client_auth: ClientAuth,
    tls13_only: bool,
}

/// TLS settings, rebuilt into a fresh `ServerConfig` when the files change.
#[derive(Debug)]
pub(crate) struct TlsReloader {
    settings: TlsSettings,
    current: Mutex<(Stamp, Arc<ServerConfig>)>,
}

type Stamp = (SystemTime, SystemTime);

fn modified(path: &Path) -> Result<SystemTime, String> {
    std::fs::metadata(path)
        .and_then(|meta| meta.modified())
        .map_err(|err| format!("{}: {err}", path.display()))
}

fn load_certs(path: &Path) -> Result<Vec<CertificateDer<'static>>, String> {
    let certs = CertificateDer::pem_file_iter(path)
        .and_then(Iterator::collect::<Result<Vec<_>, _>>)
        .map_err(|err| format!("{}: {err}", path.display()))?;
    if certs.is_empty() {
        return Err(format!("{}: no certificate found", path.display()));
    }
    Ok(certs)
}

impl TlsSettings {
    fn stamp(&self) -> Result<Stamp, String> {
        Ok((modified(&self.cert)?, modified(&self.key)?))
    }

    fn build(&self) -> Result<Arc<ServerConfig>, String> {
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let certs = load_certs(&self.cert)?;
        let key = PrivateKeyDer::from_pem_file(&self.key)
            .map_err(|err| format!("{}: {err}", self.key.display()))?;
        let versions: &[&SupportedProtocolVersion] = if self.tls13_only {
            &[&rustls::version::TLS13]
        } else {
            &[&rustls::version::TLS13, &rustls::version::TLS12]
        };
        // One closure for every rustls failure, so the one a test can reach (a
        // key that does not match the certificate) runs the same code as those
        // it cannot.
        let rustls_error = |err: rustls::Error| err.to_string();
        let builder = ServerConfig::builder_with_provider(Arc::clone(&provider))
            .with_protocol_versions(versions)
            .map_err(rustls_error)?;
        let builder = match (&self.ca, self.client_auth) {
            (Some(ca), ClientAuth::Require | ClientAuth::IfGiven) => {
                let mut roots = RootCertStore::empty();
                // Unusable certificates are skipped; with none left, building
                // the verifier below fails.
                roots.add_parsable_certificates(load_certs(ca)?);
                let verifier =
                    WebPkiClientVerifier::builder_with_provider(Arc::new(roots), provider);
                let verifier = if self.client_auth == ClientAuth::IfGiven {
                    verifier.allow_unauthenticated()
                } else {
                    verifier
                };
                builder.with_client_cert_verifier(
                    verifier
                        .build()
                        .map_err(|err| format!("{}: {err}", ca.display()))?,
                )
            }
            _ => builder.with_no_client_auth(),
        };
        let mut config = builder.with_single_cert(certs, key).map_err(rustls_error)?;
        config.alpn_protocols = vec![b"http/1.1".to_vec()];
        Ok(Arc::new(config))
    }
}

impl TlsReloader {
    fn new(settings: TlsSettings) -> Result<Self, String> {
        let stamp = settings.stamp()?;
        let config = settings.build()?;
        Ok(Self {
            settings,
            current: Mutex::new((stamp, config)),
        })
    }

    /// The current server config; checked on each new connection, so rotation
    /// needs no restart. Fails while the files are missing or unusable.
    pub(crate) fn config(&self) -> Result<Arc<ServerConfig>, String> {
        let mut current = crate::_lock::lock(&self.current);
        let stamp = self.settings.stamp()?;
        if stamp != current.0 {
            *current = (stamp, self.settings.build()?);
        }
        Ok(Arc::clone(&current.1))
    }
}

/// What a web config asks of the listener.
#[derive(Debug, Default)]
pub(crate) struct WebSecurity {
    users: HashMap<String, String>,
    pub(crate) tls: Option<TlsReloader>,
    /// `cache_digest(user, password)` of successful checks, so bcrypt runs once per credential.
    verified: Mutex<HashSet<[u8; 32]>>,
}

/// Keys the verified-credentials cache. A plain hash of user and password in
/// memory could be guessed at hash speed, far faster than bcrypt; a keyed one
/// cannot be without this key, which never leaves the process.
fn cache_key() -> &'static [u8; 32] {
    static KEY: std::sync::OnceLock<[u8; 32]> = std::sync::OnceLock::new();
    KEY.get_or_init(rand::random)
}

/// The verified-credentials cache's key for `user` and `password`.
fn cache_digest(user: &str, password: &str) -> [u8; 32] {
    let mut mac =
        <Hmac<Sha256> as Mac>::new_from_slice(cache_key()).expect("HMAC takes a key of any length");
    mac.update(format!("{user}\0{password}").as_bytes());
    mac.finalize().into_bytes().into()
}

impl WebSecurity {
    pub(crate) fn has_users(&self) -> bool {
        !self.users.is_empty()
    }

    /// Whether an Authorization header satisfies basic auth (always, with no users).
    pub(crate) fn authorized(&self, header: Option<&str>) -> bool {
        if self.users.is_empty() {
            return true;
        }
        let (scheme, encoded) = header.unwrap_or("").split_once(' ').unwrap_or(("", ""));
        if !scheme.eq_ignore_ascii_case("basic") {
            return false;
        }
        let Ok(decoded) = base64::engine::general_purpose::STANDARD.decode(encoded) else {
            return false;
        };
        let Ok(text) = String::from_utf8(decoded) else {
            return false;
        };
        match text.split_once(':') {
            Some((user, password)) => self.authenticate(user, password),
            None => false,
        }
    }

    fn authenticate(&self, user: &str, password: &str) -> bool {
        let digest = cache_digest(user, password);
        if crate::_lock::lock(&self.verified).contains(&digest) {
            return true;
        }
        let Some(hashed) = self.users.get(user) else {
            let _ = bcrypt::verify(password, DUMMY_HASH);
            return false;
        };
        if !bcrypt::verify(password, hashed).unwrap_or(false) {
            return false;
        }
        crate::_lock::lock(&self.verified).insert(digest);
        true
    }
}

/// A YAML scalar as text; `None` for null, sequences and mappings.
fn scalar(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.clone()),
        Value::Number(number) => Some(number.to_string()),
        Value::Bool(flag) => Some(flag.to_string()),
        _ => None,
    }
}

fn only_keys(map: &serde_yaml::Mapping, allowed: &[&str]) -> bool {
    map.keys()
        .all(|key| key.as_str().is_some_and(|key| allowed.contains(&key)))
}

/// Read and validate a web config file; any problem is an error message.
pub(crate) fn load_web_config(path: &str) -> Result<WebSecurity, String> {
    let text = std::fs::read_to_string(path).map_err(|err| format!("web config {path}: {err}"))?;
    let data: Value =
        serde_yaml::from_str(&text).map_err(|err| format!("web config {path}: {err}"))?;
    let map = match data {
        Value::Null => return Ok(WebSecurity::default()),
        Value::Mapping(map) if only_keys(&map, &TOP_KEYS) => map,
        _ => {
            return Err(format!(
                "web config {path}: only {TOP_KEYS:?} are supported"
            ))
        }
    };
    let base = Path::new(path).parent().unwrap_or(Path::new(""));
    let users = match map.get("basic_auth_users") {
        None | Some(Value::Null) => HashMap::new(),
        Some(Value::Mapping(raw)) => users(raw, path)?,
        Some(_) => {
            return Err(format!(
                "web config {path}: basic_auth_users must map user names to bcrypt hashes"
            ))
        }
    };
    let tls = match map.get("tls_server_config") {
        None => None,
        Some(raw) => Some(tls(raw, base)?),
    };
    Ok(WebSecurity {
        users,
        tls,
        verified: Mutex::default(),
    })
}

fn users(raw: &serde_yaml::Mapping, path: &str) -> Result<HashMap<String, String>, String> {
    let mut users = HashMap::new();
    for (user, hashed) in raw {
        let user = scalar(user).unwrap_or_default();
        let hashed = scalar(hashed).unwrap_or_default();
        let well_formed = hashed
            .parse::<bcrypt::HashParts>()
            .is_ok_and(|parts| (4..=31).contains(&parts.get_cost()));
        if !well_formed {
            return Err(format!(
                "web config {path}: basic_auth_users[{user}] is not a bcrypt hash"
            ));
        }
        users.insert(user, hashed);
    }
    Ok(users)
}

fn tls(raw: &Value, base: &Path) -> Result<TlsReloader, String> {
    let map = match raw {
        Value::Mapping(map) if only_keys(map, &TLS_KEYS) => map,
        _ => {
            return Err(format!(
                "tls_server_config: only {TLS_KEYS:?} are supported"
            ))
        }
    };
    let field = |key: &str| map.get(key).and_then(scalar).filter(|v| !v.is_empty());
    let (Some(cert), Some(key)) = (field("cert_file"), field("key_file")) else {
        return Err("tls_server_config needs cert_file and key_file".to_string());
    };
    let min_version = field("min_version").unwrap_or_else(|| "TLS12".to_string());
    let tls13_only = match min_version.as_str() {
        "TLS12" => false,
        "TLS13" => true,
        other => {
            return Err(format!(
                "tls_server_config.min_version {other:?}: want TLS12 or TLS13"
            ))
        }
    };
    let ca = field("client_ca_file");
    let default_auth = if ca.is_some() {
        "RequireAndVerifyClientCert"
    } else {
        "NoClientCert"
    };
    let auth_name = field("client_auth_type").unwrap_or_else(|| default_auth.to_string());
    let client_auth = match auth_name.as_str() {
        "NoClientCert" => ClientAuth::None,
        "RequireAndVerifyClientCert" => ClientAuth::Require,
        "VerifyClientCertIfGiven" => ClientAuth::IfGiven,
        other => {
            return Err(format!(
                "tls_server_config.client_auth_type {other:?} is not supported"
            ))
        }
    };
    if client_auth != ClientAuth::None && ca.is_none() {
        return Err(format!(
            "tls_server_config.client_auth_type {auth_name} needs client_ca_file"
        ));
    }
    TlsReloader::new(TlsSettings {
        cert: base.join(cert),
        key: base.join(key),
        ca: ca.map(|ca| base.join(ca)),
        client_auth,
        tls13_only,
    })
    .map_err(|err| format!("tls_server_config: {err}"))
}

#[cfg(test)]
#[path = "web_config_tests.rs"]
mod tests;
