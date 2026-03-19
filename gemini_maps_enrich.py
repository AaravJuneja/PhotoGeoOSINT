#!/usr/bin/env python3
import argparse
import json
import os
import sys

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


def collect_source_indices(grounding):
    indices = set()
    for support in getattr(grounding, "grounding_supports", []) or []:
        for index in getattr(support, "grounding_chunk_indices", []) or []:
            indices.add(index)
    return indices


def collect_map_sources(response):
    sources = []
    widget_context_token = None
    try:
        grounding = getattr(response.candidates[0], "grounding_metadata", None)
        if grounding is None:
            return [], None
        widget_context_token = getattr(
            grounding, "google_maps_widget_context_token", None
        )
        source_indices = collect_source_indices(grounding)
        chunks = getattr(grounding, "grounding_chunks", []) or []

        for index, chunk in enumerate(chunks):
            if source_indices and index not in source_indices:
                continue
            maps = getattr(chunk, "maps", None)
            if not maps:
                continue
            title = getattr(maps, "title", None)
            uri = getattr(maps, "uri", None)
            if title and uri:
                sources.append(f"- [{title}]({uri})")
    except Exception:
        return [], None

    seen = set()
    unique_sources = []
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique_sources.append(source)
    return unique_sources, widget_context_token


def enrich_with_maps(
    lat=None,
    lng=None,
    city_fallback="",
    query="Describe nearby places, restaurants, POIs and current conditions within 15-minute walk",
    enable_widget=False,
):
    if genai is None or types is None:
        return {"error": "google-genai is not installed"}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"error": "Set GEMINI_API_KEY environment variable"}

    if lat is None or lng is None:
        lat = None
        lng = None
    if lat is None and not city_fallback:
        return {"error": "Provide lat/lng or a city fallback"}

    model = os.getenv("PHOTO_GEO_GEMINI_MAPS_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    try:
        maps_tool = types.Tool(
            google_maps=types.GoogleMaps(enable_widget=enable_widget)
        )
    except TypeError:
        maps_tool = types.Tool(google_maps=types.GoogleMaps())

    retrieval = None
    if lat is not None and lng is not None:
        retrieval = types.RetrievalConfig(
            lat_lng=types.LatLng(latitude=lat, longitude=lng)
        )

    prompt = (
        f"{query}\n"
        "Use only current Google Maps data. Include distances, hours, ratings, and identifying local context where possible."
    )
    if city_fallback:
        prompt += f"\nApproximate area: {city_fallback}"

    config = types.GenerateContentConfig(
        tools=[maps_tool],
        tool_config=types.ToolConfig(retrieval_config=retrieval) if retrieval else None,
        temperature=0.3,
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    sources, widget_context_token = collect_map_sources(response)
    return {
        "answer": (response.text or "").strip(),
        "sources": sources,
        "query": query,
        "coordinates": {"lat": lat, "lng": lng}
        if lat is not None and lng is not None
        else None,
        "city_fallback": city_fallback,
        "model": model,
        "widget_context_token": widget_context_token,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run Gemini Google Maps grounding for a location."
    )
    parser.add_argument("--lat", type=float, default=None, help="Latitude")
    parser.add_argument("--lng", type=float, default=None, help="Longitude")
    parser.add_argument("--city", default="", help="City or area fallback")
    parser.add_argument(
        "--query",
        default="Describe nearby places, restaurants, POIs and current conditions within 15-minute walk",
        help="Maps grounding prompt",
    )
    parser.add_argument(
        "--enable-widget",
        action="store_true",
        help="Request Google Maps widget context token",
    )
    args = parser.parse_args()

    result = enrich_with_maps(
        lat=args.lat,
        lng=args.lng,
        city_fallback=args.city,
        query=args.query,
        enable_widget=args.enable_widget,
    )
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
