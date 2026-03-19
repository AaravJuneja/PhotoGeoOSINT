PYTHON ?= python3
BUN ?= bun

.PHONY: install-python install-opencode check-python check-opencode check

install-python:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt

install-opencode:
	$(BUN) install --cwd .opencode

check-python:
	$(PYTHON) -m py_compile exif_vision.py gemini_maps_enrich.py grok_search_enrich.py photo_geo_report.py osint_common.py osint_username_lookup.py osint_artifact_extract.py osint_barcode_extract.py osint_challenge_context.py osint_text_extract.py osint_email_phone_probe.py osint_workbench_report.py

check-opencode:
	$(BUN) run --cwd .opencode check

check: check-python check-opencode
