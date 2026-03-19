#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

try:
    from PIL import ExifTags, Image
except ImportError:
    ExifTags = None
    Image = None

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


GPS_INFO_TAG = 34853


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
    return guessed or ".img"


def resolve_input(input_value):
    raw = input_value.strip().strip('"').strip("'")
    cleanup_path = None

    if raw.startswith("file://"):
        raw = unquote(urlparse(raw).path)

    if is_url(raw):
        request = Request(raw, headers={"User-Agent": "PhotoGeoOSINT/1.0"})
        with urlopen(request, timeout=60) as response:
            content = response.read()
            suffix = guess_suffix(raw, response.headers.get("Content-Type", ""))
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.write(content)
        handle.flush()
        handle.close()
        cleanup_path = handle.name
        return handle.name, "url", cleanup_path

    if is_windows_path(raw):
        raw = wsl_path(raw)
        input_type = "windows_path"
    else:
        input_type = "path"

    resolved = os.path.abspath(os.path.expanduser(raw))
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Image not found: {resolved}")
    return resolved, input_type, cleanup_path


def safe_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("deg", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def exiftool_extract(image_path):
    if not shutil.which("exiftool"):
        return None
    command = [
        "exiftool",
        "-n",
        "-j",
        "-GPSLatitude",
        "-GPSLongitude",
        "-GPSAltitude",
        "-GPSImgDirection",
        "-Make",
        "-Model",
        "-DateTimeOriginal",
        "-CreateDate",
        image_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)[0]
    except Exception:
        return None
    lat = safe_float(payload.get("GPSLatitude"))
    lng = safe_float(payload.get("GPSLongitude"))
    if lat is None or lng is None:
        return {
            "lat": None,
            "lng": None,
            "source": "EXIF",
            "metadata": payload,
        }
    return {
        "lat": lat,
        "lng": lng,
        "source": "EXIF",
        "metadata": payload,
    }


def ratio_to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator or 1)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        numerator, denominator = value
        return float(numerator) / float(denominator or 1)
    return float(value)


def dms_to_decimal(dms, ref):
    if not dms:
        return None
    if isinstance(dms, (int, float)):
        decimal = float(dms)
    else:
        parts = list(dms)
        if len(parts) < 3:
            return None
        degrees, minutes, seconds = [ratio_to_float(part) for part in parts[:3]]
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if str(ref).upper() in {"S", "W"}:
        decimal *= -1
    return decimal


def pillow_extract(image_path):
    if Image is None:
        return None
    try:
        image = Image.open(image_path)
        exif = image.getexif()
        if not exif:
            return None
        gps_ifd = (
            exif.get_ifd(GPS_INFO_TAG)
            if hasattr(exif, "get_ifd")
            else exif.get(GPS_INFO_TAG)
        )
        if not gps_ifd:
            return None
        gps = {}
        for key, value in gps_ifd.items():
            tag_name = ExifTags.GPSTAGS.get(key, key) if ExifTags else key
            gps[tag_name] = value
        lat = dms_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef", "N"))
        lng = dms_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef", "E"))
        if lat is None or lng is None:
            return None
        return {
            "lat": lat,
            "lng": lng,
            "source": "Pillow",
            "metadata": gps,
        }
    except Exception:
        return None


