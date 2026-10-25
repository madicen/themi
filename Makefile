# Uses .venv if present, otherwise the python on PATH (as in CI).
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST := $(PYTHON) -m pytest
# Override to pin a specific interpreter, e.g. make venv VENV_PYTHON=/path/to/python3.13
VENV_PYTHON ?= python3

.PHONY: venv install fmt lint test test-all test-live evals cov dev dev-reset dev-invite

venv:
	$(VENV_PYTHON) -m venv .venv

install:
	$(PYTHON) -m pip install -e '.[dev]'

fmt:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .
	$(PYTHON) -m pyright --pythonpath "$$($(PYTHON) -c 'import sys; print(sys.executable)')"
	$(PYTHON) tools/check_clock.py

test:
	$(PYTEST) tests/unit

test-all:
	$(PYTEST) tests/unit tests/integration tests/scenarios

test-live:
	$(PYTEST) tests/live --run-live

# make evals PROVIDER=gemini (or claude, ollama, openai_compat); see tests/evals/README.md
# One slice at a time: make evals EVAL_ARGS='-k energy'
PROVIDER ?= gemini
evals:
	$(PYTEST) tests/evals --run-evals --provider $(PROVIDER) $(EVAL_ARGS)

cov:
	$(PYTHON) -m coverage run -m pytest tests/unit tests/integration tests/scenarios
	$(PYTHON) -m coverage report
	$(PYTHON) tools/check_coverage.py

# Themi on this computer, chatting through the Telegram simulator at http://localhost:8090.
# Dev data lives in data/dev/; see tools/dev/runner.py.
dev:
	$(PYTHON) -m tools.dev

dev-reset:
	$(PYTHON) -m tools.dev reset

# make dev-invite NAME=Sam, then send /start <code> as "Someone new" in the simulator
dev-invite:
	$(PYTHON) -m tools.dev invite "$(NAME)"

