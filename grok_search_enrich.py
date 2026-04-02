#!/usr/bin/env python3
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from osint_common import normalize_whitespace


def extract_text(response_json):
    output = response_json.get("output") if isinstance(response_json, dict) else []
    parts = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if not isinstance(content, dict):
                        continue
                    text = content.get("text")
                    if text:
                        parts.append(text)
            elif item.get("type") in {"output_text", "text"} and item.get("text"):
                parts.append(item["text"])
    return "\n".join(part.strip() for part in parts if part and part.strip())


def grok_enrich(
    prompt,
    challenge_name="",
    challenge_description="",
    enable_x_search=True,
    enable_image_understanding=True,
):
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        return {"error": "Set XAI_API_KEY environment variable"}

    model = os.getenv("PHOTO_GEO_GROK_MODEL", "grok-4.20-beta-latest-non-reasoning")
    prompt_parts = [prompt]
    if challenge_name:
        prompt_parts.append(f"CTF challenge name: {challenge_name}")
    if challenge_description:
        prompt_parts.append(f"CTF challenge description: {challenge_description}")
    final_prompt = "\n".join(part for part in prompt_parts if part)

    tools = [
        {
            "type": "web_search",
            "enable_image_understanding": bool(enable_image_understanding),
        }
    ]
    if enable_x_search:
        tools.append(
            {
                "type": "x_search",
                "enable_image_understanding": bool(enable_image_understanding),
            }
        )

    payload = {
        "model": model,
        "include": ["no_inline_citations"],
        "input": [{"role": "user", "content": final_prompt}],
        "tools": tools,
    }

    request = Request(
        "https://api.x.ai/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        return {"error": f"xAI request failed: {exc.code} {message}"}
    except URLError as exc:
        return {"error": f"xAI request failed: {exc.reason}"}

    return {
        "answer": normalize_whitespace(extract_text(data)),
        "sources": data.get("citations", [])
        if isinstance(data.get("citations"), list)
        else [],
        "model": model,
        "challenge_name": challenge_name,
        "challenge_description": challenge_description,
        "raw": data,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Optional Grok/xAI web and X search enrichment for PhotoGeoOSINT."
    )
    parser.add_argument("--prompt", required=True, help="Research prompt for Grok")
    parser.add_argument(
        "--challenge-name", default="", help="Optional CTF challenge name"
    )
    parser.add_argument(
        "--challenge-description", default="", help="Optional CTF challenge description"
    )
    parser.add_argument(
        "--disable-x-search",
        action="store_true",
        help="Disable X search and only use web search",
    )
    parser.add_argument(
        "--disable-image-understanding",
        action="store_true",
        help="Disable image understanding in Grok tools",
    )
    args = parser.parse_args()

    result = grok_enrich(
        args.prompt,
        challenge_name=args.challenge_name,
        challenge_description=args.challenge_description,
        enable_x_search=not args.disable_x_search,
        enable_image_understanding=not args.disable_image_understanding,
    )
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
