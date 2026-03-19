#!/usr/bin/env python3
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

from osint_common import dedupe, normalize_whitespace, safe_json_loads


def available_tools():
    return {
        "maigret": shutil.which("maigret"),
        "sherlock": shutil.which("sherlock"),
    }


def generate_variants(username):
    cleaned = normalize_whitespace(username)
    variants = [cleaned, cleaned.lower()]
    if " " in cleaned:
        variants.extend(
            [
                cleaned.replace(" ", "_"),
                cleaned.replace(" ", "-"),
                cleaned.replace(" ", "."),
                cleaned.replace(" ", ""),
            ]
        )
    if "_" in cleaned:
        variants.extend(
            [
                cleaned.replace("_", "-"),
                cleaned.replace("_", "."),
                cleaned.replace("_", ""),
            ]
        )
    if "-" in cleaned:
        variants.extend(
            [
                cleaned.replace("-", "_"),
                cleaned.replace("-", "."),
                cleaned.replace("-", ""),
            ]
        )
    if "." in cleaned:
        variants.extend(
            [
                cleaned.replace(".", "_"),
                cleaned.replace(".", "-"),
                cleaned.replace(".", ""),
            ]
        )
    return dedupe(variants)


def recursive_urls(value):
    output = []
    if isinstance(value, dict):
        for nested in value.values():
            output.extend(recursive_urls(nested))
    elif isinstance(value, list):
        for nested in value:
            output.extend(recursive_urls(nested))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        output.append(value)
    return dedupe(output)


def parse_sherlock_stdout(stdout):
    findings = []
    for line in stdout.splitlines():
        cleaned = line.strip()
        if not cleaned.startswith("[+"):
            continue
        if ": http" not in cleaned:
            continue
        _, remainder = cleaned.split("]", 1)
        site, url = remainder.split(":", 1)
        findings.append(
            {
                "site": normalize_whitespace(site),
                "url": url.strip(),
            }
        )
    return findings


def run_maigret(username, tags="", timeout=20, all_sites=False, top_sites=500):
    workdir = tempfile.mkdtemp(prefix="maigret_lookup_")
    try:
        command = [
            "maigret",
            username,
            "--json",
            "simple",
            "--folderoutput",
            workdir,
            "--timeout",
            str(timeout),
            "--no-color",
        ]
        if all_sites:
            command.append("-a")
        elif top_sites and int(top_sites) != 500:
            command.extend(["--top-sites", str(top_sites)])
        if tags:
            command.extend(["--tags", tags])

        result = subprocess.run(command, capture_output=True, text=True, check=False)
        report_files = sorted(
            glob.glob(os.path.join(workdir, "**", "*.json"), recursive=True)
        )
        reports = []
        urls = []
        for report_file in report_files:
            with open(report_file, "r", encoding="utf-8", errors="replace") as handle:
                loaded = safe_json_loads(handle.read())
            if loaded is None:
                continue
            reports.append(loaded)
            urls.extend(recursive_urls(loaded))

        return {
            "tool": "maigret",
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "report_files": report_files,
            "reports": reports,
            "profile_urls": dedupe(urls),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_sherlock(username, timeout=20):
    command = [
        "sherlock",
        username,
        "--print-found",
        "--no-color",
        "--timeout",
        str(timeout),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    findings = parse_sherlock_stdout(result.stdout)
    return {
        "tool": "sherlock",
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "findings": findings,
        "profile_urls": dedupe([item["url"] for item in findings]),
    }


def choose_tool(preferred):
    tools = available_tools()
    if preferred in {"maigret", "sherlock"}:
        if tools.get(preferred):
            return preferred, tools
        return None, tools
    for candidate in ["maigret", "sherlock"]:
        if tools.get(candidate):
            return candidate, tools
    return None, tools


def lookup_username(
    username,
    preferred_tool="auto",
    tags="",
    timeout=20,
    all_sites=False,
    top_sites=500,
    search_variants=False,
):
    tool_name, tools = choose_tool(preferred_tool)
    if tool_name is None:
        return {
            "error": "No free username lookup tool detected. Install `maigret` or `sherlock` on Ubuntu/WSL.",
            "available_tools": tools,
            "username": username,
        }

    variants = generate_variants(username)
    targets = variants if search_variants else variants[:1]
    results = []
    for target in targets:
        if tool_name == "maigret":
            result = run_maigret(
                target,
                tags=tags,
                timeout=timeout,
                all_sites=all_sites,
                top_sites=top_sites,
            )
        else:
            result = run_sherlock(target, timeout=timeout)
        result["queried_username"] = target
        results.append(result)

    combined_urls = []
    for result in results:
        combined_urls.extend(result.get("profile_urls", []))

    return {
        "username": username,
        "suggested_variants": variants,
        "queried_usernames": targets,
        "selected_tool": tool_name,
        "available_tools": tools,
        "results": results,
        "profile_urls": dedupe(combined_urls),
        "install_hint": "Free/local-first options: `pip install maigret sherlock-project` or distro packages if available.",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Free local-first username lookup with Maigret or Sherlock."
    )
    parser.add_argument(
        "--username", required=True, help="Username or handle to investigate"
    )
    parser.add_argument(
        "--tool",
        choices=["auto", "maigret", "sherlock"],
        default="auto",
        help="Preferred lookup tool",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Optional Maigret tags such as photo,us,coding",
    )
    parser.add_argument(
        "--timeout", type=int, default=20, help="Per-request timeout in seconds"
    )
    parser.add_argument(
        "--all-sites",
        action="store_true",
        help="Use all Maigret sites instead of the default ranked subset",
    )
    parser.add_argument(
        "--top-sites",
        type=int,
        default=500,
        help="Maigret top sites count when not using --all-sites",
    )
    parser.add_argument(
        "--search-variants",
        action="store_true",
        help="Search generated username variants as well as the exact value",
    )
    args = parser.parse_args()

    result = lookup_username(
        args.username,
        preferred_tool=args.tool,
        tags=args.tags,
        timeout=args.timeout,
        all_sites=args.all_sites,
        top_sites=args.top_sites,
        search_variants=args.search_variants,
    )
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
