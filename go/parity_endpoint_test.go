// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_endpoint_test.go validates Go behavioral parity for endpoint URL
// validation against spec/behavioral_fixtures.yaml: valid endpoints (HTTP/HTTPS
// with various port/path combinations, IPv6) and invalid endpoints (empty string,
// missing scheme, wrong scheme, no host, bad/negative/zero ports).

package telemetry

import (
	"os"
	"testing"

	"gopkg.in/yaml.v3"
)

func TestEndpointValidationParity(t *testing.T) {
	type fixture struct {
		Endpoint    string `yaml:"endpoint"`
		Description string `yaml:"description"`
	}
	type fixtures struct {
		EndpointValidation struct {
			Valid   []fixture `yaml:"valid"`
			Invalid []fixture `yaml:"invalid"`
		} `yaml:"endpoint_validation"`
	}

	data, err := os.ReadFile("../spec/behavioral_fixtures.yaml")
	if err != nil {
		t.Fatalf("failed to read fixtures: %v", err)
	}
	var f fixtures
	if err := yaml.Unmarshal(data, &f); err != nil {
		t.Fatalf("failed to parse fixtures: %v", err)
	}

	for _, tc := range f.EndpointValidation.Valid {
		tc := tc
		t.Run("valid/"+tc.Description, func(t *testing.T) {
			_, err := _validatedSignalEndpointURL(tc.Endpoint, "/v1/traces")
			if err != nil {
				t.Errorf("expected valid endpoint %q to be accepted, got: %v", tc.Endpoint, err)
			}
		})
	}
	for _, tc := range f.EndpointValidation.Invalid {
		tc := tc
		t.Run("invalid/"+tc.Description, func(t *testing.T) {
			_, err := _validatedSignalEndpointURL(tc.Endpoint, "/v1/traces")
			if err == nil {
				t.Errorf("expected invalid endpoint %q to be rejected", tc.Endpoint)
			}
		})
	}
}
