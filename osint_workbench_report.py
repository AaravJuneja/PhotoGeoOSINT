#!/usr/bin/env python3
import argparse
import json
import mimetypes
import os
import sys

from osint_artifact_extract import extract_artifact
from osint_barcode_extract import extract_barcodes
from osint_challenge_context import parse_context
from osint_common import dedupe, normalize_whitespace
from osint_domain_probe import probe_domains
from osint_email_phone_probe import probe_identifiers
from osint_text_extract import extract_text_pivots
from osint_username_lookup import lookup_username
from osint_wifi_probe import probe_wifi
from photo_geo_report import generate_report


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".svg",
}


def looks_like_image(input_value):
    lowered = input_value.lower().split("?", 1)[0]
    _, extension = os.path.splitext(lowered)
    if extension in IMAGE_EXTENSIONS:
        return True
    mime_type, _ = mimetypes.guess_type(lowered)
    return bool(mime_type and mime_type.startswith("image/"))


def call_safe(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        return {"error": str(exc)}


def summarize_photo_lead(photo_result):
    if not isinstance(photo_result, dict):
        return "No photo result available."
    coordinates = photo_result.get("coordinates") or {}
    lat = coordinates.get("lat")
    lng = coordinates.get("lng")
    source = coordinates.get("source", "unknown")
    if lat is not None and lng is not None:
        return f"Image pipeline found candidate coordinates {lat:.6f}, {lng:.6f} from {source}."
    analysis = photo_result.get("analysis") or {}
    vision = analysis.get("vision") if isinstance(analysis, dict) else {}
    if isinstance(vision, dict):
        best_guess = vision.get("best_guess")
        if isinstance(best_guess, dict):
            parts = [
                best_guess.get("location_name"),
                best_guess.get("city"),
                best_guess.get("region"),
                best_guess.get("country"),
            ]
            guess = ", ".join(part for part in parts if part)
            if guess:
                return f"Image pipeline produced a location hypothesis: {guess}."
    return "Image pipeline extracted clues but no confirmed coordinates yet."


def summarize_username_lead(username_result):
    if not isinstance(username_result, dict) or username_result.get("error"):
        return "Username lookup did not produce a confirmed cross-platform hit yet."
    urls = username_result.get("profile_urls") or []
    if urls:
        return f"Username lookup found {len(urls)} profile candidate(s) for the strongest handle."
    return "Username lookup ran, but no profile URLs were confirmed."


def strongest_primary_lead(results):
    if results.get("photo") and not (results["photo"] or {}).get("error"):
        summary = summarize_photo_lead(results["photo"])
        if "candidate coordinates" in summary or "location hypothesis" in summary:
            return summary
    if results.get("username") and not (results["username"] or {}).get("error"):
        summary = summarize_username_lead(results["username"])
        if "found" in summary:
            return summary
    if results.get("artifact") and not (results["artifact"] or {}).get("error"):
        usernames = (results["artifact"] or {}).get("candidate_usernames") or []
        emails = ((results["artifact"] or {}).get("entities") or {}).get("emails") or []
        if usernames or emails:
            return (
                "Artifact extraction exposed reusable identifiers and metadata pivots."
            )
    if results.get("text") and not (results["text"] or {}).get("error"):
        entities = (results["text"] or {}).get("entities") or {}
        if any(entities.get(key) for key in ["handles", "emails", "phones", "urls"]):
            return "Raw challenge text exposed structured pivots worth following immediately."
    if results.get("domain") and ((results["domain"] or {}).get("domains") or []):
        return "Domain probing exposed infrastructure pivots that can extend the investigation."
    if results.get("wifi") and (
        (results["wifi"] or {}).get("ssids") or (results["wifi"] or {}).get("bssids")
    ):
        return "Wi-Fi artifacts exposed SSID or BSSID pivots that can anchor the next OSINT step."
    return "No single definitive answer yet, but the workbench extracted actionable pivots to keep the OSINT chain moving."


def evidence_lines(results):
    evidence = []
    if results.get("challenge_context"):
        context = results["challenge_context"]
        if context.get("error"):
            evidence.append(f"Challenge parsing error: {context['error']}")
        else:
            modules = context.get("recommended_modules") or []
            if modules:
                evidence.append(f"Challenge parser recommends: {', '.join(modules)}")
            formats = context.get("flag_format_hints") or []
            if formats:
                evidence.append(f"Flag/answer format hints: {' | '.join(formats)}")
    if results.get("text"):
        if (results["text"] or {}).get("error"):
            evidence.append(f"Text extraction error: {results['text']['error']}")
        entities = (results["text"] or {}).get("entities") or {}
        for key in ["handles", "emails", "phones", "urls", "mac_addresses"]:
            values = entities.get(key) or []
            if values:
                evidence.append(f"Text entities {key}: {', '.join(values[:6])}")
    if results.get("artifact"):
        artifact = results["artifact"] or {}
        if artifact.get("error"):
            evidence.append(f"Artifact extraction error: {artifact['error']}")
        usernames = artifact.get("candidate_usernames") or []
        if usernames:
            evidence.append(f"Artifact usernames: {', '.join(usernames[:8])}")
        entities = artifact.get("entities") or {}
        if entities.get("emails"):
            evidence.append(f"Artifact emails: {', '.join(entities['emails'][:6])}")
        if entities.get("coordinates"):
            evidence.append(
                f"Artifact coordinates: {', '.join(entities['coordinates'][:4])}"
            )
    if results.get("barcode"):
        if (results["barcode"] or {}).get("error"):
            evidence.append(f"Barcode extraction error: {results['barcode']['error']}")
        decoded = (results["barcode"] or {}).get("decoded_items") or []
        if decoded:
            payloads = [
                item.get("payload", "") for item in decoded[:4] if item.get("payload")
            ]
            if payloads:
                evidence.append(f"Barcode payloads: {' | '.join(payloads)}")
    if results.get("photo"):
        evidence.append(summarize_photo_lead(results["photo"]))
    if results.get("username"):
        if (results["username"] or {}).get("error"):
            evidence.append(f"Username lookup error: {results['username']['error']}")
        else:
            evidence.append(summarize_username_lead(results["username"]))
    if results.get("identity"):
        identity = results["identity"] or {}
        if identity.get("error"):
            evidence.append(f"Identity probe error: {identity['error']}")
        if identity.get("email_count"):
            evidence.append(f"Email probe count: {identity['email_count']}")
        if identity.get("phone_count"):
            evidence.append(f"Phone probe count: {identity['phone_count']}")
    if results.get("domain"):
        domain_result = results["domain"] or {}
        if domain_result.get("error"):
            evidence.append(f"Domain probe error: {domain_result['error']}")
        domains = domain_result.get("domains") or []
        if domains:
            names = [
                item.get("domain", "")
                for item in domains
                if isinstance(item, dict) and item.get("domain")
            ]
            if names:
                evidence.append(f"Domain pivots: {', '.join(names[:6])}")
    if results.get("wifi"):
        wifi_result = results["wifi"] or {}
        if wifi_result.get("error"):
            evidence.append(f"Wi-Fi probe error: {wifi_result['error']}")
        ssids = wifi_result.get("ssids") or []
        bssids = wifi_result.get("bssids") or []
        if ssids:
            evidence.append(f"SSID pivots: {', '.join(ssids[:6])}")
        if bssids:
            formatted = [
                item.get("bssid", "")
                for item in bssids
                if isinstance(item, dict) and item.get("bssid")
            ]
            if formatted:
                evidence.append(f"BSSID pivots: {', '.join(formatted[:6])}")
    return dedupe(item for item in evidence if item)


def pivot_lines(results):
    pivots = []
    if results.get("challenge_context"):
        pivots.extend((results["challenge_context"] or {}).get("search_pivots") or [])
    if results.get("text"):
        pivots.extend((results["text"] or {}).get("search_pivots") or [])
    if results.get("artifact"):
        pivots.extend((results["artifact"] or {}).get("suggested_pivots") or [])
    if results.get("identity"):
        pivots.extend((results["identity"] or {}).get("search_pivots") or [])
    if results.get("domain"):
        pivots.extend((results["domain"] or {}).get("search_pivots") or [])
    if results.get("wifi"):
        pivots.extend((results["wifi"] or {}).get("search_pivots") or [])
    if results.get("username"):
        pivots.extend((results["username"] or {}).get("suggested_variants") or [])
        pivots.extend((results["username"] or {}).get("profile_urls") or [])
    if results.get("photo"):
        photo = results["photo"] or {}
        analysis = photo.get("analysis") or {}
        pivots.extend(analysis.get("suggested_web_queries") or [])
    return dedupe(item for item in pivots if item)[:16]


def next_actions(results):
    actions = []
    if results.get("photo"):
        photo = results["photo"] or {}
        coordinates = photo.get("coordinates") or {}
        if coordinates.get("lat") is None or coordinates.get("lng") is None:
            actions.append(
                "Use the strongest OCR or landmark pivot from the image in focused web search or username pivots."
            )
        else:
            actions.append(
                "Validate the mapped area against challenge wording such as nearest, exact, or business-email requirements."
            )
    if results.get("username"):
        username = results["username"] or {}
        if username.get("profile_urls"):
            actions.append(
                "Review the highest-confidence profile URLs for linked emails, domains, and secondary handles."
            )
    if results.get("artifact"):
        artifact = results["artifact"] or {}
        if artifact.get("candidate_usernames"):
            actions.append(
                "Run deeper username pivots on the artifact-derived handles if the first lookup is sparse."
            )
    if results.get("barcode"):
        barcode = results["barcode"] or {}
        if barcode.get("decoded_items"):
            actions.append(
                "Follow the decoded QR or barcode payloads as first-class pivots before broader searching."
            )
    if results.get("identity"):
        identity = results["identity"] or {}
        if identity.get("email_count") or identity.get("phone_count"):
            actions.append(
                "Correlate the normalized email or phone outputs with usernames, domains, and challenge answer format hints."
            )
    if results.get("domain"):
        domain_result = results["domain"] or {}
        if domain_result.get("domains"):
            actions.append(
                "Use DNS, SSL, and WHOIS findings to pivot into subdomains, registrars, and related infrastructure."
            )
    if results.get("wifi"):
        wifi_result = results["wifi"] or {}
        if wifi_result.get("bssids") or wifi_result.get("ssids"):
            actions.append(
                "Pivot on SSID and BSSID values to correlate vendors, hotspots, and nearby-location clues."
            )
    if not actions:
        actions.append(
            "Start with the strongest search pivot from the extracted evidence and validate one branch at a time."
        )
    return dedupe(actions)[:6]


def candidate_handles(results, explicit_username=""):
    handles = []
    if explicit_username:
        handles.append(explicit_username)
    text_entities = ((results.get("text") or {}).get("entities") or {}).get(
        "handles"
    ) or []
    artifact_entities = (results.get("artifact") or {}).get("candidate_usernames") or []
    identity_pivots = []
    for report in (results.get("identity") or {}).get("emails") or []:
        identity_pivots.extend(
            (report.get("summary") or {}).get("local_part_variants") or []
        )
    handles.extend(text_entities)
    handles.extend(artifact_entities)
    handles.extend(identity_pivots)
    return dedupe(handles)


def candidate_domain_text(results, effective_text=""):
    parts = []
    if effective_text:
        parts.append(effective_text)
    artifact_entities = (results.get("artifact") or {}).get("entities") or {}
    parts.extend(artifact_entities.get("urls", []))
    parts.extend(artifact_entities.get("emails", []))
    identity = results.get("identity") or {}
    for report in (
        identity.get("emails", []) if isinstance(identity.get("emails"), list) else []
    ):
        if not isinstance(report, dict):
            continue
        summary = report.get("summary", {})
        if isinstance(summary, dict):
            parts.append(summary.get("email", ""))
            parts.append(summary.get("domain", ""))
    barcode = results.get("barcode") or {}
    for item in (
        barcode.get("decoded_items", [])
        if isinstance(barcode.get("decoded_items"), list)
        else []
    ):
        if not isinstance(item, dict):
            continue
        normalized = item.get("normalized", {})
        if isinstance(normalized, dict):
            parts.append(normalized.get("url", ""))
            parts.append(normalized.get("domain", ""))
    return "\n".join(part for part in parts if part)


def candidate_wifi_text(results, effective_text=""):
    parts = []
    if effective_text:
        parts.append(effective_text)
    artifact_entities = (results.get("artifact") or {}).get("entities") or {}
    parts.extend(artifact_entities.get("mac_addresses", []))
    barcode = results.get("barcode") or {}
    for item in (
        barcode.get("decoded_items", [])
        if isinstance(barcode.get("decoded_items"), list)
        else []
    ):
        if not isinstance(item, dict):
            continue
        payload = item.get("payload", "")
        if payload:
            parts.append(payload)
    return "\n".join(part for part in parts if part)


def generate_workbench_report(
    input_value="",
    text="",
    username="",
    challenge_name="",
    challenge_description="",
    use_grok=False,
):
    results = {}

    if challenge_name or challenge_description:
        results["challenge_context"] = call_safe(
            parse_context, challenge_name, challenge_description
        )

    effective_text = "\n".join(
        part for part in [text, challenge_description, challenge_name] if part
    )
    if effective_text:
        results["text"] = call_safe(
            extract_text_pivots, effective_text, challenge_name=challenge_name
        )
        results["identity"] = call_safe(probe_identifiers, text=effective_text)

    if input_value:
        if looks_like_image(input_value):
            results["photo"] = call_safe(
                generate_report,
                input_value,
                True,
                "Describe nearby places, restaurants, POIs and current conditions within 15-minute walk",
                challenge_name=challenge_name,
                challenge_description=challenge_description,
                use_grok=use_grok,
            )
            results["barcode"] = call_safe(extract_barcodes, input_value)
        else:
            results["artifact"] = call_safe(extract_artifact, input_value)
            artifact_result = (
                results["artifact"] if isinstance(results.get("artifact"), dict) else {}
            )
            artifact_entities_raw = artifact_result.get("entities") or {}
            artifact_entities = (
                artifact_entities_raw if isinstance(artifact_entities_raw, dict) else {}
            )
            artifact_text = "\n".join(
                artifact_entities.get("emails", [])
                + artifact_entities.get("phones", [])
                + artifact_entities.get("urls", [])
                + artifact_entities.get("coordinates", [])
            )
            if artifact_text:
                identity = call_safe(probe_identifiers, text=artifact_text)
                existing_identity = (
                    results.get("identity")
                    if isinstance(results.get("identity"), dict)
                    else None
                )
                if existing_identity:
                    if not existing_identity.get("error") and not identity.get("error"):
                        existing_emails = list(existing_identity.get("emails", []))
                        existing_phones = list(existing_identity.get("phones", []))
                        existing_emails.extend(identity.get("emails", []))
                        existing_phones.extend(identity.get("phones", []))
                        existing_identity["emails"] = existing_emails
                        existing_identity["phones"] = existing_phones
                        existing_identity["search_pivots"] = dedupe(
                            list(existing_identity.get("search_pivots", []))
                            + list(identity.get("search_pivots", []))
                        )
                        existing_identity["email_count"] = len(existing_emails)
                        existing_identity["phone_count"] = len(existing_phones)
                    elif existing_identity.get("error"):
                        results["identity"] = identity
                else:
                    results["identity"] = identity

    domain_text = candidate_domain_text(results, effective_text=effective_text)
    if domain_text:
        results["domain"] = call_safe(probe_domains, text=domain_text)

    wifi_text = candidate_wifi_text(results, effective_text=effective_text)
    if wifi_text:
        results["wifi"] = call_safe(probe_wifi, text=wifi_text)

    handle_candidates = candidate_handles(results, explicit_username=username)
    if handle_candidates:
        results["username"] = call_safe(
            lookup_username,
            handle_candidates[0],
            preferred_tool="auto",
            search_variants=True,
        )

    markdown = "\n".join(
        [
            "Primary lead:",
            strongest_primary_lead(results),
            "Evidence:",
            *[f"- {item}" for item in evidence_lines(results)],
            "Pivots:",
            *[f"- {item}" for item in pivot_lines(results)],
            "Next best action:",
            *[f"- {item}" for item in next_actions(results)],
        ]
    )

    return {
        "input": input_value,
        "text": text,
        "username": username,
        "challenge_name": challenge_name,
        "challenge_description": challenge_description,
        "results": results,
        "markdown": markdown,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate a combined OSINT challenge report from photo, file, text, and identity pivots."
    )
    parser.add_argument(
        "--input", default="", help="Optional path, Windows path, or URL"
    )
    parser.add_argument("--text", default="", help="Optional raw clue text")
    parser.add_argument(
        "--username", default="", help="Optional known username or handle"
    )
    parser.add_argument("--challenge-name", default="", help="Optional challenge name")
    parser.add_argument(
        "--challenge-description", default="", help="Optional challenge description"
    )
    parser.add_argument(
        "--use-grok",
        action="store_true",
        help="Optionally run Grok within the photo pipeline when configured",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format",
    )
    args = parser.parse_args()

    report = generate_workbench_report(
        input_value=args.input,
        text=args.text,
        username=args.username,
        challenge_name=args.challenge_name,
        challenge_description=args.challenge_description,
        use_grok=args.use_grok,
    )

    if args.format == "markdown":
        sys.stdout.write(report["markdown"] + "\n")
        return
    json.dump(report, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
