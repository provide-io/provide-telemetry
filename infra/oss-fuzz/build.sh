#!/bin/bash -eu
# Copy to google/oss-fuzz/projects/provide-telemetry/build.sh
#
# Builds native Go fuzz targets from go/fuzz_test.go as libFuzzer binaries
# for ClusterFuzz / OSS-Fuzz.

go install github.com/AdamKorcz/go-118-fuzz-build@latest
go get github.com/AdamKorcz/go-118-fuzz-build/testing

cd "$SRC/provide-telemetry/go"

# Package path + Fuzz function name + output fuzzer binary name
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzParseOTLPHeaders FuzzParseOTLPHeaders
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzMaskEndpointURL FuzzMaskEndpointURL
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzValidateRate FuzzValidateRate
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzValidatedSignalEndpointURL FuzzValidatedSignalEndpointURL
compile_native_go_fuzzer github.com/provide-io/provide-telemetry/go FuzzParseEnvFloatThenValidateRate FuzzParseEnvFloatThenValidateRate
