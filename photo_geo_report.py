#!/usr/bin/env python3
import argparse
import json
import sys

from exif_vision import analyze_image, dedupe, normalize_whitespace
from gemini_maps_enrich import enrich_with_maps


DEFAULT_MAPS_QUERY = "Describe nearby places, restaurants, POIs and current conditions within 15-minute walk"


def format_coordinates(lat, lng):
    if lat is None or lng is None:
        return "[unknown, unknown]"
    return f"[{lat:.6f}, {lng:.6f}]"


def best_guess_payload(analysis):
    vision = analysis.get("vision") if isinstance(analysis, dict) else {}
    if not isinstance(vision, dict):
        return {}
    best_guess = vision.get("best_guess")
    return best_guess if isinstance(best_guess, dict) else {}


def best_guess_text(analysis):
    best_guess = best_guess_payload(analysis)
    parts = [
        best_guess.get("location_name"),
        best_guess.get("city"),
        best_guess.get("region"),
        best_guess.get("country"),
    ]
    return ", ".join(part for part in parts if part)


def resolve_coordinates(analysis, user_lat=None, user_lng=None):
    extracted = analysis.get("coordinates") if isinstance(analysis, dict) else None
    if isinstance(extracted, dict):
        lat = extracted.get("lat")
        lng = extracted.get("lng")
        source = extracted.get("source", "unknown")
        if lat is not None and lng is not None:
            return lat, lng, source

    if user_lat is not None and user_lng is not None:
        return user_lat, user_lng, "user"

    return None, None, "unknown"


def derive_city_fallback(analysis, user_city=""):
    if user_city:
        return user_city
    guess_text = best_guess_text(analysis)
    return guess_text


def normalize_list(values, limit=5):
    if not isinstance(values, list):
        return []
    return dedupe(values)[:limit]


def background_bullets(analysis):
    bullets = []
    input_details = analysis.get("input_details") if isinstance(analysis, dict) else {}
    if isinstance(input_details, dict):
        mime_type = input_details.get("mime_type")
        size_bytes = input_details.get("size_bytes")
        validation_warning = normalize_whitespace(
            input_details.get("validation_warning", "")
        )
        details = []
        if mime_type:
            details.append(f"mime `{mime_type}`")
        if size_bytes is not None:
            details.append(f"size {size_bytes} bytes")
        if details:
            bullets.append(f"Input verified as image ({', '.join(details)})")
        if validation_warning:
            bullets.append(validation_warning)

    ocr_terms = normalize_list(analysis.get("ocr_terms"), limit=6)
    if ocr_terms:
        bullets.append(f"OCR pivots: {', '.join(ocr_terms)}")

    vision = analysis.get("vision") if isinstance(analysis, dict) else {}
    if isinstance(vision, dict):
        landmarks = normalize_list(vision.get("landmarks"), limit=4)
        if landmarks:
            bullets.append(f"Visible landmarks or place cues: {', '.join(landmarks)}")

        visible_text = normalize_list(vision.get("visible_text"), limit=4)
        if visible_text:
            bullets.append(f"Visible text cues: {', '.join(visible_text)}")

        guess = best_guess_text(analysis)
        if guess:
            reason = normalize_whitespace(
                best_guess_payload(analysis).get("reason", "")
            )
            bullet = f"Vision location hypothesis: {guess}"
            if reason:
                bullet += f" ({reason})"
            bullets.append(bullet)

    suggested_queries = normalize_list(analysis.get("suggested_web_queries"), limit=6)
    if suggested_queries:
        bullets.append(f"Suggested search pivots: {' | '.join(suggested_queries)}")

    return bullets or ["No strong OCR or landmark pivots extracted."]


def build_markdown_report(analysis, maps_result, lat, lng, coordinate_source):
    confidence = analysis.get("confidence", "Medium")
    maps_answer = "No Google Maps enrichment available."
    maps_sources = []

    if isinstance(maps_result, dict):
        if maps_result.get("answer"):
            maps_answer = maps_result["answer"]
        elif maps_result.get("error"):
            maps_answer = maps_result["error"]
        maps_sources = (
            maps_result.get("sources")
            if isinstance(maps_result.get("sources"), list)
            else []
        )

    source_lines = maps_sources or ["- None"]
    osint_lines = [f"- {bullet}" for bullet in background_bullets(analysis)]

    return "\n".join(
        [
            f"📍 Coordinates: {format_coordinates(lat, lng)} (source: {coordinate_source})",
            f"Confidence: {confidence}",
            "Gemini Maps Enrichment:",
            maps_answer,
            "Sources from Google Maps:",
            *source_lines,
            "Exa Background OSINT:",
            *osint_lines,
            "Full report ready.",
        ]
    )


def generate_report(
    input_value,
    use_vision,
    query,
    user_lat=None,
    user_lng=None,
    user_city="",
):
    analysis = analyze_image(input_value, use_vision)
    if analysis.get("error"):
        return {"error": analysis["error"], "analysis": analysis}

    lat, lng, coordinate_source = resolve_coordinates(
        analysis,
        user_lat=user_lat,
        user_lng=user_lng,
    )
    city_fallback = derive_city_fallback(analysis, user_city)

    maps_result = None
    if lat is not None and lng is not None:
        maps_result = enrich_with_maps(lat=lat, lng=lng, query=query)
    elif city_fallback:
        maps_result = enrich_with_maps(city_fallback=city_fallback, query=query)

    markdown = build_markdown_report(
        analysis,
        maps_result,
        lat,
        lng,
        coordinate_source,
    )
    return {
        "analysis": analysis,
        "maps": maps_result,
        "coordinates": {
            "lat": lat,
            "lng": lng,
            "source": coordinate_source,
        },
        "city_fallback": city_fallback,
        "markdown": markdown,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate a structured PhotoGeoOSINT report from one command."
    )
    parser.add_argument(
        "--input", required=True, help="Linux path, Windows path, or image URL"
    )
    parser.add_argument(
        "--vision", action="store_true", help="Use Gemini vision when GPS is missing"
    )
    parser.add_argument(
        "--lat", type=float, default=None, help="User-supplied latitude override"
    )
    parser.add_argument(
        "--lng", type=float, default=None, help="User-supplied longitude override"
    )
    parser.add_argument(
        "--city", default="", help="User-supplied city or area fallback"
    )
    parser.add_argument(
        "--query", default=DEFAULT_MAPS_QUERY, help="Google Maps grounding prompt"
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format",
    )
    args = parser.parse_args()

    try:
        report = generate_report(
            args.input,
            args.vision,
            args.query,
            user_lat=args.lat,
            user_lng=args.lng,
            user_city=args.city,
        )
    except Exception as exc:
        report = {"error": str(exc), "input": args.input}

    if (
        args.format == "markdown"
        and isinstance(report, dict)
        and report.get("markdown")
    ):
        sys.stdout.write(report["markdown"] + "\n")
        return

    json.dump(report, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
