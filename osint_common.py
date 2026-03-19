#!/usr/bin/env python3
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


URL_PATTERN = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:(?<!\w)\+?\d[\d().\- ]{6,}\d)")
MAC_PATTERN = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
COORD_PATTERN = re.compile(
    r"(?P<lat>-?\d{1,3}\.\d{3,})\s*[,/ ]\s*(?P<lng>-?\d{1,3}\.\d{3,})"
)
HANDLE_PATTERN = re.compile(r"(?<![\w/])@(?P<handle>[A-Za-z0-9][A-Za-z0-9._-]{2,31})")
GENERIC_USERNAME_PATTERN = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9._-]{3,31}\b")
COMMON_WORDS = {
    "about",
    "account",
    "admin",
    "answer",
    "author",
    "before",
    "challenge",
    "contact",
    "current",
    "description",
    "document",
    "email",
    "example",
    "export",
    "false",
    "first",
    "format",
    "google",
    "image",
    "information",
    "license",
    "location",
    "metadata",
    "nearest",
    "number",
    "person",
    "phone",
    "profile",
    "report",
    "result",
    "sample",
    "social",
    "source",
    "string",
    "target",
    "title",
    "true",
    "unknown",
    "username",
    "value",
    "version",
    "website",
}


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text or "").strip()


def dedupe(items):
    seen = set()
    output = []
    for item in items:
        cleaned = normalize_whitespace(str(item))
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def is_url(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def is_windows_path(value):
    return bool(re.match(r"^[A-Za-z]:\\", value))


def wsl_path(value):
    result = subprocess.run(
        ["wslpath", "-u", value],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FileNotFoundError(
            result.stderr.strip() or f"Could not convert path: {value}"
        )
    return result.stdout.strip()


def guess_suffix(url, content_type):
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return guessed or ".bin"


def resolve_input(input_value, user_agent="PhotoGeoOSINT/1.0"):
    raw = input_value.strip().strip('"').strip("'")
    cleanup_path = None

    if raw.startswith("file://"):
        raw = unquote(urlparse(raw).path)

    if is_url(raw):
        request = Request(raw, headers={"User-Agent": user_agent})
        with urlopen(request, timeout=90) as response:
            content = response.read()
            content_type = (
                (response.headers.get("Content-Type", "") or "").split(";")[0].strip()
            )
            suffix = guess_suffix(raw, response.headers.get("Content-Type", ""))
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.write(content)
        handle.flush()
        handle.close()
        cleanup_path = handle.name
        return {
            "resolved_path": handle.name,
            "input_type": "url",
            "cleanup_path": cleanup_path,
            "input": raw,
            "remote_content_type": content_type or "application/octet-stream",
        }

    if is_windows_path(raw):
        raw = wsl_path(raw)
        input_type = "windows_path"
    else:
        input_type = "path"

    resolved = os.path.abspath(os.path.expanduser(raw))
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Input not found: {resolved}")
    return {
        "resolved_path": resolved,
        "input_type": input_type,
        "cleanup_path": cleanup_path,
        "input": input_value,
        "remote_content_type": "",
    }


def cleanup_path(path_value):
    if path_value and os.path.exists(path_value):
        os.remove(path_value)


def guess_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


def sha256_file(file_path):
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_details(file_path):
    path_obj = Path(file_path)
    return {
        "basename": path_obj.name,
        "extension": path_obj.suffix.lower(),
        "mime_type": guess_mime_type(file_path),
        "size_bytes": os.path.getsize(file_path),
        "sha256": sha256_file(file_path),
    }


def flatten_strings(value):
    output = []
    if isinstance(value, dict):
        for key, nested in value.items():
            output.append(str(key))
            output.extend(flatten_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            output.extend(flatten_strings(nested))
    elif value is not None:
        output.append(str(value))
    return output


def extract_urls(text):
    return dedupe(match.rstrip(".,)") for match in URL_PATTERN.findall(text or ""))


def extract_emails(text):
    return dedupe(EMAIL_PATTERN.findall(text or ""))


def extract_phone_candidates(text):
    candidates = []
    for match in PHONE_PATTERN.findall(text or ""):
        cleaned = normalize_whitespace(match)
        digits = re.sub(r"\D", "", cleaned)
        if 7 <= len(digits) <= 15:
            candidates.append(cleaned)
    return dedupe(candidates)


def extract_coordinates(text):
    output = []
    for match in COORD_PATTERN.finditer(text or ""):
        lat = float(match.group("lat"))
        lng = float(match.group("lng"))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            output.append(f"{lat:.6f}, {lng:.6f}")
    return dedupe(output)


def extract_mac_addresses(text):
    return dedupe(match.upper() for match in MAC_PATTERN.findall(text or ""))


def extract_handle_candidates(text):
    handles = [match.group("handle") for match in HANDLE_PATTERN.finditer(text or "")]
    generic = []
    for token in GENERIC_USERNAME_PATTERN.findall(text or ""):
        lowered = token.lower()
        if lowered in COMMON_WORDS:
            continue
        if token.startswith("http"):
            continue
        if re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", token):
            continue
        if (
            any(char.isdigit() for char in token)
            or "_" in token
            or "-" in token
            or "." in token
        ):
            generic.append(token)
    return dedupe(handles + generic)


def extract_domains(urls, emails):
    domains = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.netloc:
            domains.append(parsed.netloc.lower())
    for email in emails:
        if "@" in email:
            domains.append(email.rsplit("@", 1)[1].lower())
    return dedupe(domains)


def collect_entities(texts):
    combined = "\n".join(texts)
    urls = extract_urls(combined)
    emails = extract_emails(combined)
    phones = extract_phone_candidates(combined)
    coordinates = extract_coordinates(combined)
    mac_addresses = extract_mac_addresses(combined)
    handles = extract_handle_candidates(combined)
    domains = extract_domains(urls, emails)
    return {
        "urls": urls,
        "emails": emails,
        "phones": phones,
        "coordinates": coordinates,
        "mac_addresses": mac_addresses,
        "handles": handles,
        "domains": domains,
    }


def safe_json_loads(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def parse_flag_format(text):
    lines = []
    for line in (text or "").splitlines():
        if "flag format" in line.lower() or "answer format" in line.lower():
            lines.append(normalize_whitespace(line))
    return dedupe(lines)
