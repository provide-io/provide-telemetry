// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// prometheus_listener_test.go covers the standalone listener: the
// listener_web_config cases of spec/prometheus_fixtures.yaml over real TLS and
// basic auth, its lifecycle, and its fail-closed paths.

package otel

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"golang.org/x/crypto/bcrypt"
	"gopkg.in/yaml.v3"
)

const _testPassword = "e2e-test-only-password"

// _pki is a throwaway CA with a server certificate for 127.0.0.1 and a client
// certificate, written as PEM files into dir.
type _pki struct {
	dir                           string
	caFile, certFile, keyFile     string
	clientCertFile, clientKeyFile string
	pool                          *x509.CertPool
	caCert                        *x509.Certificate
	caKey                         *ecdsa.PrivateKey
}

func _newPKI(t *testing.T) *_pki {
	t.Helper()
	dir := t.TempDir()
	caKey, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	caTmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "test CA"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign,
	}
	caDER, _ := x509.CreateCertificate(rand.Reader, caTmpl, caTmpl, &caKey.PublicKey, caKey)
	caCert, _ := x509.ParseCertificate(caDER)
	p := &_pki{dir: dir, caCert: caCert, caKey: caKey, pool: x509.NewCertPool()}
	p.pool.AddCert(caCert)
	p.caFile = _writePEM(t, dir, "ca.crt", "CERTIFICATE", caDER)
	p.certFile, p.keyFile = p.issue(t, "server", 2, x509.ExtKeyUsageServerAuth)
	p.clientCertFile, p.clientKeyFile = p.issue(t, "client", 3, x509.ExtKeyUsageClientAuth)
	return p
}

func (p *_pki) issue(t *testing.T, name string, serial int64, usage x509.ExtKeyUsage) (string, string) {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(serial), Subject: pkix.Name{CommonName: name},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		ExtKeyUsage: []x509.ExtKeyUsage{usage}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")},
	}
	der, _ := x509.CreateCertificate(rand.Reader, tmpl, p.caCert, &key.PublicKey, p.caKey)
	keyDER, _ := x509.MarshalECPrivateKey(key)
	return _writePEM(t, p.dir, name+".crt", "CERTIFICATE", der), _writePEM(t, p.dir, name+".key", "EC PRIVATE KEY", keyDER)
}

func _writePEM(t *testing.T, dir, name, kind string, der []byte) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, pem.EncodeToMemory(&pem.Block{Type: kind, Bytes: der}), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

type _webConfigCase struct {
	ID                 string                 `yaml:"id"`
	WebConfig          map[string]interface{} `yaml:"web_config"`
	WebConfigPath      string                 `yaml:"web_config_path"`
	Listener           bool                   `yaml:"listener"`
	Scheme             string                 `yaml:"scheme"`
	Auth               bool                   `yaml:"auth"`
	ClientCertRequired bool                   `yaml:"client_cert_required"`
	Error              bool                   `yaml:"error"`
}

func _loadWebConfigCases(t *testing.T) []_webConfigCase {
	t.Helper()
	data, err := os.ReadFile("../../spec/prometheus_fixtures.yaml")
	if err != nil {
		t.Fatal(err)
	}
	var f struct {
		Cases []_webConfigCase `yaml:"listener_web_config"`
	}
	if err := yaml.Unmarshal(data, &f); err != nil {
		t.Fatal(err)
	}
	return f.Cases
}

// _writeWebConfig renders a fixture web config with real file paths and hash.
func _writeWebConfig(t *testing.T, p *_pki, config map[string]interface{}) string {
	t.Helper()
	hash, _ := bcrypt.GenerateFromPassword([]byte(_testPassword), bcrypt.MinCost)
	raw, _ := yaml.Marshal(config)
	text := strings.NewReplacer(
		"{cert}", p.certFile, "{key}", p.keyFile, "{ca}", p.caFile,
		"{missing}", filepath.Join(p.dir, "missing.pem"), "bcrypt_of_e2e_test_only_password", string(hash),
	).Replace(string(raw))
	path := filepath.Join(p.dir, "web.yml")
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func _listenerEnv(t *testing.T, webConfig string) {
	t.Helper()
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	t.Setenv("PROVIDE_METRICS_PROMETHEUS_LISTEN", "true")
	t.Setenv("OTEL_EXPORTER_PROMETHEUS_PORT", "0")
	t.Setenv("PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG", webConfig)
}

func _client(p *_pki, withClientCert bool) *http.Client {
	tlsConfig := &tls.Config{RootCAs: p.pool, MinVersion: tls.VersionTLS12}
	if withClientCert {
		pair, _ := tls.LoadX509KeyPair(p.clientCertFile, p.clientKeyFile)
		tlsConfig.Certificates = []tls.Certificate{pair}
	}
	return &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{TLSClientConfig: tlsConfig, Proxy: nil}}
}