def run_tesseract(image_path):
    if not shutil.which("tesseract"):
        return ""
    command = ["tesseract", image_path, "stdout", "--psm", "11"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    text = result.stdout.replace("\x0c", "\n")
    return text.strip()


def extract_ocr_terms(text, limit=8):
    cleaned_lines = []
    for line in text.splitlines():
        candidate = normalize_whitespace(re.sub(r"[^A-Za-z0-9&@#'./ -]+", " ", line))
        if len(candidate) < 3 or not any(char.isalpha() for char in candidate):
            continue
        cleaned_lines.append(candidate)

    token_candidates = re.findall(r"[A-Za-z0-9][A-Za-z0-9&@#'./-]{2,}", text)
    return dedupe(cleaned_lines + token_candidates)[:limit]


def guess_mime_type(image_path):
    mime_type, _ = mimetypes.guess_type(image_path)
    return mime_type or "image/jpeg"


def clean_json_text(text):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def parse_json_text(text):
    cleaned = clean_json_text(text)
    try:
        payload = json.loads(cleaned)
        return payload if isinstance(payload, dict) else {"raw": payload}
    except Exception:
        return {"raw": cleaned}


def describe_image(image_path, ocr_text):
    if genai is None or types is None:
        return {"available": False, "reason": "google-genai is not installed"}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"available": False, "reason": "GEMINI_API_KEY is not set"}

    with open(image_path, "rb") as handle:
        image_bytes = handle.read()

    prompt = (
        "You are a photo OSINT analyst. Analyze the image for geographic clues and return strict JSON with the keys "
        "summary, visible_text, landmarks, place_clues, location_candidates, best_guess, confidence, and search_terms. "
        "best_guess must be an object with city, region, country, location_name, and reason. "
        "search_terms must be a short array of distinctive web-searchable phrases."
    )
    if ocr_text:
        prompt += (
            f"\nOCR text already extracted: {normalize_whitespace(ocr_text)[:1200]}"
        )

    model = os.getenv("PHOTO_GEO_GEMINI_VISION_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)
    image_part = types.Part.from_bytes(
        data=image_bytes, mime_type=guess_mime_type(image_path)
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception:
        response = client.models.generate_content(
            model=model,
            contents=[prompt + " Return JSON only.", image_part],
            config=types.GenerateContentConfig(temperature=0.2),
        )

    data = parse_json_text(response.text or "")
    data["available"] = True
    data["model"] = model
    return data


def build_queries(ocr_terms, vision_data):
    queries = []
    best_guess = vision_data.get("best_guess") if isinstance(vision_data, dict) else {}
    best_guess = best_guess if isinstance(best_guess, dict) else {}
    location_context = " ".join(
        piece
        for piece in [
            best_guess.get("location_name"),
            best_guess.get("city"),
            best_guess.get("region"),
            best_guess.get("country"),
        ]
        if piece
    ).strip()

    landmarks = vision_data.get("landmarks") if isinstance(vision_data, dict) else []
    search_terms = (
        vision_data.get("search_terms") if isinstance(vision_data, dict) else []
    )
    visible_text = (
        vision_data.get("visible_text") if isinstance(vision_data, dict) else []
    )

    for landmark in landmarks[:3] if isinstance(landmarks, list) else []:
        queries.append(f'"{landmark}" {location_context}'.strip())

    for phrase in ocr_terms[:3]:
        queries.append(f'"{phrase}" {location_context}'.strip())
        queries.append(f'"{phrase}" location'.strip())

    for phrase in visible_text[:2] if isinstance(visible_text, list) else []:
        queries.append(f'"{phrase}" {location_context}'.strip())

    for term in search_terms[:3] if isinstance(search_terms, list) else []:
        queries.append(f"{term} {location_context}".strip())

    return dedupe(queries)[:8]


def analyze_image(input_value, use_vision):
    resolved_path, input_type, cleanup_path = resolve_input(input_value)
    try:
        exif = exiftool_extract(resolved_path)
        pillow = (
            None
            if exif and exif.get("lat") is not None
            else pillow_extract(resolved_path)
        )

        coordinates = None
        metadata_source = None
        metadata = None
        if exif and exif.get("lat") is not None and exif.get("lng") is not None:
            coordinates = {
                "lat": exif["lat"],
                "lng": exif["lng"],
                "source": exif["source"],
            }
            metadata_source = exif["source"]
            metadata = exif.get("metadata")
            confidence = "High"
        elif pillow:
            coordinates = {
                "lat": pillow["lat"],
                "lng": pillow["lng"],
                "source": pillow["source"],
            }
            metadata_source = pillow["source"]
            metadata = pillow.get("metadata")
            confidence = "High"
        else:
            confidence = "Medium"

        ocr_text = run_tesseract(resolved_path)
        ocr_terms = extract_ocr_terms(ocr_text)

        vision = {}
        if use_vision and coordinates is None:
            vision = describe_image(resolved_path, ocr_text)
            if isinstance(vision, dict):
                candidate_confidence = str(vision.get("confidence", "")).strip().lower()
                if candidate_confidence == "high":
                    confidence = "High"
                elif candidate_confidence == "low":
                    confidence = "Low"
                elif candidate_confidence:
                    confidence = candidate_confidence.capitalize()

        result = {
            "input": input_value,
            "resolved_path": resolved_path,
            "input_type": input_type,
            "coordinates": coordinates,
            "confidence": confidence,
            "metadata_source": metadata_source,
            "metadata": metadata,
            "ocr_text": ocr_text,
            "ocr_terms": ocr_terms,
            "vision": vision,
            "suggested_web_queries": build_queries(ocr_terms, vision),
        }
        return result
    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            os.remove(cleanup_path)


def main():
    parser = argparse.ArgumentParser(
        description="Extract EXIF, OCR, and vision clues from an image."
    )
    parser.add_argument(
        "--input", required=True, help="Linux path, Windows path, or image URL"
    )
    parser.add_argument(
        "--vision", action="store_true", help="Use Gemini vision when GPS is missing"
    )
    args = parser.parse_args()

    try:
        result = analyze_image(args.input, args.vision)
    except Exception as exc:
        result = {"error": str(exc), "input": args.input}

    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
