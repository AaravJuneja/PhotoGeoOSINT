#!/usr/bin/env python3
import argparse
import json
import shutil
import socket
import ssl
import subprocess
import sys
from urllib.parse import urlparse

from osint_common import collect_entities, dedupe, normalize_whitespace


def available_tools():
    return {
        "host": shutil.which("host"),
        "nslookup": shutil.which("nslookup"),
        "dig": shutil.which("dig"),
        "whois": shutil.which("whois"),
    }


def normalize_domain(value):
    cleaned = normalize_whitespace(value).strip().strip("/")
    if not cleaned:
        return ""
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        cleaned = parsed.netloc or parsed.path
    if "@" in cleaned and "/" not in cleaned:
        cleaned = cleaned.rsplit("@", 1)[1]
    cleaned = cleaned.split("/", 1)[0].split(":", 1)[0].strip().lower().strip(".")
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    if not cleaned or "." not in cleaned:
        return ""
    return cleaned


def resolve_ips(domain):
    addresses = []
    try:
        infos = socket.getaddrinfo(domain, None)
    except socket.gaierror:
        return []
    for info in infos:
        if info[4] and info[4][0]:
            addresses.append(info[4][0])
    return dedupe(addresses)


def run_lookup(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        errors="replace",
    )
    return normalize_whitespace(result.stdout or result.stderr)


def dns_lookup(domain, query_type):
    if shutil.which("host"):
        return run_lookup(["host", "-t", query_type, domain])
    if shutil.which("dig"):
        return run_lookup(["dig", "+short", domain, query_type])
    if shutil.which("nslookup"):
        return run_lookup(["nslookup", "-type=" + query_type, domain])
    return ""


def whois_lookup(domain):
    if not shutil.which("whois"):
        return {"available": False, "summary_lines": []}
    result = subprocess.run(
        ["whois", domain],
        capture_output=True,
        text=True,
        check=False,
        errors="replace",
    )
    output = result.stdout or result.stderr
    summary_lines = []
    for line in output.splitlines()[:400]:
        cleaned = normalize_whitespace(line)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(
            marker in lowered
            for marker in [
                "registrar:",
                "registrant",
                "organisation",
                "organization",
                "orgname",
                "country:",
                "name server:",
                "abuse",
                "admin",
                "tech",
                "email:",
            ]
        ):
            summary_lines.append(cleaned)
    return {
        "available": True,
        "summary_lines": dedupe(summary_lines)[:40],
    }


def ssl_probe(domain):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=6) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as tls_sock:
                cert = tls_sock.getpeercert()
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    cert_data = dict(cert or {})

    subject = []
    for item in cert_data.get("subject", []):
        if isinstance(item, tuple):
            for pair in item:
                if isinstance(pair, tuple) and len(pair) == 2:
                    subject.append(f"{pair[0]}={pair[1]}")
    issuer = []
    for item in cert_data.get("issuer", []):
        if isinstance(item, tuple):
            for pair in item:
                if isinstance(pair, tuple) and len(pair) == 2:
                    issuer.append(f"{pair[0]}={pair[1]}")

    san_entries = []
    for entry in cert_data.get("subjectAltName", []):
        if isinstance(entry, tuple) and len(entry) == 2:
            san_entries.append(str(entry[1]))

    return {
        "available": True,
        "subject": subject,
        "issuer": issuer,
        "not_before": cert_data.get("notBefore", ""),
        "not_after": cert_data.get("notAfter", ""),
        "subject_alt_names": dedupe(san_entries)[:30],
    }


def domain_report(domain):
    return {
        "domain": domain,
        "ips": resolve_ips(domain),
        "dns": {
            "mx": dns_lookup(domain, "MX"),
            "txt": dns_lookup(domain, "TXT"),
            "ns": dns_lookup(domain, "NS"),
        },
        "whois": whois_lookup(domain),
        "ssl": ssl_probe(domain),
    }


def search_pivots(reports):
    pivots = []
    for report in reports:
        pivots.append(report.get("domain", ""))
        pivots.extend(report.get("ips", []))
        whois_lines = ((report.get("whois") or {}).get("summary_lines") or [])[:10]
        pivots.extend(whois_lines)
        san_entries = ((report.get("ssl") or {}).get("subject_alt_names") or [])[:10]
        pivots.extend(san_entries)
    return dedupe(item for item in pivots if item)


def probe_domains(text="", domain="", url=""):
    candidates = []
    if domain:
        normalized = normalize_domain(domain)
        if normalized:
            candidates.append(normalized)
    if url:
        normalized = normalize_domain(url)
        if normalized:
            candidates.append(normalized)
    if text:
        entities = collect_entities([text])
        for item in entities.get("domains", []):
            normalized = normalize_domain(item)
            if normalized:
                candidates.append(normalized)
        for item in entities.get("urls", []):
            normalized = normalize_domain(item)
            if normalized:
                candidates.append(normalized)
    domains = dedupe(candidates)
    reports = [domain_report(item) for item in domains]
    return {
        "input_text": text,
        "domains": reports,
        "available_tools": available_tools(),
        "search_pivots": search_pivots(reports),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Free local-first domain, DNS, WHOIS, and SSL probe helper."
    )
    parser.add_argument(
        "--text", default="", help="Raw text containing domains, emails, or URLs"
    )
    parser.add_argument("--domain", default="", help="Specific domain to probe")
    parser.add_argument("--url", default="", help="Specific URL to probe")
    args = parser.parse_args()

    result = probe_domains(text=args.text, domain=args.domain, url=args.url)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
