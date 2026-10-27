.PHONY: check lint demo

check:
	python -m compileall -q src scripts
	ruff check src tests
	python -m pytest -q

lint:
	ruff check src tests

demo:
	tradecase demo --fixture fixtures/case_strong --out cases/demo-offline