func _get(t *testing.T, client *http.Client, url string, auth bool) (*http.Response, error) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodGet, url, nil)
	if auth {
		req.SetBasicAuth("e2e", _testPassword)
	}
	resp, err := client.Do(req)
	if err == nil {
		t.Cleanup(func() { _ = resp.Body.Close() })
	}
	return resp, err
}

func TestPrometheusListener_WebConfigFixtures(t *testing.T) {
	for _, c := range _loadWebConfigCases(t) {
		t.Run(c.ID, func(t *testing.T) {
			_promReset(t)
			p := _newPKI(t)
			path := ""
			switch {
			case c.WebConfigPath != "":
				path = strings.ReplaceAll(c.WebConfigPath, "{missing}", filepath.Join(p.dir, "missing.yml"))
			case c.WebConfig != nil:
				path = _writeWebConfig(t, p, c.WebConfig)
			}
			_listenerEnv(t, path)
			_promSetup(t)
			addr := _promListenerAddr()
			if (addr != "") != c.Listener {
				t.Fatalf("listener running = %v, want %v", addr != "", c.Listener)
			}
			if c.Error {
				if got := telemetry.GetHealthSnapshot().SetupError; !strings.Contains(got, "prometheus listener") {
					t.Fatalf("SetupError = %q, want a prometheus listener failure", got)
				}
				return
			}
			_checkListener(t, p, c, "http"+map[bool]string{true: "s", false: ""}[c.Scheme == "https"]+"://"+addr+"/metrics")
		})
	}
}

func _checkListener(t *testing.T, p *_pki, c _webConfigCase, url string) {
	t.Helper()
	client := _client(p, false)
	if c.ClientCertRequired {
		if _, err := _get(t, client, url, false); err == nil {
			t.Fatal("a scrape without a client certificate must fail the handshake")
		}
		client = _client(p, true)
	}
	if c.Auth {
		resp, err := _get(t, client, url, false)
		if err != nil || resp.StatusCode != http.StatusUnauthorized || resp.Header.Get("WWW-Authenticate") != "Basic" {
			t.Fatalf("unauthenticated scrape: %v %v", resp, err)
		}
	}
	resp, err := _get(t, client, url, c.Auth)
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Fatalf("scrape: %v %v", resp, err)
	}
}

func TestPrometheusListener_OnlyTheConfiguredPath(t *testing.T) {
	_promReset(t)
	_listenerEnv(t, "")
	t.Setenv("PROVIDE_METRICS_PROMETHEUS_PATH", "/internal/metrics")
	_promSetup(t)
	base := "http://" + _promListenerAddr()
	client := &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{Proxy: nil}}
	for path, want := range map[string]int{"/internal/metrics": 200, "/metrics": 404, "/internal/metrics/x": 404} {
		resp, err := _get(t, client, base+path, false)
		if err != nil || resp.StatusCode != want {
			t.Errorf("%s: %v %v, want %d", path, resp, err, want)
		}
	}
}

func TestPrometheusListener_KeepsRunningListenerUntilItsKeyChanges(t *testing.T) {
	_promReset(t)
	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Metrics.Exporters = []string{"prometheus"}
	cfg.Metrics.Prometheus.Listen = "true"
	cfg.Metrics.Prometheus.Port = 0
	report := func(msg string) { t.Fatalf("unexpected listener failure: %s", msg) }
	_syncPromListener(cfg, report)
	first := _listener
	_syncPromListener(cfg, report)
	if _listener != first {
		t.Fatal("an unchanged config must keep the running listener")
	}
	cfg.Metrics.Prometheus.Path = "/other"
	_syncPromListener(cfg, report)
	if _listener == first || _listener == nil {
		t.Fatal("a changed path must restart the listener")
	}
	cfg.Metrics.Prometheus.Listen = "false"
	_syncPromListener(cfg, report)
	if _promListenerAddr() != "" {
		t.Fatal("turning the listener off must stop it")
	}
	_stopPromListener() // stopping twice is a no-op
}

