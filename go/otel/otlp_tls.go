// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"strings"
	"sync"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// _tlsFileError is an OTLP TLS file that cannot be read or loaded (spec
// prometheus_metrics.push_security): that signal's exporter is not built.
type _tlsFileError struct{ msg string }

func (e *_tlsFileError) Error() string { return e.msg }

var (
	_tlsProblemsMu sync.Mutex //nolint:gochecknoglobals
	_tlsProblems   []string   //nolint:gochecknoglobals
)

// _otlpTLSPath returns the per-signal OTEL_EXPORTER_OTLP_<SIGNAL>_<KIND> value,
// or the shared OTEL_EXPORTER_OTLP_<KIND> when that is unset, with its name.
func _otlpTLSPath(signal, kind string, getenv func(string) string) (path, name string) {
	name = "OTEL_EXPORTER_OTLP_" + signal + "_" + kind
	if path = getenv(name); path != "" {
		return path, name
	}
	name = "OTEL_EXPORTER_OTLP_" + kind
	return getenv(name), name
}

// _otlpTLSConfig builds the TLS config for signal ("LOGS", "TRACES" or
// "METRICS") from the environment, or nil when nothing is configured. Passing
// it explicitly keeps the exporter from reading the variables itself, which on
// an unreadable file logs and falls back to the system roots.
func _otlpTLSConfig(signal string, getenv func(string) string) (*tls.Config, error) {
	ca, caName := _otlpTLSPath(signal, "CERTIFICATE", getenv)
	cert, certName := _otlpTLSPath(signal, "CLIENT_CERTIFICATE", getenv)
	key, keyName := _otlpTLSPath(signal, "CLIENT_KEY", getenv)
	contents := map[string][]byte{}
	for _, f := range [][2]string{{caName, ca}, {certName, cert}, {keyName, key}} {
		if f[1] == "" {
			continue
		}
		data, err := os.ReadFile(f[1])
		if err != nil {
			return nil, &_tlsFileError{fmt.Sprintf("%s=%s: %v", f[0], f[1], _pathErrorReason(err))}
		}
		contents[f[0]] = data
	}
	config := &tls.Config{MinVersion: tls.VersionTLS12}
	configured := false
	if ca != "" {
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(contents[caName]) {
			return nil, &_tlsFileError{fmt.Sprintf("%s=%s: no PEM certificates", caName, ca)}
		}
		config.RootCAs, configured = pool, true
	}
	if cert != "" && key != "" {
		pair, err := tls.X509KeyPair(contents[certName], contents[keyName])
		if err != nil {
			return nil, &_tlsFileError{fmt.Sprintf("%s=%s, %s=%s: %v", certName, cert, keyName, key, err)}
		}
		config.Certificates, configured = []tls.Certificate{pair}, true
	}
	if !configured {
		return nil, nil
	}
	return config, nil
}

// _pathErrorReason drops the operation and path that *fs.PathError repeats.
func _pathErrorReason(err error) error {
	var pathErr *fs.PathError
	if errors.As(err, &pathErr) {
		return pathErr.Err
	}
	return err
}

// _otlpTLSFor resolves signal's TLS config, noting a problem for setup_error.
func _otlpTLSFor(signal string) (*tls.Config, error) {
	config, err := _otlpTLSConfig(signal, os.Getenv)
	if err != nil {
		_tlsProblemsMu.Lock()
		_tlsProblems = append(_tlsProblems, err.Error())
		_tlsProblemsMu.Unlock()
		if logger := telemetry.Logger(); logger != nil {
			logger.Warn("otlp.tls_file_unreadable", slog.String("signal", strings.ToLower(signal)), slog.String("error", err.Error()))
		}
	}
	return config, err
}

// _takeTLSProblems returns the problems noted since the last call, joined, and clears them.
func _takeTLSProblems() string {
	_tlsProblemsMu.Lock()
	defer _tlsProblemsMu.Unlock()
	joined := strings.Join(_tlsProblems, "; ")
	_tlsProblems = nil
	return joined
}
