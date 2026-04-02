#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

from osint_common import (
    cleanup_path,
    collect_entities,
    dedupe,
    file_details,
    parse_wifi_payload,
    resolve_input,
)

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None


def normalize_payload(payload):
    lowered = payload.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(payload)
        return {"type": "url", "url": payload, "domain": parsed.netloc.lower()}
    if lowered.startswith("mailto:"):
        parsed = urlparse(payload)
        return {
            "type": "mailto",
            "email": parsed.path,
            "query": parse_qs(parsed.query),
        }
    if lowered.startswith("tel:"):
        return {"type": "telephone", "number": payload[4:]}
    if lowered.startswith("geo:"):
        return {"type": "geo", "coordinates": payload[4:]}
    if lowered.startswith("wifi:"):
        return parse_wifi_payload(payload)
    if payload.startswith("BEGIN:VCARD"):
        return {"type": "vcard", "raw": payload}
    if payload.startswith("MECARD:"):
        return {"type": "mecard", "raw": payload}
    if lowered.startswith("otpauth://"):
        return {"type": "otpauth", "uri": payload}
    return {"type": "text", "text": payload}


def decode_with_zbar(image_path):
    if not shutil.which("zbarimg"):
        return {"available": False, "error": "zbarimg is not installed"}
    result = subprocess.run(
        ["zbarimg", "--quiet", image_path],
        capture_output=True,
        text=True,
        check=False,
        errors="replace",
    )
    items = []
    for line in result.stdout.splitlines():
        cleaned = line.strip()
        if not cleaned or ":" not in cleaned:
            continue
        symbology, payload = cleaned.split(":", 1)
        items.append(
            {
                "symbology": symbology.strip(),
                "payload": payload.strip(),
                "normalized": normalize_payload(payload.strip()),
            }
        )
    return {
        "available": True,
        "exit_code": result.returncode,
        "stderr": result.stderr.strip(),
        "items": items,
    }


def create_variants(image_path):
    variants = [("original", image_path, False)]
    if Image is None or ImageOps is None:
        return variants

    temp_files = []
    image = Image.open(image_path)
    prepared = {
        "rot90": image.rotate(90, expand=True),
        "rot180": image.rotate(180, expand=True),
        "rot270": image.rotate(270, expand=True),
        "grayscale": ImageOps.autocontrast(image.convert("L")),
        "threshold": ImageOps.autocontrast(image.convert("L")).point(
            lambda value: 255 if value > 160 else 0
        ),
    }

    for name, variant in prepared.items():
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        variant.save(handle.name)
        handle.close()
        temp_files.append(handle.name)
        variants.append((name, handle.name, True))
    return variants


def cleanup_variants(variants):
    for _, file_path, should_cleanup in variants:
        if should_cleanup:
            cleanup_path(file_path)


def extract_barcodes(input_value):
    resolution = resolve_input(input_value, user_agent="OSINTWorkbench/1.0")
    cleanup = resolution.get("cleanup_path")
    image_path = resolution["resolved_path"]
    variants = create_variants(image_path)
    try:
        attempts = []
        payloads = []
        for name, variant_path, _ in variants:
            decoded = decode_with_zbar(variant_path)
            attempt = {
                "variant": name,
                "available": decoded.get("available", False),
                "exit_code": decoded.get("exit_code"),
                "decoded_count": len(decoded.get("items", [])),
                "stderr": decoded.get("stderr", ""),
            }
            attempts.append(attempt)
            payloads.extend(decoded.get("items", []))

        unique_items = []
        seen = set()
        for item in payloads:
            key = (item["symbology"], item["payload"])
            if key in seen:
                continue
            seen.add(key)
            unique_items.append(item)

        entity_texts = [item["payload"] for item in unique_items]
        return {
            "input": input_value,
            "resolved_path": image_path,
            "input_type": resolution["input_type"],
            "file_details": file_details(image_path),
            "attempts": attempts,
            "decoded_items": unique_items,
            "entities": collect_entities(entity_texts),
        }
    finally:
        cleanup_variants(variants)
        cleanup_path(cleanup)


def main():
    parser = argparse.ArgumentParser(
        description="Decode QR codes and barcodes from a local or remote image."
    )
    parser.add_argument("--input", required=True, help="Path, Windows path, or URL")
    args = parser.parse_args()

    try:
        result = extract_barcodes(args.input)
    except Exception as exc:
        result = {"error": str(exc), "input": args.input}

    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
