// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — data classification engine (strippable governance module).
// If this file is deleted, the PII engine runs unchanged (hook stays nil).
package telemetry

import (
	"path/filepath"
	"sync"
)

// DataClass represents a data classification label.
type DataClass string

// DataClass constants mirror Python's DataClass enum.
const (
	DataClassPublic   DataClass = "PUBLIC"
	DataClassInternal DataClass = "INTERNAL"
	DataClassPII      DataClass = "PII"
	DataClassPHI      DataClass = "PHI"
	DataClassPCI      DataClass = "PCI"
	DataClassSecret   DataClass = "SECRET"
)

// ClassificationRule maps a glob pattern to a DataClass.
type ClassificationRule struct {
	Pattern        string
	Classification DataClass
}

// ClassificationPolicy defines the action to take per DataClass.
type ClassificationPolicy struct {
	Public   string
	Internal string
	PII      string
	PHI      string
	PCI      string
	Secret   string
}

// defaultClassificationPolicy returns a policy with sensible defaults.
func defaultClassificationPolicy() ClassificationPolicy {
	return ClassificationPolicy{
		Public:   "pass",
		Internal: "pass",
		PII:      "redact",
		PHI:      "drop",
		PCI:      "hash",
		Secret:   "drop",
	}
}

var (
	_classificationMu     sync.RWMutex
	_classificationRules  []ClassificationRule
	_classificationPolicy = defaultClassificationPolicy()
)

// RegisterClassificationRules adds rules and installs the classification hook on the PII engine.
func RegisterClassificationRules(rules []ClassificationRule) {
	_classificationMu.Lock()
	_classificationRules = append(_classificationRules, rules...)
	_classificationMu.Unlock()
	SetClassificationHook(_classifyField)
}

// SetClassificationPolicy updates the active classification policy.
func SetClassificationPolicy(p ClassificationPolicy) {
	_classificationMu.Lock()
	_classificationPolicy = p
	_classificationMu.Unlock()
}

// GetClassificationPolicy returns the current classification policy.
func GetClassificationPolicy() ClassificationPolicy {
	_classificationMu.RLock()
	defer _classificationMu.RUnlock()
	return _classificationPolicy
}

// _classifyField returns the DataClass string for key when a rule matches, or "" when none match.
func _classifyField(key string, _ any) string {
	_classificationMu.RLock()
	defer _classificationMu.RUnlock()
	for _, rule := range _classificationRules {
		matched, err := filepath.Match(rule.Pattern, key)
		if err == nil && matched {
			return string(rule.Classification)
		}
	}
	return ""
}

// ResetClassificationForTests resets all classification state and removes the hook.
func ResetClassificationForTests() {
	_classificationMu.Lock()
	_classificationRules = nil
	_classificationPolicy = defaultClassificationPolicy()
	_classificationMu.Unlock()
	SetClassificationHook(nil)
}
