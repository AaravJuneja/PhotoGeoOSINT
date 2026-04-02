#!/usr/bin/env python3
import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys

from osint_common import EMAIL_PATTERN, collect_entities, dedupe, normalize_whitespace

try:
    phonenumbers = importlib.import_module("phonenumbers")
    carrier = importlib.import_module("phonenumbers.carrier")
    geocoder = importlib.import_module("phonenumbers.geocoder")
except ImportError:
    phonenumbers = None
    carrier = None
    geocoder = None


def available_tools():
    return {
        "host": shutil.which("host"),
        "nslookup": shutil.which("nslookup"),
        "dig": shutil.which("dig"),
        "holehe": shutil.which("holehe"),
        "ignorant": shutil.which("ignorant"),
        "phonenumbers": bool(phonenumbers),
    }


def normalize_email(value):
    cleaned = normalize_whitespace(value).strip('<>()[]{}.,;:"')
    if not EMAIL_PATTERN.fullmatch(cleaned):
        return ""
    return cleaned.lower()


def gravatar_hash(email):
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()


def email_local_analysis(email):
    local_part, domain = email.split("@", 1)
    domain_lower = domain.lower()
    suggestions = [local_part]
    if "." in local_part:
        suggestions.extend(local_part.split("."))
    if "_" in local_part:
        suggestions.extend(local_part.split("_"))
    return {
        "email": email,
        "local_part": local_part,
        "domain": domain_lower,
        "local_part_variants": dedupe(suggestions),
        "gravatar_hash": gravatar_hash(email),
        "gravatar_url": f"https://www.gravatar.com/avatar/{gravatar_hash(email)}?d=404",
    }


def resolve_domain_ips(domain):
    addresses = []
    try:
        infos = socket.getaddrinfo(domain, None)
        for info in infos:
            if info[4] and info[4][0]:
                addresses.append(info[4][0])
    except socket.gaierror:
        return []
    return dedupe(addresses)


def dns_query(domain, query_type):
    if shutil.which("host"):
        result = subprocess.run(
            ["host", "-t", query_type, domain],
            capture_output=True,
            text=True,
            check=False,
        )
        return normalize_whitespace(result.stdout or result.stderr)
    if shutil.which("nslookup"):
        result = subprocess.run(
            ["nslookup", "-type=" + query_type, domain],
            capture_output=True,
            text=True,
            check=False,
        )
        return normalize_whitespace(result.stdout or result.stderr)
    if shutil.which("dig"):
        result = subprocess.run(
            ["dig", "+short", domain, query_type],
            capture_output=True,
            text=True,
            check=False,
        )
        return normalize_whitespace(result.stdout or result.stderr)
    return ""


def email_dns_analysis(email):
    domain = email.split("@", 1)[1].lower()
    return {
        "domain": domain,
        "a_records": resolve_domain_ips(domain),
        "mx_lookup": dns_query(domain, "MX"),
        "txt_lookup": dns_query(domain, "TXT"),
    }


def parse_phone_local(value):
    digits = re.sub(r"\D", "", value)
    return {
        "raw": value,
        "digits_only": digits,
        "length": len(digits),
    }


def parse_phone_enriched(value, default_region="US"):
    basic = parse_phone_local(value)
    if phonenumbers is None:
        basic["library_available"] = False
        return basic

    try:
        parsed = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException as exc:
        basic.update({"library_available": True, "error": str(exc)})
        return basic

    basic.update(
        {
            "library_available": True,
            "international": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            ),
            "e164": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            ),
            "possible": phonenumbers.is_possible_number(parsed),
            "valid": phonenumbers.is_valid_number(parsed),
            "country_code": parsed.country_code,
            "region_code": phonenumbers.region_code_for_number(parsed),
            "number_type": str(phonenumbers.number_type(parsed)),
        }
    )
    if geocoder is not None:
        basic["location"] = geocoder.description_for_number(parsed, "en")
    if carrier is not None:
        basic["carrier"] = carrier.name_for_number(parsed, "en")
    return basic


def maybe_run_command(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        errors="replace",
    )
    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def optional_email_tools(email):
    outputs = {}
    if shutil.which("holehe"):
        outputs["holehe"] = maybe_run_command(
            ["holehe", email, "--only-used", "--no-color"]
        )
    return outputs


def optional_phone_tools(phone):
    outputs = {}
    if shutil.which("ignorant"):
        outputs["ignorant"] = maybe_run_command(["ignorant", phone])
    return outputs


def probe_identifiers(text="", email="", phone="", default_region="US"):
    entities = collect_entities([text]) if text else {"emails": [], "phones": []}
    emails = []
    phones = []
    if email:
        normalized = normalize_email(email)
        if normalized:
            emails.append(normalized)
    if phone:
        phones.append(normalize_whitespace(phone))
    emails.extend(entities.get("emails", []))
    phones.extend(entities.get("phones", []))
    emails = dedupe(emails)
    phones = dedupe(phones)

    email_reports = []
    for item in emails:
        email_reports.append(
            {
                "summary": email_local_analysis(item),
                "dns": email_dns_analysis(item),
                "optional_tools": optional_email_tools(item),
            }
        )

    phone_reports = []
    for item in phones:
        phone_reports.append(
            {
                "summary": parse_phone_enriched(item, default_region=default_region),
                "optional_tools": optional_phone_tools(item),
            }
        )

    search_pivots = []
    for report in email_reports:
        summary = report["summary"]
        search_pivots.append(summary["email"])
        search_pivots.extend(summary.get("local_part_variants", []))
        search_pivots.append(summary.get("domain", ""))
    for report in phone_reports:
        summary = report["summary"]
        search_pivots.extend(
            value
            for value in [
                summary.get("raw"),
                summary.get("e164"),
                summary.get("international"),
                summary.get("location"),
                summary.get("carrier"),
            ]
            if value
        )

    return {
        "input_text": text,
        "email_count": len(email_reports),
        "phone_count": len(phone_reports),
        "emails": email_reports,
        "phones": phone_reports,
        "available_tools": available_tools(),
        "search_pivots": dedupe(search_pivots),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Free local-first email and phone OSINT normalization with optional helper tool hooks."
    )
    parser.add_argument(
        "--text", default="", help="Raw text containing emails and phone numbers"
    )
    parser.add_argument("--email", default="", help="Specific email to probe")
    parser.add_argument("--phone", default="", help="Specific phone number to probe")
    parser.add_argument(
        "--default-region",
        default="US",
        help="Default region hint for phone parsing when country code is absent",
    )
    args = parser.parse_args()

    result = probe_identifiers(
        text=args.text,
        email=args.email,
        phone=args.phone,
        default_region=args.default_region,
    )
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
