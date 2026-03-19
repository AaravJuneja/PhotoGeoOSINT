# PhotoGeoOSINT

Single-command photo OSINT for OpenCode on Ubuntu/WSL.

## What it does

- Extracts GPS from EXIF with native `exiftool`
- Falls back to Pillow EXIF parsing
- Runs OCR with `tesseract` for signs, storefronts, and key text
- Uses Gemini vision for landmark and city/country inference when GPS is missing
- Enriches coordinates with official Gemini Google Maps grounding
- Uses OpenCode web search for fast background OSINT in parallel

## Files

- `exif_vision.py` - intake, EXIF, OCR, vision, and search hints
- `gemini_maps_enrich.py` - Google Maps grounding helper
- `.opencode/agents/PhotoGeoOSINT.md` - permanent agent definition
- `.opencode/commands/photo-osint.md` - slash command wrapper
- `.opencode/tools/photo_geo_extract.ts` - OpenCode tool for image extraction
- `.opencode/tools/photo_geo_maps.ts` - OpenCode tool for Maps enrichment

## Install

System packages:

```bash
sudo apt update && sudo apt install -y exiftool python3-pillow python3-pip tesseract-ocr
```

Python packages:

```bash
python3 -m pip install --break-system-packages -r requirements.txt
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

## Use

Direct agent call:

```text
@PhotoGeoOSINT analyze this photo: /path/to/image.jpg
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
