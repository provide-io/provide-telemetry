.PHONY: help lint vet test coverage mutation security fmt fmt-check bench stress fuzz check

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

lint: ## Run golangci-lint
	golangci-lint run ./...

vet: ## Run go vet
	go vet ./...

test: ## Run tests with race detector
	go test -race -count=1 ./...

coverage: ## Run tests and enforce 100% coverage
	go test -race -coverprofile=coverage.out -covermode=atomic .
	@TOTAL=$$(go tool cover -func=coverage.out | grep total | awk '{print $$3}'); \
	echo "Total coverage: $$TOTAL"; \
	if [ "$$TOTAL" != "100.0%" ]; then \
		echo "FAIL: coverage is $$TOTAL, expected 100.0%"; \
		exit 1; \
	fi

mutation: ## Run gremlins mutation testing
	gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 --coverpkg="github.com/provide-io/provide-telemetry/go" --exclude-files="sampling_cmp.go" --exclude-files="resilience_cmp.go" --exclude-files="cmd/e2e_cross_language_client/" --exclude-files="examples/" --exclude-files="internal/" --exclude-files="logger/" --exclude-files="otel/" --exclude-files="scripts/stress/" --exclude-files="tracer/" .
	gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 ./logger
	gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 ./tracer
	cd otel && gremlins unleash --workers=1 --test-cpu=1 --timeout-coefficient=30 --threshold-efficacy=100 --exclude-files="examples/" .

security: ## Run gosec and govulncheck
	gosec ./...
	govulncheck ./...

fmt: ## Format source files
	goimports -w .
	gofmt -w .

fmt-check: ## Check formatting (fail if any files need formatting)
	goimports -l . | diff /dev/null -

bench: ## Run benchmarks
	go test -bench=. -benchmem -count=1 ./...

stress: ## Run stress tests
	go run ./scripts/stress

# Coverage-guided fuzz of config parsing / redaction (OSS-Fuzz-class local run).
# Override duration: make fuzz FUZZTIME=5m
FUZZTIME ?= 30s
fuzz: ## Run config/endpoint/header fuzz targets
	go test . -run='^$$' -fuzz='^FuzzParseOTLPHeaders$$' -fuzztime=$(FUZZTIME)
	go test . -run='^$$' -fuzz='^FuzzMaskEndpointURL$$' -fuzztime=$(FUZZTIME)
	go test . -run='^$$' -fuzz='^FuzzValidateRate$$' -fuzztime=$(FUZZTIME)
	go test . -run='^$$' -fuzz='^FuzzValidatedSignalEndpointURL$$' -fuzztime=$(FUZZTIME)
	go test . -run='^$$' -fuzz='^FuzzParseEnvFloatThenValidateRate$$' -fuzztime=$(FUZZTIME)

check: fmt-check vet lint security test coverage ## Run all quality gates

# Local OSS-Fuzz (Docker libFuzzer build). Not Google cloud onboarding.
# From repo root: make -C go oss-fuzz-local  OR  ../scripts/oss-fuzz-local.sh build
oss-fuzz-local: ## Build libFuzzer binaries via local OSS-Fuzz helper
	cd .. && ./scripts/oss-fuzz-local.sh build
