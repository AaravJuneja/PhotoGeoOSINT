# PhotoGeoOSINT

Single-command photo OSINT plus a broader OSINT challenge workbench for OpenCode on Ubuntu/WSL.

## What it does

- Extracts GPS from EXIF with native `exiftool`
- Falls back to Pillow EXIF parsing
- Runs OCR with `tesseract` for signs, storefronts, and key text
- Decodes QR codes and barcodes with free local tooling when available
- Uses Gemini vision for landmark and city/country inference when GPS is missing
- Enriches coordinates with official Gemini Google Maps grounding
- Uses OpenCode web search for fast background OSINT in parallel
- Progresses on non-image OSINT too with username lookup, challenge-text pivots, document metadata extraction, QR/barcode decoding, and email/phone normalization

## Files

- `exif_vision.py` - intake, EXIF, OCR, vision, and search hints
- `gemini_maps_enrich.py` - Google Maps grounding helper
- `grok_search_enrich.py` - optional xAI Grok web/X search helper
- `osint_common.py` - shared local input and entity extraction helpers
- `osint_username_lookup.py` - free username lookup with Maigret or Sherlock
- `osint_artifact_extract.py` - generic metadata and strings extraction for challenge artifacts
- `osint_barcode_extract.py` - QR and barcode decoding helper
- `osint_challenge_context.py` - challenge-name and description parser
- `osint_text_extract.py` - raw text clue pivot extractor
- `osint_email_phone_probe.py` - free email and phone normalization plus optional local helper hooks
- `osint_workbench_report.py` - one-shot general OSINT challenge report generator
- `photo_geo_report.py` - one-shot report generator that combines extraction and Maps enrichment
- `.opencode/agents/PhotoGeoOSINT.md` - permanent agent definition
- `.opencode/agents/OSINTWorkbench.md` - general challenge agent definition
- `.opencode/commands/photo-osint.md` - slash command wrapper
- `.opencode/commands/osint-workbench.md` - slash command wrapper for general OSINT challenges
- `.opencode/tools/photo_geo_extract.ts` - OpenCode tool for image extraction
- `.opencode/tools/photo_geo_grok.ts` - optional OpenCode tool for Grok web/X search enrichment
- `.opencode/tools/photo_geo_maps.ts` - OpenCode tool for Maps enrichment
- `.opencode/tools/photo_geo_report.ts` - OpenCode tool for a combined report seed
- `.opencode/tools/osint_username_lookup.ts` - OpenCode tool for free username lookup
- `.opencode/tools/osint_artifact_extract.ts` - OpenCode tool for generic artifact extraction
- `.opencode/tools/osint_barcode_extract.ts` - OpenCode tool for QR and barcode decoding
- `.opencode/tools/osint_challenge_context.ts` - OpenCode tool for challenge parsing
- `.opencode/tools/osint_text_extract.ts` - OpenCode tool for raw clue text extraction
- `.opencode/tools/osint_email_phone_probe.ts` - OpenCode tool for email and phone enrichment
- `.opencode/tools/osint_workbench_report.ts` - OpenCode tool for one-shot general challenge analysis

## Install

System packages:

```bash
sudo apt update && sudo apt install -y exiftool python3-pillow python3-pip tesseract-ocr zbar-tools qpdf binutils
```

Python packages:

```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

Optional free username lookup tooling:

```bash
python3 -m pip install --break-system-packages maigret sherlock-project
```

Optional free identity tooling:

```bash
python3 -m pip install --break-system-packages holehe phonenumbers
```

Optional Ubuntu packages for deeper local probes when you want them:

```bash
sudo apt update && sudo apt install -y dnsutils bind9-host
```

OpenCode tool dependencies:

```bash
bun install --cwd .opencode
```

## Environment

Set your Gemini key for the current shell session only:

```bash
export GEMINI_API_KEY="your_key_here"
```

Optional Grok/xAI session key for extra web and X search enrichment:

```bash
export XAI_API_KEY="your_key_here"
```

Image intake is intentionally permissive for personal use. There is no hard file size cap or rigid type allowlist in the pipeline.

## Use

Direct agent call:

```text
@PhotoGeoOSINT analyze this photo: /path/to/image.jpg
```

General OSINT agent for non-image or mixed-evidence challenges:

```text
@OSINTWorkbench analyze this OSINT challenge: username clue is sakura_snow and the flag asks for the nearest business email
```

One-shot mixed challenge flow:

```text
@OSINTWorkbench analyze this OSINT challenge: challenge name Sakura Rooftop, clue text says the QR code and username both matter, and the answer is a business email
```

Direct agent call with CTF context:

```text
@PhotoGeoOSINT analyze this photo: /path/to/image.jpg challenge name: rooftop_riddle description: identify the exact building and nearby business names
```

Windows path:

```text
@PhotoGeoOSINT analyze this photo: "C:\Users\you\Pictures\image.jpg"
```

URL:

```text
@PhotoGeoOSINT analyze this photo: https://example.com/image.jpg
```

Slash command:

```text
/photo-osint /path/to/image.jpg
```

General slash command:

```text
/osint-workbench username clue is sakura_snow and the challenge mentions a PDF and QR code
```

Direct local script:

```bash
python3 photo_geo_report.py --input /path/to/image.jpg --vision --format markdown
```

Direct local script with challenge context:

```bash
python3 photo_geo_report.py --input /path/to/image.jpg --vision --challenge-name rooftop_riddle --challenge-description "identify the exact building and nearby business names" --format markdown
```

Direct local script with optional Grok augmentation:

```bash
python3 photo_geo_report.py --input /path/to/image.jpg --vision --challenge-name rooftop_riddle --challenge-description "identify the exact building and nearby business names" --use-grok --format markdown
```

Free username lookup helper:

```bash
python3 osint_username_lookup.py --username sakura_snow --tool auto --search-variants
```

Generic artifact metadata helper:

```bash
python3 osint_artifact_extract.py --input /path/to/document.pdf
```

QR and barcode helper:

```bash
python3 osint_barcode_extract.py --input /path/to/ticket.png
```

Challenge-text helper:

```bash
python3 osint_challenge_context.py --challenge-name rooftop_riddle --challenge-description "Find the nearest business email from a rooftop photo and QR sticker"
python3 osint_text_extract.py --text "username clue is sakura_snow, phone +44 1234 567890, maybe a nearby QR code"
```

Email and phone helper:

```bash
python3 osint_email_phone_probe.py --text "contact clue: sakura_snow@proton.me and +44 1234 567890"
```

One-shot general challenge report:

```bash
python3 osint_workbench_report.py --input /path/to/file_or_image --text "username clue is sakura_snow" --challenge-name rooftop_riddle --challenge-description "Find the exact business email" --format markdown
```

## Check

Quick validation:

```bash
make check
```

## Output

The agent returns:

- coordinates and confidence
- Gemini Maps enrichment with grounded sources
- OCR-driven and landmark-driven background OSINT bullets
- a clean report ready to paste elsewhere

The general OSINT agent returns:

- the strongest current lead even when there is no usable image location
- extracted identities and artifact pivots from usernames, files, QR codes, and raw text clues
- next actions that keep the investigation moving instead of stalling on one branch

## Recommended split

- Use `@PhotoGeoOSINT` when the starting point is mainly an image and geolocation matters most.
- Use `@OSINTWorkbench` when the challenge is mixed, starts from text or files, or needs progress even without a visible image location.
