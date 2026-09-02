// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"
)

// orderedLogger installs a JSON logger writing to buf.
func orderedLogger(t *testing.T, buf *bytes.Buffer) *slog.Logger {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	t.Setenv("PROVIDE_LOG_INCLUDE_CALLER", "false")
	if _, err := SetupTelemetry(WithLogOutput(buf)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	return GetLogger(context.Background(), "order.test")
}

// emittedKeys returns the record's keys in the order the renderer wrote them.
//
// encoding/json unmarshals into a map, losing exactly the property under test,
// so the raw line is scanned instead.
func emittedKeys(t *testing.T, line string) []string {
	t.Helper()
	decoder := json.NewDecoder(strings.NewReader(strings.TrimSpace(line)))
	token, err := decoder.Token()
	if err != nil {
		t.Fatalf("reading the record: %v", err)
	}
	if delim, ok := token.(json.Delim); !ok || delim != '{' {
		t.Fatalf("record does not start with an object: %v", token)
	}

	keys := []string{}
	for decoder.More() {
		key, err := decoder.Token()
		if err != nil {
			t.Fatalf("reading a key: %v", err)
		}
		name, ok := key.(string)
		if !ok {
			t.Fatalf("key is not a string: %v", key)
		}
		keys = append(keys, name)
		var value any
		if err := decoder.Decode(&value); err != nil {
			t.Fatalf("reading the value for %q: %v", name, err)
		}
	}
	return keys
}

// The order a caller logged attributes in is the order they are emitted in.
//
// The PII pass converts the record to a map and back, and Go deliberately
// randomizes map iteration — so ranging it to rebuild reshuffled every line.
// Six emissions of one identical call used to produce six orders.
func TestPIIOrder_AttributeOrderIsStableAcrossEmissions(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	for range 6 {
		logger.Info("order.ok", "a", 1, "b", 2, "c", 3, "d", 4, "e", 5)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 6 {
		t.Fatalf("expected 6 records, got %d", len(lines))
	}
	first := emittedKeys(t, lines[0])
	for i, line := range lines[1:] {
		got := emittedKeys(t, line)
		if strings.Join(got, ",") != strings.Join(first, ",") {
			t.Fatalf("record %d ordered its keys differently:\n first: %v\n   got: %v", i+2, first, got)
		}
	}
}

// And that order is the caller's, not merely a stable one.
func TestPIIOrder_TheOrderIsTheOneTheCallerWrote(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	logger.Info("order.caller", "zeta", 1, "alpha", 2, "mu", 3)

	keys := emittedKeys(t, buf.String())
	var caller []string
	for _, k := range keys {
		switch k {
		case "zeta", "alpha", "mu":
			caller = append(caller, k)
		}
	}
	want := []string{"zeta", "alpha", "mu"}
	if strings.Join(caller, ",") != strings.Join(want, ",") {
		t.Errorf("caller attributes came out as %v, want %v — sorted or shuffled, not preserved", caller, want)
	}
}

// A duplicate key keeps both values.
//
// slog permits duplicates and leaves rendering to the handler. Keying a map by
// name meant the last write won and the earlier value was gone, with nothing
// reporting it — which cost every caller appending a field in a loop.
func TestPIIOrder_DuplicateKeysBothSurvive(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	logger.Info("order.dup", slog.String("k", "a"), slog.String("k", "b"))

	line := strings.TrimSpace(buf.String())
	if strings.Count(line, `"k"`) != 2 {
		t.Errorf(`expected "k" twice in %s`, line)
	}
	for _, want := range []string{`"a"`, `"b"`} {
		if !strings.Contains(line, want) {
			t.Errorf("value %s was dropped from %s", want, line)
		}
	}
	keys := emittedKeys(t, line)
	var seen []string
	for _, k := range keys {
		if k == "k" {
			seen = append(seen, k)
		}
	}
	if len(seen) != 2 {
		t.Errorf("the record carries %d 'k' attributes, want 2", len(seen))
	}
}

// Both occurrences are sanitized, each under its own key.
//
// The round split exists so a duplicate is judged by the rule engine rather
// than smuggled past it: an earlier occurrence that skipped sanitization would
// be a redaction bypass, which is worse than the data loss it replaced.
func TestPIIOrder_EveryOccurrenceOfADuplicateIsSanitized(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	logger.Info("order.dup.pii",
		slog.String("password", "first-secret"),
		slog.String("password", "second-secret"),
	)

	line := buf.String()
	for _, leaked := range []string{"first-secret", "second-secret"} {
		if strings.Contains(line, leaked) {
			t.Errorf("%q survived redaction in %s", leaked, line)
		}
	}
	if strings.Count(line, Redacted) != 2 {
		t.Errorf("expected both occurrences redacted in %s", line)
	}
}

// Three of a kind: the rounds are not hard-coded to two.
func TestPIIOrder_MoreThanTwoOccurrencesAreKept(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	logger.Info("order.triple", slog.Int("n", 1), slog.Int("n", 2), slog.Int("n", 3))

	line := strings.TrimSpace(buf.String())
	if strings.Count(line, `"n"`) != 3 {
		t.Errorf(`expected "n" three times in %s`, line)
	}
	for _, want := range []string{":1", ":2", ":3"} {
		if !strings.Contains(line, want) {
			t.Errorf("value %s was dropped from %s", want, line)
		}
	}
}

// A record with no duplicates takes exactly one round, so the common case pays
// for none of this.
func TestPIIOrder_TheCommonCaseIsASingleRound(t *testing.T) {
	attrs := []slog.Attr{slog.Int("a", 1), slog.Int("b", 2), slog.Int("c", 3)}
	if got := _roundCount(_occurrences(attrs)); got != 1 {
		t.Errorf("a record with distinct keys took %d rounds, want 1", got)
	}
}

func TestPIIOrder_RoundsCountTheDeepestRepetition(t *testing.T) {
	attrs := []slog.Attr{
		slog.Int("a", 1), slog.Int("b", 1), slog.Int("a", 2), slog.Int("a", 3), slog.Int("b", 2),
	}
	rounds := _occurrences(attrs)
	if got := []int{rounds[0], rounds[1], rounds[2], rounds[3], rounds[4]}; got[0] != 0 ||
		got[1] != 0 || got[2] != 1 || got[3] != 2 || got[4] != 1 {
		t.Errorf("occurrence numbers are %v, want [0 0 1 2 1]", got)
	}
	if got := _roundCount(rounds); got != 3 {
		t.Errorf("round count is %d, want 3 — the multiplicity of the most repeated key", got)
	}
}

func TestPIIOrder_NoAttributesTakesOneRound(t *testing.T) {
	if got := _roundCount(_occurrences(nil)); got != 1 {
		t.Errorf("an empty record took %d rounds, want 1", got)
	}
}

// A key carrying control characters is cleaned before the round split, so the
// rebuild finds it under the name the engine returned.
//
// Hardening cleans keys because the pretty renderer emits them bare and a
// newline in one forged a second log line. A rebuild keyed on the caller's
// original spelling found nothing and dropped the attribute — silently, and
// only for the records that most need to survive.
func TestPIIOrder_AKeyWithControlCharactersSurvivesTheRoundSplit(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	logger.Info("order.forged", "x\nforged [error] payment.failed", "1")

	line := strings.TrimSpace(buf.String())
	if !strings.Contains(line, "xforged [error] payment.failed") {
		t.Errorf("the cleaned key is missing from %s", line)
	}
	if strings.Count(line, "\n") != 0 {
		t.Errorf("the record spans more than one line: %q", line)
	}
}

// Groups keep their nesting through the round split.
func TestPIIOrder_GroupsSurviveAsGroups(t *testing.T) {
	var buf bytes.Buffer
	logger := orderedLogger(t, &buf)

	logger.Info("order.group", slog.Group("outer", slog.String("inner", "value")))

	var record map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf.String())), &record); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	outer, ok := record["outer"].(map[string]any)
	if !ok {
		t.Fatalf("outer is not a group: %#v", record["outer"])
	}
	if outer["inner"] != "value" {
		t.Errorf("inner is %#v, want \"value\"", outer["inner"])
	}
}

// An attribute the engine drops stays dropped, rather than reappearing from the
// ordered list unsanitized.
func TestPIIOrder_ADroppedAttributeIsNotResurrected(t *testing.T) {
	attrs := []slog.Attr{slog.Int("kept", 1), slog.Int("dropped", 2)}
	rounds := _occurrences(attrs)
	sanitized := []map[string]any{{"kept": 1}}

	got := _rebuildInOrder(attrs, rounds, sanitized)
	if len(got) != 1 || got[0].Key != "kept" {
		t.Errorf("rebuild produced %v, want only the kept attribute", got)
	}
}
