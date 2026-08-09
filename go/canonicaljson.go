// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — RFC 8785 (JCS) canonical JSON.
//
// JCS was specified against ECMAScript, which is why TypeScript gets most of it
// for free: JSON.stringify already emits the required string escaping, and
// JavaScript's Number-to-string is the binary64 rendering JCS mandates. Go has
// no such luck. Key ordering by UTF-16 code unit, the escape set, and the
// ECMAScript number grammar are all reimplemented here.
//
// The point of doing it at all is that a receipt hashes what a value *was*, not
// how it printed. Hashing fmt.Sprintf("%v", value) collides across types: the
// number 1 and the string "1" produce the same digest, so a receipt cannot
// distinguish them. spec/receipt_fixtures.yaml pins the output, and its vectors
// were produced by independent implementations, so agreeing with them means
// agreeing with the other SDKs rather than with ourselves.
package telemetry

import (
	"math"
	"slices"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

// nullLiteral is the JSON spelling for both a nil value and a non-finite
// number. Named rather than repeated because goconst counts every occurrence
// in the package, tests included, and a bare literal here trips it.
const nullLiteral = "null"

// CanonicalJSON returns the RFC 8785 canonical JSON serialization of value.
//
// Values JSON cannot encode are normalized rather than rejected: NaN and
// ±Infinity become null, and anything without a JSON shape at all becomes the
// redaction sentinel. Canonicalization runs inside the redaction hook, so
// returning an error here would turn a log call into a failure.
func CanonicalJSON(value any) string {
	return string(appendCanonical(make([]byte, 0, 64), value))
}

func appendCanonical(dst []byte, value any) []byte {
	switch typed := value.(type) {
	case nil:
		return append(dst, nullLiteral...)
	case bool:
		return strconv.AppendBool(dst, typed)
	case string:
		return appendCanonicalString(dst, typed)
	case int64:
		return strconv.AppendInt(dst, typed, 10)
	case uint64:
		return strconv.AppendUint(dst, typed, 10)
	case float64:
		return append(dst, canonicalNumber(typed)...)
	case map[string]any:
		return appendCanonicalObject(dst, typed)
	case []any:
		return appendCanonicalArray(dst, typed)
	default:
		// Hardening reduces any Go value to exactly the cases above, so this
		// recurses at most once. It runs unlimited: a digest must not depend on
		// how long or how wide the value was, only on what it contained.
		return appendCanonical(dst, Harden(value, _unlimited()))
	}
}

func appendCanonicalObject(dst []byte, obj map[string]any) []byte {
	keys := make([]string, 0, len(obj))
	for key := range obj {
		keys = append(keys, key)
	}
	// JCS orders members by UTF-16 code unit, which is not Go's byte order:
	// an astral character encodes to a surrogate pair starting at 0xD800 and
	// therefore sorts *below* U+E000..U+FFFF, where UTF-8 puts it above.
	slices.SortFunc(keys, compareUTF16)
	dst = append(dst, '{')
	for i, key := range keys {
		if i > 0 {
			dst = append(dst, ',')
		}
		dst = appendCanonicalString(dst, key)
		dst = append(dst, ':')
		dst = appendCanonical(dst, obj[key])
	}
	return append(dst, '}')
}

func appendCanonicalArray(dst []byte, items []any) []byte {
	dst = append(dst, '[')
	for i, item := range items {
		if i > 0 {
			dst = append(dst, ',')
		}
		dst = appendCanonical(dst, item)
	}
	return append(dst, ']')
}

// compareUTF16 orders two strings by their UTF-16 code units, the ordering
// RFC 8785 specifies for object members.
func compareUTF16(a, b string) int {
	return slices.Compare(utf16.Encode([]rune(a)), utf16.Encode([]rune(b)))
}

// appendCanonicalString writes a JSON string literal using JCS's escape set:
// the seven two-character escapes, \u00xx for the remaining C0 controls, and
// nothing else. Non-ASCII is emitted literally — JCS forbids \u escaping it.
func appendCanonicalString(dst []byte, s string) []byte {
	dst = append(dst, '"')
	for _, r := range s {
		switch r {
		case '"':
			dst = append(dst, '\\', '"')
		case '\\':
			dst = append(dst, '\\', '\\')
		case '\b':
			dst = append(dst, '\\', 'b')
		case '\f':
			dst = append(dst, '\\', 'f')
		case '\n':
			dst = append(dst, '\\', 'n')
		case '\r':
			dst = append(dst, '\\', 'r')
		case '\t':
			dst = append(dst, '\\', 't')
		default:
			if r < 0x20 {
				dst = append(dst, `\u00`...)
				const hexDigits = "0123456789abcdef"
				dst = append(dst, hexDigits[r>>4], hexDigits[r&0xf])
				continue
			}
			dst = utf8.AppendRune(dst, r)
		}
	}
	return append(dst, '"')
}

// canonicalNumber renders f the way ECMAScript's Number::toString does, which
// is what RFC 8785 requires of a JSON number.
//
// Two behaviors this pins that Go's own formatters do not: -0 prints as "0"
// (strconv gives "-0"), and the exponential/positional switchover happens at
// 10^21 and 10^-7 rather than wherever %g decides. The negative_zero_collapses
// and non_finite_normalization vectors exist for exactly these.
func canonicalNumber(f float64) string {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		// Neither has a JSON encoding; null is the spelling the contract fixes
		// so no SDK has to invent one.
		return nullLiteral
	}
	if f == 0 {
		return "0"
	}
	sign := ""
	if f < 0 {
		sign, f = "-", -f
	}

	// ECMAScript defines the output in terms of integers k, n and s with
	// 10^(k-1) <= s < 10^k and s * 10^(n-k) = f, k minimal. Go's shortest
	// round-trip exponential form yields exactly that s (the digits) and n.
	mantissa, exponent, _ := strings.Cut(strconv.FormatFloat(f, 'e', -1, 64), "e")
	exp, _ := strconv.Atoi(exponent) //nolint:errcheck // FormatFloat 'e' always emits a parsable exponent
	digits := strings.Replace(mantissa, ".", "", 1)

	return sign + canonicalDigits(digits, exp+1)
}

