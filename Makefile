PYTHON ?= python3
export PYTHONPATH := src

.PHONY: test check demo

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m book_data_api.cli validate

demo:
	$(PYTHON) -m book_data_api.cli metadata --json
	$(PYTHON) -m book_data_api.cli records --category developer-tools --json