func TestPrometheusListener_BindFailureIsReportedAndClearedByNextSetup(t *testing.T) {
	_promReset(t)
	busy, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = busy.Close() })
	_listenerEnv(t, "")
	t.Setenv("OTEL_EXPORTER_PROMETHEUS_PORT", strings.Split(busy.Addr().String(), ":")[1])
	_promSetup(t)
	if _promListenerAddr() != "" || !strings.Contains(telemetry.GetHealthSnapshot().SetupError, "prometheus listener") {
		t.Fatalf("bind failure not reported: %q", telemetry.GetHealthSnapshot().SetupError)
	}
	resetSetupState(t)
	_listenerEnv(t, "")
	_promSetup(t)
	if got := telemetry.GetHealthSnapshot().SetupError; got != "" {
		t.Fatalf("a successful setup must clear SetupError, got %q", got)
	}
}

func TestPrometheusListener_ReloadsRotatedCertificate(t *testing.T) {
	p := _newPKI(t)
	reloader := &_certReloader{certFile: p.certFile, keyFile: p.keyFile}
	first, err := reloader.certificate()
	if err != nil {
		t.Fatal(err)
	}
	if again, _ := reloader.certificate(); again != first {
		t.Fatal("an unchanged pair must be served from cache")
	}
	newCert, newKey := p.issue(t, "server-rotated", 9, x509.ExtKeyUsageServerAuth)
	future := time.Now().Add(time.Minute)
	for src, dst := range map[string]string{newCert: p.certFile, newKey: p.keyFile} {
		data, _ := os.ReadFile(src)
		_ = os.WriteFile(dst, data, 0o600)
		_ = os.Chtimes(dst, future, future)
	}
	rotated, err := reloader.getCertificate(nil)
	if err != nil || rotated == first {
		t.Fatalf("rotated certificate not picked up: %v", err)
	}
	_ = os.WriteFile(p.keyFile, []byte("garbage"), 0o600)
	_ = os.Chtimes(p.keyFile, future.Add(time.Minute), future.Add(time.Minute))
	if _, err := reloader.certificate(); err == nil {
		t.Fatal("a broken rotation must fail rather than serve the stale pair")
	}
}

func TestPrometheusListener_CertificateStatFailures(t *testing.T) {
	p := _newPKI(t)
	missing := filepath.Join(p.dir, "nope.pem")
	for _, r := range []*_certReloader{{certFile: missing, keyFile: p.keyFile}, {certFile: p.certFile, keyFile: missing}} {
		if _, err := r.certificate(); err == nil {
			t.Fatalf("missing file %+v must fail", r)
		}
	}
}

func TestPrometheusWebConfig_RejectsInvalidSettings(t *testing.T) {
	p := _newPKI(t)
	noPEM := filepath.Join(p.dir, "empty.pem")
	_ = os.WriteFile(noPEM, []byte("not pem"), 0o600)
	cases := map[string]map[string]interface{}{
		"missing key_file":        {"tls_server_config": map[string]string{"cert_file": "{cert}"}},
		"bad client_auth_type":    {"tls_server_config": map[string]string{"cert_file": "{cert}", "key_file": "{key}", "client_auth_type": "Sometimes"}},
		"client auth without CA":  {"tls_server_config": map[string]string{"cert_file": "{cert}", "key_file": "{key}", "client_auth_type": "RequireAndVerifyClientCert"}},
		"client CA file missing":  {"tls_server_config": map[string]string{"cert_file": "{cert}", "key_file": "{key}", "client_ca_file": "{missing}"}},
		"client CA file not PEM":  {"tls_server_config": map[string]string{"cert_file": "{cert}", "key_file": "{key}", "client_ca_file": noPEM}},
		"user hash not bcrypt":    {"basic_auth_users": map[string]string{"e2e": "plaintext"}},
		"malformed yaml document": {"tls_server_config": "not a mapping"},
	}
	for name, config := range cases {
		if _, err := _loadWebConfig(_writeWebConfig(t, p, config)); err == nil {
			t.Errorf("%s: want an error", name)
		}
	}
}

