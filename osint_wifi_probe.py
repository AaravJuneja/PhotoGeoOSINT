#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys

from osint_common import collect_entities, dedupe, normalize_whitespace, parse_wifi_payload


SSID_PATTERN = re.compile(
    r"(?:ssid|wifi name|network name)\s*[:=]\s*['\"]?([^;\n'\"]{1,64})", re.IGNORECASE
)
WIFI_PAYLOAD_PATTERN = re.compile(r"WIFI:[^\s]+", re.IGNORECASE)

OUI_FILES = [
    "/var/lib/ieee-data/oui.txt",
    "/usr/share/ieee-data/oui.txt",
    "/usr/share/misc/oui.txt",
]


def normalize_bssid(value):
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(cleaned) != 12:
        return ""
    upper = cleaned.upper()
    return ":".join(upper[index : index + 2] for index in range(0, 12, 2))


def extract_ssids(text):
    ssids = [normalize_whitespace(match) for match in SSID_PATTERN.findall(text or "")]
    for payload in WIFI_PAYLOAD_PATTERN.findall(text or ""):
        parsed = parse_wifi_payload(payload)
        if parsed.get("ssid"):
            ssids.append(parsed["ssid"])
    return dedupe(item for item in ssids if item)


def oui_vendor(bssid):
    prefix = normalize_bssid(bssid).replace(":", "")[:6]
    if len(prefix) != 6:
        return ""
    prefix_dash = "-".join(prefix[index : index + 2] for index in range(0, 6, 2))
    for file_path in OUI_FILES:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if prefix_dash in line and "(hex)" in line:
                        vendor = line.split("(hex)", 1)[1].strip()
                        if vendor:
                            return vendor
        except OSError:
            continue
    return ""


def probe_wifi(text="", bssid="", ssid=""):
    entities = collect_entities([text]) if text else {"mac_addresses": []}
    bssids = []
    if bssid:
        normalized = normalize_bssid(bssid)
        if normalized:
            bssids.append(normalized)
    for item in entities.get("mac_addresses", []):
        normalized = normalize_bssid(item)
        if normalized:
            bssids.append(normalized)
    bssids = dedupe(bssids)

    ssids = []
    if ssid:
        ssids.append(normalize_whitespace(ssid))
    ssids.extend(extract_ssids(text))
    ssids = dedupe(item for item in ssids if item)

    wifi_payloads = [match for match in WIFI_PAYLOAD_PATTERN.findall(text or "")]
    parsed_payloads = [parse_wifi_payload(payload) for payload in wifi_payloads]

    bssid_reports = []
    for item in bssids:
        bssid_reports.append(
            {
                "bssid": item,
                "oui_prefix": item[:8],
                "vendor": oui_vendor(item),
            }
        )

    pivots = []
    for report in bssid_reports:
        pivots.append(report["bssid"])
        if report.get("vendor"):
            pivots.append(report["vendor"])
    pivots.extend(ssids)
    for payload in parsed_payloads:
        if payload.get("ssid"):
            pivots.append(payload["ssid"])

    return {
        "input_text": text,
        "bssids": bssid_reports,
        "ssids": ssids,
        "wifi_payloads": parsed_payloads,
        "search_pivots": dedupe(item for item in pivots if item),
        "local_oui_files": [path for path in OUI_FILES if os.path.exists(path)],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Free local-first Wi-Fi and BSSID probe helper."
    )
    parser.add_argument(
        "--text",
        default="",
        help="Raw text containing SSIDs, BSSIDs, or Wi-Fi QR payloads",
    )
    parser.add_argument(
        "--bssid", default="", help="Specific BSSID or MAC address to probe"
    )
    parser.add_argument("--ssid", default="", help="Specific SSID to probe")
    args = parser.parse_args()

    result = probe_wifi(text=args.text, bssid=args.bssid, ssid=args.ssid)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
