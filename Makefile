.PHONY: test lint security memray memray-flamegraph memray-analyze memray-baseline perf-smoke perf perf-python perf-typescript perf-go perf-rust perf-baseline-python perf-baseline-typescript perf-baseline-go perf-baseline-rust bench bench-python bench-typescript bench-go stress stress-typescript stress-go

MEMRAY_OUTPUT_DIR ?= memray-output

test: ## Run core test suite (100% coverage enforced)
	uv run python scripts/run_pytest_gate.py

lint: ## Run all linters and type checkers
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy src tests
	uv run bandit -r src -ll
	uv run codespell
	uv run python scripts/check_spdx_headers.py
	uv run python scripts/check_max_loc.py --max-lines 500

security: ## Run project-targeted security scans
	uv run bandit -r src -ll
	uv run python -m pip_audit --path .

memray: ## Run all memray stress tests
	uv run python scripts/memray/run_memray_stress.py

memray-flamegraph: ## Generate HTML flamegraphs from memray binaries
	@for f in $(MEMRAY_OUTPUT_DIR)/memray_*.bin; do \
		[ -f "$$f" ] || continue; \
		echo "Generating flamegraph for $$(basename $$f)..."; \
		uv run memray flamegraph "$$f" -o "$${f%.bin}_flamegraph.html" --force 2>/dev/null || true; \
	done
	@echo "Flamegraphs written to $(MEMRAY_OUTPUT_DIR)/"

memray-analyze: ## Run tracemalloc audit for Python-level allocations
	uv run python scripts/memray/tracemalloc_audit.py

memray-baseline: ## Update memray regression baselines
	MEMRAY_UPDATE_BASELINE=1 uv run pytest tests/memray/ -m memray -v --no-cov -p no:provide_telemetry

perf-smoke: ## Run Python performance smoke benchmarks (legacy report-only path; prefer `make perf-python`)
	uv run python scripts/run_performance_smoke.py --iterations 200000 --runs 3

# ── Perf-budget gate ─────────────────────────────────────────────────────────
# Each `perf-<lang>` target runs that language's hot-path benchmarks and pipes
# the output through scripts/perf_check.py, which compares the measurements
# against baselines/perf-<lang>.json for the host's OS bucket. Fails with exit
# code 1 if any operation exceeds its budget (baseline_ns * tolerance_multiplier).
# `perf` runs all four sequentially. `perf-baseline-<lang>` prints fresh
# measurements WITHOUT comparison — copy the JSON into the baseline file by
# hand to seed or refresh a bucket.

perf: perf-python perf-typescript perf-go perf-rust ## Run perf-budget gate for all four languages

perf-python: ## Run perf-budget gate for Python only
	uv run python scripts/run_performance_smoke.py --iterations 300000 --runs 5 --emit-json | uv run python scripts/perf_check.py --lang python

perf-typescript: ## Run perf-budget gate for TypeScript only
	cd typescript && npx tsx scripts/perf-smoke.ts --emit-json | uv run --project .. python ../scripts/perf_check.py --lang typescript

perf-go: ## Run perf-budget gate for Go only
	cd go && go test -bench=. -benchtime=100ms -run=^$$ . | uv run --project .. python ../scripts/parse_go_bench.py | uv run --project .. python ../scripts/perf_check.py --lang go

perf-rust: ## Run perf-budget gate for Rust only
	cd rust && cargo bench --bench hot_path -- --quick | uv run --project .. python ../scripts/parse_criterion.py | uv run --project .. python ../scripts/perf_check.py --lang rust

perf-baseline-python: ## Print fresh Python perf measurements (paste into baselines/perf-python.json)
	uv run python scripts/run_performance_smoke.py --iterations 300000 --runs 5 --emit-json

perf-baseline-typescript: ## Print fresh TypeScript perf measurements (paste into baselines/perf-typescript.json)
	cd typescript && npx tsx scripts/perf-smoke.ts --emit-json

perf-baseline-go: ## Print fresh Go perf measurements (paste into baselines/perf-go.json)
	cd go && go test -bench=. -benchtime=100ms -run=^$$ . | uv run --project .. python ../scripts/parse_go_bench.py

perf-baseline-rust: ## Print fresh Rust perf measurements (paste into baselines/perf-rust.json)
	cd rust && cargo bench --bench hot_path -- --quick | uv run --project .. python ../scripts/parse_criterion.py

bench: ## Run benchmarks for all languages side-by-side
	./scripts/bench.sh all

bench-python: ## Run Python benchmarks only
	./scripts/bench.sh python

bench-typescript: ## Run TypeScript benchmarks only
	./scripts/bench.sh typescript

bench-go: ## Run Go benchmarks only
	./scripts/bench.sh go

stress: ## Run stress tests for TypeScript and Go
	cd typescript && npm run stress
	cd go && make stress

stress-typescript: ## Run TypeScript stress tests only
	cd typescript && npm run stress

stress-go: ## Run Go stress tests only
	cd go && make stress

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
