PYTHON ?= python3
BUN ?= bun

.PHONY: install-python install-opencode check-python check-opencode check

install-python:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt

install-opencode:
	$(BUN) install --cwd .opencode

check-python:
	$(PYTHON) -m py_compile exif_vision.py gemini_maps_enrich.py

check-opencode:
	$(BUN) run --cwd .opencode check

check: check-python check-opencode
