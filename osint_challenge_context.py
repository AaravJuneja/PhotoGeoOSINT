#!/usr/bin/env python3
import argparse
import json
import re
import sys

from osint_common import dedupe, normalize_whitespace, parse_flag_format


STOP_WORDS = {
    "about",
    "after",
    "against",
    "agent",
    "answer",
    "around",
    "before",
    "between",
    "challenge",
    "current",
    "description",
    "exact",
    "figure",
    "format",
    "from",
    "identify",
    "image",
    "location",
    "metadata",
    "nearest",
    "person",
    "photo",
    "place",
    "provided",
    "question",
    "should",
    "solve",
    "target",
    "their",
    "there",
    "these",
    "this",
    "through",
    "using",
    "what",
    "where",
    "which",
    "with",
}

MODULE_RULES = {
    "osint_workbench_report": [
        "challenge",
        "flag",
        "answer",
        "nearest",
        "exact",
        "identify",
    ],
    "photo_geo_report": [
        "photo",
        "image",
        "landmark",
        "geolocation",
        "location",
        "street",
        "building",
    ],
    "osint_barcode_extract": ["qr", "barcode", "ticket", "scan", "wifi", "qrcode"],
    "osint_artifact_extract": [
        "metadata",
        "document",
        "pdf",
        "docx",
        "pptx",
        "svg",
        "file",
        "author",
    ],
    "osint_username_lookup": [
        "username",
        "handle",
        "profile",
        "account",
        "social",
        "nickname",
    ],
    "osint_email_phone_probe": [
        "email",
        "phone",
        "telephone",
        "contact",
        "sms",
        "number",
    ],
    "osint_text_extract": ["text", "description", "clue", "writeup", "hint"],
}


def keyword_hits(text):
    lowered = text.lower()
    hits = {}
    for module, keywords in MODULE_RULES.items():
        matched = [keyword for keyword in keywords if keyword in lowered]
        if matched:
            hits[module] = matched
    return hits


def extract_constraints(text):
    lowered = text.lower()
    return {
        "needs_exact_match": any(
            word in lowered for word in ["exact", "precise", "specific"]
        ),
        "needs_nearby_result": any(
            word in lowered for word in ["nearest", "nearby", "within", "walk"]
        ),
        "needs_temporal_reasoning": any(
            word in lowered for word in ["before", "after", "oldest", "current", "now"]
        ),
        "needs_contact_answer": any(
            word in lowered for word in ["email", "phone", "telephone"]
        ),
        "needs_identity_answer": any(
            word in lowered for word in ["username", "handle", "real name", "person"]
        ),
    }


def extract_entities(text):
    quoted = re.findall(r'"([^"]{3,})"', text)
    parenthetical = re.findall(r"\(([^)]{3,})\)", text)
    token_candidates = []
    for token in re.findall(r"\b[A-Za-z0-9][A-Za-z0-9._-]{3,}\b", text):
        lowered = token.lower()
        if lowered in STOP_WORDS:
            continue
        if token.isdigit():
            continue
        token_candidates.append(token)
    return {
        "quoted_phrases": dedupe(quoted),
        "parenthetical_phrases": dedupe(parenthetical),
        "keywords": dedupe(token_candidates)[:25],
    }


def recommended_modules(text):
    hits = keyword_hits(text)
    ordered = []
    for module in [
        "osint_workbench_report",
        "photo_geo_report",
        "osint_barcode_extract",
        "osint_artifact_extract",
        "osint_username_lookup",
        "osint_email_phone_probe",
        "osint_text_extract",
    ]:
        if module in hits:
            ordered.append(module)
    if not ordered:
        ordered.append("osint_artifact_extract")
    return ordered, hits


def parse_context(challenge_name="", challenge_description=""):
    text = normalize_whitespace(
        " ".join(part for part in [challenge_name, challenge_description] if part)
    )
    modules, keyword_map = recommended_modules(text)
    entities = extract_entities(text)
    pivots = []
    if challenge_name:
        pivots.append(f'"{challenge_name}"')
    pivots.extend(f'"{phrase}"' for phrase in entities["quoted_phrases"])
    pivots.extend(entities["keywords"][:12])
    return {
        "challenge_name": challenge_name,
        "challenge_description": challenge_description,
        "constraints": extract_constraints(text),
        "flag_format_hints": parse_flag_format(challenge_description),
        "recommended_modules": modules,
        "module_keyword_hits": keyword_map,
        "entities": entities,
        "search_pivots": dedupe(pivots),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse challenge text into tool and pivot recommendations."
    )
    parser.add_argument("--challenge-name", default="", help="Optional challenge name")
    parser.add_argument(
        "--challenge-description", default="", help="Optional challenge description"
    )
    args = parser.parse_args()

    result = parse_context(args.challenge_name, args.challenge_description)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
