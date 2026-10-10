// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"bytes"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"golang.org/x/crypto/bcrypt"
	"gopkg.in/yaml.v3"
)

// _webConfigFile is the subset of the Prometheus web config format
// (--web.config.file) every SDK reads; see prometheus_metrics.listener_security.
// Decoding rejects any other key, so a setting this SDK would ignore fails
// loudly instead of silently weakening the listener.
type _webConfigFile struct {
	TLS            *_webTLSConfig    `yaml:"tls_server_config"`
	BasicAuthUsers map[string]string `yaml:"basic_auth_users"`
}

type _webTLSConfig struct {
	CertFile       string `yaml:"cert_file"`
	KeyFile        string `yaml:"key_file"`
	ClientCAFile   string `yaml:"client_ca_file"`
	ClientAuthType string `yaml:"client_auth_type"`
	MinVersion     string `yaml:"min_version"`
}

const (
	_clientAuthNone       = "NoClientCert"
	_clientAuthRequire    = "RequireAndVerifyClientCert"
	_clientAuthIfGiven    = "VerifyClientCertIfGiven"
	_defaultMinTLSVersion = "TLS12"
)

var _webClientAuthTypes = map[string]tls.ClientAuthType{ //nolint:gochecknoglobals
	_clientAuthNone:    tls.NoClientCert,
	_clientAuthRequire: tls.RequireAndVerifyClientCert,
	_clientAuthIfGiven: tls.VerifyClientCertIfGiven,
}

var _webMinVersions = map[string]uint16{ //nolint:gochecknoglobals
	"TLS12": tls.VersionTLS12,
	"TLS13": tls.VersionTLS13,
}

// _webSecurity is a loaded, validated web config: an optional TLS config and
// the basic-auth users.
type _webSecurity struct {
	tlsConfig *tls.Config
	users     map[string][]byte
	verified  sync.Map // sha256(user, password) -> struct{}; successful checks only
}

// _loadWebConfig reads and validates the file at path. Any problem is an error,
// and the caller must then not start the listener: the listener fails closed.
func _loadWebConfig(path string) (*_webSecurity, error) {
	raw, err := os.ReadFile(path) //nolint:gosec // operator-supplied config path
	if err != nil {
		return nil, fmt.Errorf("web config: %w", err)
	}
	var file _webConfigFile
	decoder := yaml.NewDecoder(bytes.NewReader(raw))
	decoder.KnownFields(true)
	if err := decoder.Decode(&file); err != nil {
		return nil, fmt.Errorf("web config %s: %w", path, err)
	}
	security := &_webSecurity{users: map[string][]byte{}}
	for user, hash := range file.BasicAuthUsers {
		if _, err := bcrypt.Cost([]byte(hash)); err != nil {
			return nil, fmt.Errorf("web config %s: basic_auth_users[%s] is not a bcrypt hash: %w", path, user, err)
		}
		security.users[user] = []byte(hash)
	}
	if file.TLS != nil {
		tlsConfig, err := _webTLS(file.TLS, filepath.Dir(path))
		if err != nil {
			return nil, fmt.Errorf("web config %s: %w", path, err)
		}
		security.tlsConfig = tlsConfig
	}
	return security, nil
}

func _webTLS(c *_webTLSConfig, dir string) (*tls.Config, error) {
	if c.CertFile == "" || c.KeyFile == "" {
		return nil, errors.New("tls_server_config needs cert_file and key_file")
	}
	minVersion, ok := _webMinVersions[_orDefault(c.MinVersion, _defaultMinTLSVersion)]
	if !ok {
		return nil, fmt.Errorf("tls_server_config.min_version %q: want TLS12 or TLS13", c.MinVersion)
	}
	clientAuth, err := _webClientAuth(c)
	if err != nil {
		return nil, err
	}
	reloader := &_certReloader{certFile: _resolve(dir, c.CertFile), keyFile: _resolve(dir, c.KeyFile)}
	if _, err := reloader.certificate(); err != nil {
		return nil, err
	}
	config := &tls.Config{MinVersion: minVersion, ClientAuth: clientAuth, GetCertificate: reloader.getCertificate}
	if c.ClientCAFile != "" {
		pool, err := _clientCAPool(_resolve(dir, c.ClientCAFile))
		if err != nil {
			return nil, err
		}
		config.ClientCAs = pool
	}
	return config, nil
}