// canonicalDigits places the decimal point in digits for decimal exponent n,
// where the value is 0.digits x 10^n. Split out from canonicalNumber only to
// keep each function under the cyclomatic bound; the five branches are the
// five ECMAScript cases and belong together.
//
// An if/else chain rather than an expressionless switch, and the difference is
// not style. Go's coverage tool instruments case *bodies* only: for a switch,
// the emitted blocks start after each `case ...:`, so the condition expressions
// themselves sit outside every block. gremlins then reports every mutant of
// these bounds as "not covered" even though the vectors in
// spec/jcs_number_fixtures.yaml drive all five branches and the function
// reports 100% coverage. An if/else chain puts the conditions inside
// instrumented blocks, so the bounds are mutation-tested for real — which
// matters here, because a wrong bound in this exact algorithm is what made
// Python render 1e21 as "0.1".
func canonicalDigits(digits string, n int) string {
	k := len(digits)
	if k <= n && n <= 21 {
		return digits + strings.Repeat("0", n-k)
	}
	if 0 < n && n <= 21 {
		return digits[:n] + "." + digits[n:]
	}
	// ECMAScript spells this bound "-6 < n <= 0" and both halves are load
	// bearing: the branches above consume only n <= 21, so n = 22 falls
	// through to here, and without "n <= 0" it would render 1e21 as "0.1".
	if -6 < n && n <= 0 {
		return "0." + strings.Repeat("0", -n) + digits
	}
	if k == 1 {
		return digits + "e" + canonicalExponent(n-1)
	}
	return digits[:1] + "." + digits[1:] + "e" + canonicalExponent(n-1)
}

// canonicalExponent renders an exponent with the explicit '+' ECMAScript emits
// for non-negative values; strconv already supplies the '-'.
func canonicalExponent(e int) string {
	if e >= 0 {
		return "+" + strconv.Itoa(e)
	}
	return strconv.Itoa(e)
}
