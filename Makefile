.PHONY: check lint demo

check:
	python -m compileall -q src scripts
	ruff check src tests tools
	python -m pytest -q
	python tools/check_licenses.py
	python tools/source_manifest.py --check

lint:
	ruff check src tests

demo:
	tradecase demo --fixture fixtures/case_strong --out cases/demo-offline
