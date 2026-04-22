// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

func _signalEndpointURL(endpoint, signalPath string) string {
	trimmed := strings.TrimSpace(endpoint)
	if trimmed == "" {
		return ""
	}
	if parsed, err := url.Parse(trimmed); err == nil && parsed.Scheme != "" && parsed.Host != "" {
		currentPath := strings.TrimRight(parsed.Path, "/")
		switch {
		case currentPath == "":
			parsed.Path = signalPath
		case !strings.HasSuffix(currentPath, signalPath):
			parsed.Path = currentPath + signalPath
		default:
			parsed.Path = currentPath
		}
		return parsed.String()
	}
	if strings.HasSuffix(strings.TrimRight(trimmed, "/"), signalPath) {
		return trimmed
	}
	return strings.TrimRight(trimmed, "/") + signalPath
}

func _validateURLPort(portStr string, parsed *url.URL, signalURL string) error {
	if portStr != "" {
		port, err := strconv.Atoi(portStr)
		if err != nil || port < 1 || port > 65535 {
			return fmt.Errorf("invalid OTLP endpoint port in %q", signalURL)
		}
	}
	hostAfterBracket := parsed.Host
	if idx := strings.LastIndex(parsed.Host, "]"); idx >= 0 {
		hostAfterBracket = parsed.Host[idx+1:]
	}
	if portStr == "" && strings.Contains(hostAfterBracket, ":") {
		return fmt.Errorf("invalid OTLP endpoint port in %q", signalURL)
	}
	return nil
}

func _validatedSignalEndpointURL(endpoint, signalPath string) (string, error) {
	if strings.TrimSpace(endpoint) == "" {
		return "", fmt.Errorf("invalid OTLP endpoint URL %q", endpoint)
	}
	signalURL := _signalEndpointURL(endpoint, signalPath)
	parsed, err := url.Parse(signalURL)
	if err != nil {
		return "", err
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return "", fmt.Errorf("invalid OTLP endpoint URL %q", signalURL)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", fmt.Errorf("invalid OTLP endpoint scheme %q in %q", parsed.Scheme, signalURL)
	}
	if err := _validateURLPort(parsed.Port(), parsed, signalURL); err != nil {
		return "", err
	}
	return signalURL, nil
}
