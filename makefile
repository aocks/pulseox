
# Simple makefile to help manage the project

.PHONY: pypi help test_pypi clean check test lint type profile

PYTEST_EXTRA_FLAGS ?= ""

PYTEST_COV ?= --cov=src/pulseox --cov-report term-missing --cov-fail-under=60

# The stuff below implements an auto help feature
define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

help:   ## Show help for avaiable targets
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

lint:   ## Run linter on project
	uv run pylint src

type:   ## Run type checker
	uv run pytype src

.pylintrc:
	.venv/bin/pylint --generate-rcfile > .pylintrc

test:   ## Run tests
	.venv/bin/py.test -s -vvv --doctest-modules \
            ${PYTEST_EXTRA_FLAGS} src tests

cov:    ## Run tests and include code coverage with PYTEST_COV flag
	PYTEST_EXTRA_FLAGS="${PYTEST_EXTRA_FLAGS} ${PYTEST_COV}" \
          ${MAKE} test

check:  ## Run linting, tests, etc.
	${MAKE} lint
	${MAKE} type
	${MAKE} test


clean:  ## Clean out generated files.
	rm -rf -- dist *.egg-info src/*.egg-info
	rm -rf -- `find . -name '__pycache__' -print`

test_pypi:  clean check dist  ## Test pypi upload (builds, checks, uploads to test.pypi.org)
	uv run python3 -m twine upload --verbose --repository testpypi dist/*

pypi:   clean check cov dist  ## Upload to pypi (builds, checks with coverage, uploads to pypi.org)
	uv run python3 -m twine upload --verbose dist/*

dist:   ## Build distribution
	uv run python3 -m build 

update_dev:  ## Install/update tools required for development/packaging
	./.venv/bin/uv pip install setuptools wheel twine build packaging \
              ruff flake8 pylint pytest pytype coverage pytest-cov
	./.venv/bin/pip3 install -e .