// _webClientAuth resolves client_auth_type. It defaults to requiring a client
// certificate when client_ca_file is set, and to none otherwise.
func _webClientAuth(c *_webTLSConfig) (tls.ClientAuthType, error) {
	defaultAuth := _clientAuthNone
	if c.ClientCAFile != "" {
		defaultAuth = _clientAuthRequire
	}
	clientAuth, ok := _webClientAuthTypes[_orDefault(c.ClientAuthType, defaultAuth)]
	if !ok {
		return 0, fmt.Errorf("tls_server_config.client_auth_type %q is not supported", c.ClientAuthType)
	}
	if clientAuth != tls.NoClientCert && c.ClientCAFile == "" {
		return 0, fmt.Errorf("tls_server_config.client_auth_type %s needs client_ca_file", c.ClientAuthType)
	}
	return clientAuth, nil
}

func _clientCAPool(path string) (*x509.CertPool, error) {
	pem, err := os.ReadFile(path) //nolint:gosec // operator-supplied config path
	if err != nil {
		return nil, fmt.Errorf("client_ca_file: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(pem) {
		return nil, errors.New("client_ca_file holds no PEM certificates")
	}
	return pool, nil
}

func _orDefault(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

// _resolve makes a relative path in the web config relative to the file's directory.
func _resolve(dir, path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	return filepath.Join(dir, path)
}

// _certReloader serves the certificate and re-reads it when either file's
// modification time changes, checked on each new connection, so rotation needs
// no restart. A reload that fails fails the handshake rather than serving the
// stale pair.
type _certReloader struct {
	certFile, keyFile string
	mu                sync.Mutex
	cert              *tls.Certificate
	certMod, keyMod   time.Time
}

func (r *_certReloader) getCertificate(*tls.ClientHelloInfo) (*tls.Certificate, error) {
	return r.certificate()
}

func (r *_certReloader) certificate() (*tls.Certificate, error) {
	certInfo, err := os.Stat(r.certFile)
	if err != nil {
		return nil, fmt.Errorf("cert_file: %w", err)
	}
	keyInfo, err := os.Stat(r.keyFile)
	if err != nil {
		return nil, fmt.Errorf("key_file: %w", err)
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.cert != nil && certInfo.ModTime().Equal(r.certMod) && keyInfo.ModTime().Equal(r.keyMod) {
		return r.cert, nil
	}
	pair, err := tls.LoadX509KeyPair(r.certFile, r.keyFile)
	if err != nil {
		return nil, fmt.Errorf("load certificate: %w", err)
	}
	r.cert, r.certMod, r.keyMod = &pair, certInfo.ModTime(), keyInfo.ModTime()
	return r.cert, nil
}

// _dummyBcryptHash is compared against when the user is unknown, so a wrong
// user name costs the same time as a wrong password. It must be a well-formed
// cost-10 hash, or the comparison would return early and leak that difference;
// what it hashes does not matter.
var _dummyBcryptHash = []byte("$2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq") //nolint:gochecknoglobals

// requireAuth wraps next with basic auth when users are configured.
func (s *_webSecurity) requireAuth(next http.Handler) http.Handler {
	if len(s.users) == 0 {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if user, password, ok := r.BasicAuth(); ok && s.authenticate(user, password) {
			next.ServeHTTP(w, r)
			return
		}
		w.Header().Set("WWW-Authenticate", "Basic")
		http.Error(w, "unauthorized", http.StatusUnauthorized)
	})
}

func (s *_webSecurity) authenticate(user, password string) bool {
	key := sha256.Sum256([]byte(user + "\x00" + password))
	if _, ok := s.verified.Load(key); ok {
		return true
	}
	hash, known := s.users[user]
	if !known {
		_ = bcrypt.CompareHashAndPassword(_dummyBcryptHash, []byte(password))
		return false
	}
	if bcrypt.CompareHashAndPassword(hash, []byte(password)) != nil {
		return false
	}
	s.verified.Store(key, struct{}{})
	return true
}
