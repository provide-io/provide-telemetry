// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"gopkg.in/yaml.v3"
)

// spec/jcs_number_fixtures.yaml carries one vector per branch of the ECMAScript
// Number::toString algorithm that RFC 8785 defers to. It exists because
// spec/receipt_fixtures.yaml's seven whole receipts are realistic payloads, and
// realistic payloads never reach the exponent thresholds, the
// significand-trimming path, or the zero-padding branch. Two real bugs shipped
// past them: Python rendered 1e21 as "0.1", colliding with 0.1 and 1e22 on one
// receipt digest, and C# rendered 1e-6 as "1e-6" where every other SDK emits
// "0.000001". Mutation testing had already flagged the same hole here — 16
// uncovered mutants in canonicaljson.go, all inside canonicalNumber's five-way
// switch. These vectors turn a regression into a failing test.

type _jcsNumberFixture struct {
	ID        string `yaml:"id"`
	Branch    string `yaml:"branch"`
	Canonical string `yaml:"canonical"`
	InObject  string `yaml:"in_object"`
}

type _jcsNumberFixtureFile struct {
	Version int                 `yaml:"version"`
	Cases   []_jcsNumberFixture `yaml:"cases"`
}

// _jcsNumberCaseCount is the committed vector count. Asserted before iterating
// so a parse that yields nothing fails loudly instead of passing vacuously.
const _jcsNumberCaseCount = 21

// _findSpecFile walks up from the working directory rather than counting
// parents, so the test still finds the contract when a runner copies or
// relocates the package tree.
func _findSpecFile(t *testing.T, name string) string {
	t.Helper()
	directory, err := filepath.Abs(".")
	if err != nil {
		t.Fatalf("resolving the working directory: %v", err)
	}
	for {
		candidate := filepath.Join(directory, "spec", name)
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
		parent := filepath.Dir(directory)
		if parent == directory {
			t.Fatalf("spec/%s not found in any parent of the working directory", name)
		}
		directory = parent
	}
}

func _loadJCSNumberFixtures(t *testing.T) []_jcsNumberFixture {
	t.Helper()
	path := _findSpecFile(t, "jcs_number_fixtures.yaml")
	raw, err := os.ReadFile(path) //nolint:gosec // in-repo fixture located by walking up from the package
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	var file _jcsNumberFixtureFile
	if err := yaml.Unmarshal(raw, &file); err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	if len(file.Cases) < _jcsNumberCaseCount {
		t.Fatalf("%s declared %d cases, want at least %d", path, len(file.Cases), _jcsNumberCaseCount)
	}
	return file.Cases
}

// _jcsNumberValue recovers the float64 a JavaScript producer would have
// canonicalized. The literal is decoded through json.Number and converted with
// Float64 rather than being read into an untyped any: JavaScript has one number
// type, so the fixture spells 1e20 and 1e21 without a decimal point exactly as
// JSON.stringify renders them, and a decoder that handed those back as an
// integer would take CanonicalJSON's int64 branch and skip canonicalNumber
// entirely — the code path these vectors exist to pin.
func _jcsNumberValue(t *testing.T, tc _jcsNumberFixture) float64 {
	t.Helper()
	var wrapper struct {
		V json.Number `json:"v"`
	}
	if err := json.Unmarshal([]byte(tc.InObject), &wrapper); err != nil {
		t.Fatalf("%s: parsing %s: %v", tc.ID, tc.InObject, err)
	}
	value, err := wrapper.V.Float64()
	if err != nil {
		t.Fatalf("%s: %s is not a float64: %v", tc.ID, wrapper.V, err)
	}
	return value
}

// TestJCSNumberFixturesCanonical pins the rendering of each number on its own.
func TestJCSNumberFixturesCanonical(t *testing.T) {
	for _, tc := range _loadJCSNumberFixtures(t) {
		t.Run(tc.ID, func(t *testing.T) {
			if got := CanonicalJSON(_jcsNumberValue(t, tc)); got != tc.Canonical {
				t.Errorf("%s (%s):\n got: %s\nwant: %s", tc.ID, tc.Branch, got, tc.Canonical)
			}
		})
	}
}

// TestJCSNumberFixturesInObject pins the same numbers inside {"v": ...}. A
// serializer can format correctly in isolation and still lose the value in
// context, which is why both forms are committed.
func TestJCSNumberFixturesInObject(t *testing.T) {
	for _, tc := range _loadJCSNumberFixtures(t) {
		t.Run(tc.ID, func(t *testing.T) {
			object := map[string]any{"v": _jcsNumberValue(t, tc)}
			if got := CanonicalJSON(object); got != tc.InObject {
				t.Errorf("%s (%s):\n got: %s\nwant: %s", tc.ID, tc.Branch, got, tc.InObject)
			}
		})
	}
}
