#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

from osint_common import (
    cleanup_path,
    collect_entities,
    dedupe,
    file_details,
    flatten_strings,
    normalize_whitespace,
    parse_flag_format,
    resolve_input,
    safe_json_loads,
)


def run_exiftool(file_path):
    if not shutil.which("exiftool"):
        return {"available": False, "error": "exiftool is not installed"}
    result = subprocess.run(
        ["exiftool", "-j", file_path],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = safe_json_loads(result.stdout)
    metadata = payload[0] if isinstance(payload, list) and payload else {}
    return {
        "available": True,
        "exit_code": result.returncode,
        "metadata": metadata,
        "stderr": result.stderr.strip(),
    }


def run_strings(file_path):
    if not shutil.which("strings"):
        return {"available": False, "error": "strings is not installed"}
    result = subprocess.run(
        ["strings", "-a", "-n", "6", file_path],
        capture_output=True,
        text=True,
        check=False,
        errors="replace",
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    interesting = []
    for line in lines:
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in [
                "http://",
                "https://",
                "@",
                "flag{",
                "ctf{",
                "mailto:",
                "tel:",
                "wifi:",
                "geo:",
                "bitcoin:",
                "ethereum:",
            ]
        ):
            interesting.append(line)
    return {
        "available": True,
        "exit_code": result.returncode,
        "total_lines": len(lines),
        "interesting_lines": dedupe(interesting),
        "sample_lines": dedupe(lines[:80]),
        "stderr": result.stderr.strip(),
    }


def extract_zip_context(file_path):
    if not zipfile.is_zipfile(file_path):
        return {"is_zip": False}

    entry_names = []
    text_snippets = []
    with zipfile.ZipFile(file_path, "r") as archive:
        for info in archive.infolist():
            entry_names.append(info.filename)
            lowered = info.filename.lower()
            if info.file_size > 1024 * 1024:
                continue
            if not lowered.endswith(
                (
                    ".xml",
                    ".rels",
                    ".txt",
                    ".svg",
                    ".html",
                    ".json",
                    ".md",
                )
            ):
                continue
            with archive.open(info, "r") as handle:
                raw = handle.read().decode("utf-8", errors="replace")
            cleaned = normalize_whitespace(re.sub(r"<[^>]+>", " ", raw))
            if cleaned:
                text_snippets.append(cleaned)

    return {
        "is_zip": True,
        "entry_count": len(entry_names),
        "entry_names": entry_names,
        "text_snippets": dedupe(text_snippets)[:80],
    }


def extract_pdf_context(file_path):
    if not file_path.lower().endswith(".pdf"):
        return {"is_pdf": False}

    summary = {
        "is_pdf": True,
        "qpdf_available": False,
        "qpdf_check": "",
        "page_count": "",
    }
    if shutil.which("qpdf"):
        check_result = subprocess.run(
            ["qpdf", "--check", file_path],
            capture_output=True,
            text=True,
            check=False,
        )
        pages_result = subprocess.run(
            ["qpdf", "--show-npages", file_path],
            capture_output=True,
            text=True,
            check=False,
        )
        summary["qpdf_available"] = True
        summary["qpdf_check"] = normalize_whitespace(
            check_result.stderr or check_result.stdout
        )
        summary["page_count"] = normalize_whitespace(pages_result.stdout)
    return summary


def build_candidate_usernames(texts, entities):
    candidates = list(entities.get("handles", []))
    for email in entities.get("emails", []):
        if "@" in email:
            candidates.append(email.split("@", 1)[0])
    for text in texts:
        for token in re.findall(r"\b[A-Za-z0-9][A-Za-z0-9._-]{3,31}\b", text):
            lowered = token.lower()
            if lowered in {
                "http",
                "https",
                "document",
                "metadata",
                "version",
                "creator",
                "author",
                "producer",
                "microsoft",
                "google",
                "windows",
                "ubuntu",
            }:
                continue
            if (
                any(char.isdigit() for char in token)
                or "_" in token
                or "-" in token
                or "." in token
            ):
                candidates.append(token)
    return dedupe(candidates)


def suggested_pivots(entities, usernames):
    pivots = []
    for handle in usernames[:10]:
        pivots.append(f"lookup username: {handle}")
    for email in entities.get("emails", [])[:8]:
        pivots.append(f"search email: {email}")
    for phone in entities.get("phones", [])[:6]:
        pivots.append(f"search phone: {phone}")
    for url in entities.get("urls", [])[:8]:
        pivots.append(f"review url: {url}")
    for coord in entities.get("coordinates", [])[:4]:
        pivots.append(f"map coordinate: {coord}")
    for mac in entities.get("mac_addresses", [])[:6]:
        pivots.append(f"search BSSID/MAC: {mac}")
    return dedupe(pivots)


def extract_artifact(input_value):
    resolution = resolve_input(input_value, user_agent="OSINTWorkbench/1.0")
    cleanup = resolution.get("cleanup_path")
    file_path = resolution["resolved_path"]
    try:
        metadata_result = run_exiftool(file_path)
        strings_result = run_strings(file_path)
        zip_context = extract_zip_context(file_path)
        pdf_context = extract_pdf_context(file_path)

        texts = []
        if metadata_result.get("metadata"):
            texts.extend(flatten_strings(metadata_result["metadata"]))
        texts.extend(strings_result.get("interesting_lines", []))
        texts.extend(strings_result.get("sample_lines", []))
        text_snippets = zip_context.get("text_snippets", [])
        if isinstance(text_snippets, list):
            texts.extend(text_snippets)

        entities = collect_entities(texts)
        usernames = build_candidate_usernames(texts, entities)

        return {
            "input": input_value,
            "resolved_path": file_path,
            "input_type": resolution["input_type"],
            "file_details": file_details(file_path),
            "metadata": metadata_result,
            "strings": strings_result,
            "zip_context": zip_context,
            "pdf_context": pdf_context,
            "entities": entities,
            "candidate_usernames": usernames,
            "flag_format_hints": parse_flag_format("\n".join(texts)),
            "suggested_pivots": suggested_pivots(entities, usernames),
        }
    finally:
        cleanup_path(cleanup)


def main():
    parser = argparse.ArgumentParser(
        description="Extract metadata and OSINT pivots from generic challenge artifacts."
    )
    parser.add_argument("--input", required=True, help="Path, Windows path, or URL")
    args = parser.parse_args()

    try:
        result = extract_artifact(args.input)
    except Exception as exc:
        result = {"error": str(exc), "input": args.input}

    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
