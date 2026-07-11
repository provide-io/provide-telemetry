#!/bin/bash -eu
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################
#
# Native Go 1.18+ fuzz targets from go/fuzz_test.go for local OSS-Fuzz helper
# builds (and ClusterFuzz if ever onboarded). Not submitted to google/oss-fuzz
# cloud until explicitly revived.

cd "$SRC/provide-telemetry/go"

# go-118-fuzz-build fails without this when the source tree is not a full git checkout
# (local helper mounts / incomplete .git).
export GOFLAGS="${GOFLAGS:-} -buildvcs=false"
export GOWORK=off
go env -w GOFLAGS=-buildvcs=false

# Register blank import required by go-118-fuzz-build instrumentation.
printf 'package telemetry\n\nimport _ "github.com/AdamKorcz/go-118-fuzz-build/testing"\n' > ossfuzz_register.go
go get github.com/AdamKorcz/go-118-fuzz-build/testing
go mod tidy

# Isolate fuzz_test.go: go-118-fuzz-build walks package test files and can choke
# on large unrelated *_test.go sets. Stash them for the duration of the build.
mkdir -p /tmp/ossfuzz-tests-stash
shopt -s nullglob
for f in *_test.go; do
  if [[ "$f" != "fuzz_test.go" ]]; then
    mv "$f" /tmp/ossfuzz-tests-stash/
  fi
done
shopt -u nullglob

# Args: package path, Fuzz* function name, output binary name under $OUT
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzParseOTLPHeaders FuzzParseOTLPHeaders
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzMaskEndpointURL FuzzMaskEndpointURL
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzValidateRate FuzzValidateRate
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzValidatedSignalEndpointURL FuzzValidatedSignalEndpointURL
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzParseEnvFloatThenValidateRate FuzzParseEnvFloatThenValidateRate
