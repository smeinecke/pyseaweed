# Makefile

.PHONY: all format reformat-ruff check fix-ruff fix test test-cov test-integration test-all weed-up weed-down test-integration-local vulture complexity xenon bandit pyright docs validate

# Default target: runs format and check
all: validate test

# Format the code using ruff
format:
	uv run ruff format --check --diff .

reformat-ruff:
	uv run ruff format .

# Check the code using ruff
check:
	uv run ruff check .

fix-ruff:
	uv run ruff check . --fix

fix: reformat-ruff fix-ruff
	@echo "Updated code."

test:
	uv run pytest tests/unit

test-cov:
	uv run pytest tests/unit --cov=pyseaweed --cov-report=xml --cov-report=term-missing --cov-fail-under=80

test-integration:
	uv run pytest tests/integration -v -m integration --timeout=120

test-all: test-cov
	uv run pytest tests/integration -v -m integration --timeout=120

# Integration test helpers
weed-up:
	@docker rm -f pyseaweed-test-fs pyseaweed-toxiproxy 2>/dev/null || true
	docker run -d --name pyseaweed-test-fs --network host chrislusf/seaweedfs server -dir=/data -ip=localhost -volume.max=5 -filer
	docker run -d --name pyseaweed-toxiproxy --network host ghcr.io/shopify/toxiproxy:2.12.0
	@echo "Waiting for SeaweedFS master to be ready..."
	@bash -c 'for i in $$(seq 1 60); do nc -z localhost 9333 2>/dev/null && exit 0; sleep 1; done; echo "Timeout waiting for SeaweedFS master" >&2; exit 1'
	@echo "Waiting for SeaweedFS volume to be ready..."
	@bash -c 'for i in $$(seq 1 60); do nc -z localhost 8080 2>/dev/null && exit 0; sleep 1; done; echo "Timeout waiting for SeaweedFS volume" >&2; exit 1'
	@echo "Waiting for a writable volume..."
	@bash -c 'for i in $$(seq 1 60); do curl -sf "http://localhost:9333/dir/assign" 2>/dev/null | grep -q "\"fid\"" && exit 0; sleep 1; done; echo "Timeout waiting for writable volume" >&2; exit 1'
	@echo "Waiting for SeaweedFS filer to be ready..."
	@bash -c 'for i in $$(seq 1 60); do nc -z localhost 8888 2>/dev/null && exit 0; sleep 1; done; echo "Timeout waiting for SeaweedFS filer" >&2; exit 1'
	@echo "Waiting for toxiproxy to be ready..."
	@bash -c 'for i in $$(seq 1 60); do nc -z localhost 8474 2>/dev/null && exit 0; sleep 1; done; echo "Timeout waiting for toxiproxy" >&2; exit 1'
	@echo "SeaweedFS is ready!"

weed-down:
	@docker rm -f pyseaweed-test-fs pyseaweed-toxiproxy 2>/dev/null || true

test-integration-local: weed-up
	@uv run pytest tests/integration -v -m integration --timeout=120; status=$$?; $(MAKE) weed-down; exit $$status

vulture:
	uv run vulture . --exclude .venv,tests,docs --make-whitelist

complexity:
	uv run radon cc . -a -nc

xenon:
	uv run xenon -b D -m B -a B .

bandit:
	uv run bandit -c pyproject.toml -r .

pyright:
	uv run pyright

docs:
	uv run --group docs sphinx-build -W -b html docs docs/_build

# Validate the code (format + check)
validate: format check complexity bandit pyright vulture
	@echo "Validation passed. Your code is ready to push."
