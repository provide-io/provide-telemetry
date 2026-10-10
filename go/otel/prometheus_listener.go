// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"sync"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// _listenerKey is what makes a running listener stale: any change restarts it.
type _listenerKey struct {
	host      string
	port      int
	path      string
	webConfig string
}

type _runningListener struct {
	key    _listenerKey
	server *http.Server
	addr   net.Addr
}

var (
	_listenerMu sync.Mutex        //nolint:gochecknoglobals
	_listener   *_runningListener //nolint:gochecknoglobals
)

// _syncPromListener makes the standalone listener match cfg: started when
// cfg asks for it, stopped when it does not, restarted when its address, path
// or web config changed, and left alone otherwise. A failure to start is
// logged and reported through report; it never fails setup.
func _syncPromListener(cfg *telemetry.TelemetryConfig, report func(string)) {
	_listenerMu.Lock()
	defer _listenerMu.Unlock()
	if !cfg.Metrics.PrometheusListenerEnabled() {
		_stopListenerLocked()
		return
	}
	p := cfg.Metrics.Prometheus
	key := _listenerKey{host: p.Host, port: p.Port, path: p.Path, webConfig: p.WebConfig}
	if _listener != nil && _listener.key == key {
		return
	}
	_stopListenerLocked()
	running, err := _startListener(key)
	if err != nil {
		msg := "prometheus listener: " + err.Error()
		report(msg)
		if logger := telemetry.Logger(); logger != nil {
			logger.Warn("otel.prometheus_listener_failed", slog.String("error", err.Error()))
		}
		return
	}
	_listener = running
}

func _startListener(key _listenerKey) (*_runningListener, error) {
	security := &_webSecurity{users: map[string][]byte{}}
	if key.webConfig != "" {
		loaded, err := _loadWebConfig(key.webConfig)
		if err != nil {
			return nil, err
		}
		security = loaded
	}
	ln, err := net.Listen("tcp", net.JoinHostPort(key.host, strconv.Itoa(key.port)))
	if err != nil {
		return nil, err
	}
	_warnListenerExposure(key.host, security)
	server := &http.Server{
		Handler:           _exactPath(key.path, security.requireAuth(MetricsHandler())),
		TLSConfig:         security.tlsConfig,
		ReadHeaderTimeout: _listenerReadHeaderTimeout,
		ReadTimeout:       _listenerReadTimeout,
		WriteTimeout:      _listenerWriteTimeout,
		IdleTimeout:       _listenerIdleTimeout,
	}
	go _serve(server, ln, security.tlsConfig != nil)
	return &_runningListener{key: key, server: server, addr: ln.Addr()}, nil
}

func _serve(server *http.Server, ln net.Listener, useTLS bool) {
	var err error
	if useTLS {
		err = server.ServeTLS(ln, "", "")
	} else {
		err = server.Serve(ln)
	}
	if err != nil && !errors.Is(err, http.ErrServerClosed) {
		if logger := telemetry.Logger(); logger != nil {
			logger.Warn("otel.prometheus_listener_stopped", slog.String("error", err.Error()))
		}
	}
}

// _exactPath answers 404 for every path but the configured one.
func _exactPath(path string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != path {
			http.NotFound(w, r)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// _warnListenerExposure logs once per start when the listener is reachable
// beyond this host, or sends credentials without TLS.
func _warnListenerExposure(host string, security *_webSecurity) {
	logger := telemetry.Logger()
	if logger == nil {
		return
	}
	if !_isLoopback(host) {
		logger.Warn("otel.prometheus_listener_exposed", slog.String("host", host),
			slog.String("hint", "the listener is reachable from other hosts; secure it with PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG"))
	}
	if len(security.users) > 0 && security.tlsConfig == nil {
		logger.Warn("otel.prometheus_listener_cleartext_auth",
			slog.String("hint", "basic_auth_users without tls_server_config sends credentials in clear text"))
	}
}

func _isLoopback(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func _stopListenerLocked() {
	if _listener == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), _listenerShutdownTimeout)
	defer cancel()
	_ = _listener.server.Shutdown(ctx)
	_listener = nil
}

func _stopPromListener() {
	_listenerMu.Lock()
	defer _listenerMu.Unlock()
	_stopListenerLocked()
}

// _promListenerAddr returns the bound address of the running listener, or "".
func _promListenerAddr() string {
	_listenerMu.Lock()
	defer _listenerMu.Unlock()
	if _listener == nil {
		return ""
	}
	return _listener.addr.String()
}
