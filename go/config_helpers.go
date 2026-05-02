// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

// strTrue and strFalse are the canonical string representations of boolean values
// used when parsing environment variables.
const (
	strTrue  = "true"
	strFalse = "false"
)

// validateRate returns a ConfigurationError if v is not in [0.0, 1.0].
func validateRate(v float64, field string) error {
	if v < 0.0 || v > 1.0 {
		return NewConfigurationError(fmt.Sprintf("%s must be in [0.0, 1.0], got %g", field, v))
	}
	return nil
}

// validateNonNegative returns a ConfigurationError if v is negative.
func validateNonNegative(v int, field string) error {
	if v < 0 {
		return NewConfigurationError(fmt.Sprintf("%s must be >= 0, got %d", field, v))
	}
	return nil
}

// validateNonNegativeFloat returns a ConfigurationError if v is negative.
func validateNonNegativeFloat(v float64, field string) error {
	if v < 0 {
		return NewConfigurationError(fmt.Sprintf("%s must be >= 0, got %g", field, v))
	}
	return nil
}

func parseEnvBool(value string, defaultVal bool, field string) (bool, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return defaultVal, nil
	}
	switch strings.ToLower(trimmed) {
	case "1", strTrue, "yes", "on":
		return true, nil
	case "0", strFalse, "no", "off":
		return false, nil
	default:
		return false, NewConfigurationError(
			fmt.Sprintf("invalid boolean for %s: %q (expected one of: 1,true,yes,on,0,false,no,off)", field, value),
		)
	}
}

// normalizeLevel validates and normalises a log level string.
func normalizeLevel(value string) (string, error) {
	allowed := map[string]struct{}{
		LogLevelTrace: {}, LogLevelDebug: {}, LogLevelInfo: {},
		LogLevelWarning: {}, LogLevelError: {}, LogLevelCritical: {},
	}
	upper := strings.ToUpper(strings.TrimSpace(value))
	if _, ok := allowed[upper]; !ok {
		return "", NewConfigurationError(fmt.Sprintf("invalid log level: %s", value))
	}
	return upper, nil
}

// validateFormat checks that the log format is one of the allowed values.
func validateFormat(value string) error {
	switch value {
	case LogFormatConsole, LogFormatJSON, LogFormatPretty:
		return nil
	default:
		return NewConfigurationError(fmt.Sprintf("invalid log format: %s", value))
	}
}

// parseEnvFloat parses a float64 from a string, returning ConfigurationError on failure.
func parseEnvFloat(value, field string) (float64, error) {
	f, err := strconv.ParseFloat(strings.TrimSpace(value), 64)
	if err != nil {
		return 0, NewConfigurationError(fmt.Sprintf("invalid float for %s: %q", field, value))
	}
	return f, nil
}

// parseEnvInt parses an int from a string, returning ConfigurationError on failure.
func parseEnvInt(value, field string) (int, error) {
	n, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, NewConfigurationError(fmt.Sprintf("invalid integer for %s: %q", field, value))
	}
	return n, nil
}

// parseOTLPHeaders parses "key=value,key2=value2" into a map.
// Keys and values are URL-decoded. Malformed pairs are skipped.
func parseOTLPHeaders(raw string) map[string]string {
	headers := map[string]string{}
	if raw == "" {
		return headers
	}
	for _, pair := range strings.Split(raw, ",") {
		idx := strings.Index(pair, "=")
		if idx < 1 {
			// malformed or empty key — skip
			continue
		}
		rawKey := strings.TrimSpace(pair[:idx])
		rawVal := strings.TrimSpace(pair[idx+1:])
		// Use PathUnescape so that '+' is preserved as a literal character
		// (QueryUnescape decodes '+' as space, which breaks header names like
		// "x-api+json").
		key, err := url.PathUnescape(rawKey)
		if err != nil || key == "" {
			continue
		}
		val, err := url.PathUnescape(rawVal)
		if err != nil {
			continue
		}
		headers[key] = val
	}
	return headers
}

// parseModuleLevels parses "module=LEVEL,module2=LEVEL2" into a map.
// Malformed pairs and invalid levels are skipped.
func parseModuleLevels(raw string) (map[string]string, error) {
	result := map[string]string{}
	if strings.TrimSpace(raw) == "" {
		return result, nil
	}
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		idx := strings.Index(pair, "=")
		if idx < 1 {
			// malformed or empty module name — skip
			continue
		}
		module := strings.TrimSpace(pair[:idx])
		levelStr := strings.TrimSpace(pair[idx+1:])
		normalized, err := normalizeLevel(levelStr)
		if err != nil {
			return nil, err
		}
		result[module] = normalized
	}
	return result, nil
}

// splitTrimmed splits a string by sep and trims whitespace from each element,
// omitting empty strings.
func splitTrimmed(s, sep string) []string {
	parts := strings.Split(s, sep)
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// firstNonEmpty returns the first non-empty string among the provided values.
func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
