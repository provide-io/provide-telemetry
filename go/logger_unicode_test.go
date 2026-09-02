// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
	"unicode/utf8"
)

// The SDK emits no non-ASCII of its own, so everything here arrives from a
// host: flavorpack prefixes its Go launcher stream with 🐹 to tell it apart
// from the Rust one on a shared log, and any consumer logging user data logs
// whatever alphabet that user writes in. Every rune below is multi-byte in
// UTF-8 and none of them survives a round trip through CP1252 or CP437, which
// is what makes this the test that fails first when an encoding step is
// silently inserted between the renderer and the writer.
//
// This test runs on every platform on purpose. Rendering is where Windows
// differs, and a suite that only ever runs on Linux cannot report that.
const (
	_unicodeMessage = "🐹 café ünïcode"
	_unicodeValue   = "🦀 naïve — 日本語 Ω"
	_unicodeKey     = "città"
)

// setupUnicodeSink installs buf as the log destination under the given render
// format and returns a logger, mirroring setupWithSink but with the format
// chosen per subtest.
func setupUnicodeSink(t *testing.T, format string, buf *bytes.Buffer) {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", format)

	if _, err := SetupTelemetry(WithLogOutput(buf)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
}

// Every renderer must put the host's bytes on the wire unchanged. The
// assertion is on the raw buffer, not on a decoded value: a renderer that
// escaped, transcoded or replaced a rune would still decode back to something
// readable, and the failure this guards against is exactly the byte-level one.
func TestGetLogger_PreservesNonASCIIBytesInEveryFormat(t *testing.T) {
	for _, format := range []string{LogFormatJSON, LogFormatPretty, LogFormatConsole} {
		t.Run(format, func(t *testing.T) {
			var buf bytes.Buffer
			setupUnicodeSink(t, format, &buf)
			GetLogger(context.Background(), "unicode.test").Info(
				_unicodeMessage,
				_unicodeKey, _unicodeValue,
			)

			out := buf.String()
			if !utf8.ValidString(out) {
				t.Fatalf("rendered output is not valid UTF-8: %q", out)
			}
			for _, want := range []string{_unicodeMessage, _unicodeKey, _unicodeValue} {
				if !strings.Contains(out, want) {
					t.Errorf("rendered output %q is missing %q verbatim", out, want)
				}
			}
		})
	}
}

// The JSON renderer additionally has to round-trip: a consumer parses these
// records, so the message and attribute must come back out of the decoder as
// the exact runes that went in, not merely appear somewhere in the bytes.
func TestGetLogger_JSONRoundTripsNonASCIIUnchanged(t *testing.T) {
	var buf bytes.Buffer
	setupUnicodeSink(t, LogFormatJSON, &buf)
	GetLogger(context.Background(), "unicode.test").Info(
		_unicodeMessage,
		_unicodeKey, _unicodeValue,
	)

	line := strings.TrimSpace(buf.String())
	var record map[string]any
	if err := json.Unmarshal([]byte(line), &record); err != nil {
		t.Fatalf("rendered record is not JSON: %v (%q)", err, line)
	}
	if got := record["message"]; got != _unicodeMessage {
		t.Errorf("message decoded as %q, want %q", got, _unicodeMessage)
	}
	if got := record[_unicodeKey]; got != _unicodeValue {
		t.Errorf("attribute %q decoded as %q, want %q", _unicodeKey, got, _unicodeValue)
	}
}
