#!/usr/bin/env python3
import argparse
import json
import re
import sys

from osint_common import (
    collect_entities,
    dedupe,
    normalize_whitespace,
    parse_flag_format,
)


def build_search_pivots(text, entities):
    pivots = []
    for handle in entities.get("handles", [])[:10]:
        pivots.extend([handle, f'"{handle}"'])
    for email in entities.get("emails", [])[:8]:
        pivots.append(email)
    for phone in entities.get("phones", [])[:6]:
        pivots.append(phone)
    for url in entities.get("urls", [])[:8]:
        pivots.append(url)
    for coord in entities.get("coordinates", [])[:4]:
        pivots.append(coord)
    for mac in entities.get("mac_addresses", [])[:6]:
        pivots.append(mac)

    quoted = re.findall(r'"([^"]{3,})"', text)
    pivots.extend(f'"{normalize_whitespace(item)}"' for item in quoted)
    return dedupe(pivots)


def recommended_next_steps(entities):
    steps = []
    if entities.get("handles"):
        steps.append("Run username lookup on the strongest handle candidates.")
    if entities.get("urls") or entities.get("domains"):
        steps.append(
            "Run the domain probe on linked domains and profile URLs for DNS, SSL, and WHOIS pivots."
        )
    if entities.get("emails"):
        steps.append(
            "Run the email/phone probe on exposed email addresses for recovery hints, domains, and reuse."
        )
    if entities.get("phones"):
        steps.append(
            "Run the email/phone probe on the phone numbers for normalized formats and regional footprints."
        )
    if entities.get("coordinates"):
        steps.append("Map any coordinates and compare them against challenge wording.")
    if entities.get("mac_addresses"):
        steps.append(
            "Run the Wi-Fi probe on MAC or BSSID values to extract vendor and SSID pivots."
        )
    return steps or [
        "No strong structured entity found; rely on challenge-context search pivots."
    ]


def extract_text_pivots(text, challenge_name=""):
    combined_text = "\n".join(part for part in [challenge_name, text] if part)
    entities = collect_entities([combined_text])
    return {
        "challenge_name": challenge_name,
        "text": text,
        "entities": entities,
        "flag_format_hints": parse_flag_format(combined_text),
        "search_pivots": build_search_pivots(combined_text, entities),
        "recommended_next_steps": recommended_next_steps(entities),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract OSINT-ready pivots from raw clue text or challenge descriptions."
    )
    parser.add_argument(
        "--text", required=True, help="Raw clue text or challenge description"
    )
    parser.add_argument("--challenge-name", default="", help="Optional challenge name")
    args = parser.parse_args()

    result = extract_text_pivots(args.text, challenge_name=args.challenge_name)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