func TestPrometheusWebConfig_RelativePathsAndOptionalSettings(t *testing.T) {
	p := _newPKI(t)
	path := _writeWebConfig(t, p, map[string]interface{}{"tls_server_config": map[string]string{
		"cert_file": filepath.Base(p.certFile), "key_file": filepath.Base(p.keyFile),
		"client_ca_file": filepath.Base(p.caFile), "client_auth_type": "VerifyClientCertIfGiven", "min_version": "TLS13",
	}})
	security, err := _loadWebConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	if security.tlsConfig.MinVersion != tls.VersionTLS13 || security.tlsConfig.ClientAuth != tls.VerifyClientCertIfGiven || security.tlsConfig.ClientCAs == nil {
		t.Fatalf("settings not applied: %+v", security.tlsConfig)
	}
	plain := &_webSecurity{users: map[string][]byte{}}
	if plain.requireAuth(MetricsHandler()) == nil {
		t.Fatal("no users must pass the handler through")
	}
}

func TestPrometheusWebConfig_Authenticate(t *testing.T) {
	hash, _ := bcrypt.GenerateFromPassword([]byte(_testPassword), bcrypt.MinCost)
	s := &_webSecurity{users: map[string][]byte{"e2e": hash}}
	if s.authenticate("nobody", _testPassword) || s.authenticate("e2e", "wrong") {
		t.Fatal("wrong user or password accepted")
	}
	if !s.authenticate("e2e", _testPassword) {
		t.Fatal("correct credentials rejected on the first (bcrypt) check")
	}
	if !s.authenticate("e2e", _testPassword) {
		t.Fatal("correct credentials rejected on the cached check")
	}
	if _, err := bcrypt.Cost(_dummyBcryptHash); err != nil {
		t.Fatalf("the dummy hash must be a real bcrypt hash: %v", err)
	}
}

func TestPrometheusListener_ExposureChecks(t *testing.T) {
	for host, want := range map[string]bool{"localhost": true, "127.0.0.1": true, "::1": true, "0.0.0.0": false, "example.com": false} {
		if got := _isLoopback(host); got != want {
			t.Errorf("_isLoopback(%q) = %v", host, got)
		}
	}
	resetSetupState(t)
	_warnListenerExposure("0.0.0.0", &_webSecurity{users: map[string][]byte{"u": nil}}) // no logger yet: must not panic
	_promReset(t)
	_promSetup(t)
	_warnListenerExposure("0.0.0.0", &_webSecurity{users: map[string][]byte{"u": nil}})
}

func TestPrometheusListener_ServeLogsUnexpectedStop(t *testing.T) {
	_promReset(t)
	_promSetup(t)
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	_ = ln.Close()
	_serve(&http.Server{ReadHeaderTimeout: time.Second}, ln, false)
	ln2, _ := net.Listen("tcp", "127.0.0.1:0")
	_ = ln2.Close()
	_serve(&http.Server{ReadHeaderTimeout: time.Second}, ln2, true)
	resetSetupState(t)
	ln3, _ := net.Listen("tcp", "127.0.0.1:0")
	_ = ln3.Close()
	_serve(&http.Server{ReadHeaderTimeout: time.Second}, ln3, false) // no logger: must not panic
}

func TestPrometheusListener_ServerTimeoutsAreExact(t *testing.T) {
	_promReset(t)
	_listenerEnv(t, "")
	_promSetup(t)
	srv := _listener.server
	got := []time.Duration{srv.ReadHeaderTimeout, srv.ReadTimeout, srv.WriteTimeout, srv.IdleTimeout, _listenerShutdownTimeout}
	want := []time.Duration{5 * time.Second, 10 * time.Second, 30 * time.Second, 60 * time.Second, 2 * time.Second}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("timeout %d = %v, want %v", i, got[i], want[i])
		}
	}
}
