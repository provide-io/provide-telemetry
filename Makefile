.PHONY: test lint memray memray-flamegraph memray-analyze memray-baseline perf-smoke bench bench-python bench-typescript bench-go

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

perf-smoke: ## Run performance smoke benchmarks
	uv run python scripts/run_performance_smoke.py --iterations 200000 --runs 3

bench: ## Run benchmarks for all languages side-by-side
	./scripts/bench.sh all

bench-python: ## Run Python benchmarks only
	./scripts/bench.sh python

bench-typescript: ## Run TypeScript benchmarks only
	./scripts/bench.sh typescript

bench-go: ## Run Go benchmarks only
	./scripts/bench.sh go

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
