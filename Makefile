.PHONY: check lint demo

check:
	python -m compileall -q src scripts
	ruff check src tests tools
	ruff check scripts/contracts.py scripts/customs_verify.py scripts/dedupe_leads.py scripts/evaluate_outreach_drafts.py scripts/extract_contacts.py scripts/normalize_search_results.py scripts/send_smtp.py
	python -m pytest -q
	python tools/check_licenses.py
	python tools/source_manifest.py --check

lint:
	ruff check src tests

demo:
	tradecase demo --fixture fixtures/case_strong --out cases/demo-offline
