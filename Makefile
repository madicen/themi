# Uses .venv if present, otherwise the python on PATH (as in CI).
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST := $(PYTHON) -m pytest
# Tests run in parallel, one worker per CPU (pytest-xdist), each file kept on one worker.
# PARALLEL= runs them in one process, e.g. to debug with pdb.
PARALLEL ?= -n auto --dist loadfile
# Override to pin a specific interpreter, e.g. make venv VENV_PYTHON=/path/to/python3.13
VENV_PYTHON ?= python3

.PHONY: golden venv install fmt lint test test-all test-live evals router-eval naming-eval cov dev dev-reset dev-invite dev-prod

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
	$(PYTHON) tools/check_layers.py
	$(PYTHON) tools/check_packs.py

test:
	$(PYTEST) $(PARALLEL) tests/unit

test-all:
	$(PYTEST) $(PARALLEL) tests/unit tests/integration tests/scenarios
	@if command -v node >/dev/null 2>&1; then \
		node --test extension/safeway/tests/*.test.js; \
	else \
		echo "Node isn't installed: skipping the Safeway extension tests."; \
	fi

test-live:
	$(PYTEST) tests/live --run-live

# make evals PROVIDER=gemini (or claude, ollama, openai_compat); see tests/evals/README.md
# One slice at a time: make evals EVAL_ARGS='-k energy'
PROVIDER ?= gemini
evals:
	$(PYTEST) tests/evals --run-evals --provider $(PROVIDER) $(EVAL_ARGS)

# P3: how well the tool groups are chosen, over the eval cases (no model, no keys)
router-eval:
	$(PYTEST) tests/scenarios/test_router_eval.py -k recall -s -q

# P8a: how the "which task?" word check does on the naming cases (no model, no keys)
naming-eval:
	$(PYTHON) -c 'from tests.evals.naming import *; print(format_naming(score(load_naming_cases(), word_check)))'

cov:
	$(PYTHON) -m coverage erase
	$(PYTHON) -m coverage run -m pytest $(PARALLEL) tests/unit tests/integration tests/scenarios
	$(PYTHON) -m coverage combine -q
	$(PYTHON) -m coverage report
	$(PYTHON) tools/check_coverage.py

# Themi on this computer, chatting through the Telegram simulator at http://localhost:8090.
# Dev data lives in data/dev/; see tools/dev/runner.py. Outside services are played by the
# test fakes (D5a); FAKES=0 runs without them.
dev:
	$(PYTHON) -m tools.dev $(if $(filter 0,$(FAKES)),--no-fakes)

dev-reset:
	$(PYTHON) -m tools.dev reset

# D4: dev on a fresh, cleaned copy of the Pi's data (data/dev-prod). BACKUP=latest copies
# from the encrypted backups instead; KEEP=1 runs on the copy already there.
dev-prod:
	$(PYTHON) -m tools.dev prod $(if $(BACKUP),--from-backup $(BACKUP)) $(if $(KEEP),--keep)

# make dev-invite NAME=Sam, then send /start <code> as "Someone new" in the simulator
dev-invite:
	$(PYTHON) -m tools.dev invite "$(NAME)"


# CR1: write the golden files again (tests/golden); say why in the commit.
golden:
	THEMI_WRITE_GOLDEN=1 $(PYTEST) tests/scenarios/test_golden.py -q
