// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "log/slog"

// Keeping attribute order and duplicate keys across the PII pass.
//
// The rule engine is map-shaped, and that shape is the cross-language contract:
// SanitizePayload(map[string]any, ...) is what the behavioural fixtures pin, in
// all five SDKs. A Go map cannot represent two things slog guarantees, so a
// straight round trip lost both on every record.
//
// Duplicate keys collapsed. slog permits them and leaves rendering to the
// handler, so `logger.Info("m", slog.String("k", "a"), slog.String("k", "b"))`
// is legitimate — and keying a map by name means the last write wins and "a" is
// gone, silently. Anything accumulating repeated fields in a loop lost all but
// the final one.
//
// Order was randomized. Go deliberately randomizes map iteration, so ranging
// the sanitized map to rebuild the record reshuffled every line. Irrelevant to
// a JSON consumer, visible churn for the console and text renderers, for anyone
// diffing log files, and for golden-output tests.
//
// The fix changes how the handler *applies* the engine, not the engine. The
// record's attributes are kept as an ordered slice; the map is only ever an
// argument. What makes that work is that piicore.SanitizeMap judges every entry
// on its own key, path and value — no rule consults a sibling — so splitting one
// map into several changes no decision the engine makes.

// _cleanedRecordAttrs snapshots a record's attributes in order, under the keys
// hardening will give them.
//
// Hardening does not only bound values: it cleans control characters out of
// keys, because the pretty renderer emits them bare and a key carrying a
// newline forged a second log line. So the map the engine returns is keyed by
// the *cleaned* name, and a rebuild that looked attributes up by the name the
// caller wrote would find nothing and drop them — silently, and only for the
// records that most need to survive.
//
// Cleaning here means both sides agree. Two keys differing only by control
// characters collapse to one name, which makes them duplicates, which the
// rounds below already handle.
func _cleanedRecordAttrs(r slog.Record) []slog.Attr {
	attrs := _recordAttrs(r)
	for i := range attrs {
		attrs[i].Key = _cleanKey(attrs[i].Key)
	}
	return attrs
}

// _recordAttrs snapshots a record's attributes in order.
func _recordAttrs(r slog.Record) []slog.Attr {
	attrs := make([]slog.Attr, 0, r.NumAttrs())
	r.Attrs(func(a slog.Attr) bool {
		attrs = append(attrs, a)
		return true
	})
	return attrs
}

// _occurrences numbers each attribute by how many times its key has already
// appeared: 0 for the first `k`, 1 for the second, and so on.
//
// That number is the round an attribute is sanitized in. Every round holds each
// key at most once, which is what lets a map carry it.
func _occurrences(attrs []slog.Attr) []int {
	seen := make(map[string]int, len(attrs))
	rounds := make([]int, len(attrs))
	for i, a := range attrs {
		rounds[i] = seen[a.Key]
		seen[a.Key]++
	}
	return rounds
}

// _roundCount is one more than the highest round number, i.e. the multiplicity
// of the most-repeated key. One for the overwhelmingly common case.
func _roundCount(rounds []int) int {
	highest := 0
	for _, round := range rounds {
		if round > highest {
			highest = round
		}
	}
	return highest + 1
}

// _roundPayload builds the map for one round: the attributes whose occurrence
// number matches it, keyed as the caller wrote them.
func _roundPayload(attrs []slog.Attr, rounds []int, round int) map[string]any {
	payload := make(map[string]any, len(attrs))
	for i, a := range attrs {
		if rounds[i] == round {
			payload[a.Key] = _attrValue(a.Value)
		}
	}
	return payload
}

// _attrFromValue rebuilds one attribute, restoring a nested map as the group it
// came from so the rendered shape matches what the caller logged.
func _attrFromValue(key string, value any) slog.Attr {
	if nested, ok := value.(map[string]any); ok {
		return slog.Attr{Key: key, Value: slog.GroupValue(_mapToAttrs(nested)...)}
	}
	return slog.Any(key, value)
}

// _rebuildInOrder walks the original attributes and takes each one's sanitized
// value from the round it belongs to.
//
// An attribute the engine dropped — a rule with a drop action, or a hardening
// cap — is absent from its round's map and is skipped here, which is how a
// dropped attribute stays dropped rather than reappearing unsanitized.
func _rebuildInOrder(attrs []slog.Attr, rounds []int, sanitized []map[string]any) []slog.Attr {
	out := make([]slog.Attr, 0, len(attrs))
	for i, a := range attrs {
		value, kept := sanitized[rounds[i]][a.Key]
		if !kept {
			continue
		}
		out = append(out, _attrFromValue(a.Key, value))
	}
	return out
}
