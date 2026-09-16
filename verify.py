#!/usr/bin/env python3
"""
Verification Agent
==================
Picks a stratified sample of 20 apps (2 per category), re-researches them
with a more detailed prompt + extra page fetches, and compares findings
field-by-field against the first-pass results.

Uses Google Gemini (FREE).

Outputs data/verification.json with per-app and aggregate accuracy.

Usage:
    python verify.py                  # Verify 20-app sample
    python verify.py --sample 30      # Larger sample
    python verify.py --apps 1,5,21    # Verify specific app IDs
"""

from google import genai
from google.genai.types import GenerateContentConfig
import httpx
import json
import os
import sys
import time
import random
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

BASE_DIR = Path(__file__).parent
RESULTS_FILE = BASE_DIR / "data" / "results_final.json"
OUTPUT_FILE = BASE_DIR / "data" / "verification.json"

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_PAGE_CHARS = 15_000
DELAY = 5.0

api_key = os.getenv("GEMINI_API_KEY", "")
if not api_key:
    print("ERROR: Set GEMINI_API_KEY in your .env file.")
    sys.exit(1)

client = genai.Client(api_key=api_key)

http_client = httpx.Client(
    timeout=20.0,
    follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 (compatible; ComposioVerifier/1.0)"},
)

# ---------------------------------------------------------------------------
# Structured fields we compare (enum / boolean — exact match)
# ---------------------------------------------------------------------------
COMPARE_FIELDS = [
    "primary_auth",
    "self_serve",
    "api_type",
    "api_breadth",
    "buildability",
    "has_existing_mcp",
    "has_composio_integration",
]

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "app_name": {"type": "string"},
        "primary_auth": {"type": "string"},
        "all_auth_methods": {"type": "array", "items": {"type": "string"}},
        "self_serve": {"type": "string"},
        "self_serve_evidence": {"type": "string"},
        "api_type": {"type": "string"},
        "api_breadth": {"type": "string"},
        "has_existing_mcp": {"type": "boolean"},
        "mcp_evidence": {"type": "string"},
        "has_composio_integration": {"type": "boolean"},
        "composio_evidence": {"type": "string"},
        "buildability": {"type": "string"},
        "main_blocker": {"type": "string"},
        "docs_url": {"type": "string"},
        "verification_notes": {"type": "string"},
    },
    "required": [
        "app_name", "primary_auth", "all_auth_methods", "self_serve",
        "self_serve_evidence", "api_type", "api_breadth",
        "has_existing_mcp", "mcp_evidence", "has_composio_integration",
        "composio_evidence", "buildability", "main_blocker", "docs_url",
        "verification_notes",
    ],
}

VERIFY_PROMPT = """\
You are a meticulous fact-checker verifying research about app APIs for Composio.

You will be given an app name and the fetched content of its developer docs, \
pricing page, and/or API reference. Your job is to determine the CORRECT \
values for each field based strictly on what you can confirm from the provided \
content and your knowledge.

Return a JSON object with these fields:
- app_name: string
- primary_auth: the main auth method (e.g. "OAuth2", "API Key", "Bearer Token", etc.)
- all_auth_methods: array of all supported auth methods
- self_serve: MUST be one of: "self-serve-free", "self-serve-trial", \
  "paid-plan-required", "admin-approval", "partner-gated", "contact-sales", "open-source"
- self_serve_evidence: direct quote or specific evidence from docs/pricing page
- api_type: MUST be one of: "REST", "GraphQL", "REST+GraphQL", "gRPC", \
  "WebSocket", "SDK-only", "CLI-only", "None"
- api_breadth: MUST be one of: "comprehensive", "moderate", "limited", "minimal", "none"
- has_existing_mcp: boolean — only true if you are confident an MCP server exists
- mcp_evidence: evidence for MCP claim
- has_composio_integration: boolean — only true if confident composio.dev lists this app
- composio_evidence: evidence for Composio claim
- buildability: MUST be one of: "ready", "feasible", "challenging", "not-feasible"
- main_blocker: biggest obstacle or "None — ready to build"
- docs_url: best developer docs URL
- verification_notes: any discrepancies or caveats you noticed

Be extra careful. Provide specific evidence for each claim.\
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch_page(url: str) -> str | None:
    try:
        if not url.startswith("http"):
            url = "https://" + url
        resp = http_client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "svg"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return "\n".join(lines)[:MAX_PAGE_CHARS]
    except Exception:
        return None


def select_sample(results: list[dict], sample_size: int) -> list[dict]:
    """Stratified sample: pick evenly across categories."""
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        cat = r.get("category", "Unknown")
        by_cat.setdefault(cat, []).append(r)

    per_cat = max(1, sample_size // len(by_cat))
    remainder = sample_size - per_cat * len(by_cat)

    sample = []
    cats = sorted(by_cat.keys())
    for cat in cats:
        pool = by_cat[cat]
        n = min(per_cat, len(pool))
        sample.extend(random.sample(pool, n))

    if remainder > 0:
        remaining_pool = [r for r in results if r not in sample]
        extra = min(remainder, len(remaining_pool))
        sample.extend(random.sample(remaining_pool, extra))

    return sample[:sample_size]


def verify_app(original: dict) -> dict:
    """Re-research an app and compare with original findings."""
    name = original["app_name"]
    print(f"  Verifying {name}...", end=" ", flush=True)

    # Fetch multiple pages for thorough verification
    pages = {}
    docs_url = original.get("docs_url", "")
    if docs_url:
        content = fetch_page(docs_url)
        if content:
            pages["docs"] = (docs_url, content)

    hint = ""
    for r in _load_apps():
        if r["name"] == name:
            hint = r["hint"]
            break

    if hint:
        base = hint.split("(")[0].strip().rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        if "docs" not in pages:
            c = fetch_page(base)
            if c:
                pages["main"] = (base, c)
        for suffix in ["/pricing", "/plans"]:
            c = fetch_page(base.rstrip("/") + suffix)
            if c and len(c) > 200:
                pages["pricing"] = (base.rstrip("/") + suffix, c)
                break

    fetched_summary = ""
    combined_content = ""
    for label, (url, content) in pages.items():
        fetched_summary += f"  - {label}: {url}\n"
        combined_content += f"\n--- {label.upper()} PAGE ({url}) ---\n{content}\n"

    user_msg = (
        f"Verify the research findings for this app:\n\n"
        f"App: {name}\n"
        f"Category: {original.get('category', 'Unknown')}\n\n"
    )

    if combined_content:
        user_msg += (
            f"I fetched these pages:\n{fetched_summary}\n"
            f"<fetched_content>{combined_content[:MAX_PAGE_CHARS]}</fetched_content>\n\n"
        )
    else:
        user_msg += "Could not fetch any pages. Use your knowledge.\n\n"

    user_msg += (
        "Determine the CORRECT values for auth, self-serve access, API type, "
        "API breadth, MCP status, Composio integration status, and buildability. "
        "Provide evidence for each."
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=VERIFY_PROMPT + "\n\n" + user_msg,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VERIFY_SCHEMA,
                temperature=0.1,
            ),
        )

        verified = json.loads(response.text)

        matches = {}
        for field in COMPARE_FIELDS:
            orig_val = original.get(field)
            ver_val = verified.get(field)
            if isinstance(orig_val, bool) or isinstance(ver_val, bool):
                matches[field] = bool(orig_val) == bool(ver_val)
            else:
                matches[field] = (
                    str(orig_val).lower().strip() == str(ver_val).lower().strip()
                )

        correct = sum(matches.values())
        total = len(matches)
        accuracy = correct / total if total > 0 else 0

        print(f"-> {correct}/{total} fields match ({accuracy:.0%})")

        return {
            "app_name": name,
            "app_id": original.get("id"),
            "category": original.get("category"),
            "original": {f: original.get(f) for f in COMPARE_FIELDS},
            "verified": {f: verified.get(f) for f in COMPARE_FIELDS},
            "field_matches": matches,
            "accuracy": accuracy,
            "correct_count": correct,
            "total_fields": total,
            "verification_notes": verified.get("verification_notes", ""),
            "evidence": {
                "self_serve": verified.get("self_serve_evidence", ""),
                "mcp": verified.get("mcp_evidence", ""),
                "composio": verified.get("composio_evidence", ""),
            },
            "pages_fetched": list(pages.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except json.JSONDecodeError as e:
        print(f"-> ERROR: bad JSON ({e})")
        return {"app_name": name, "error": f"JSON decode: {e}"}
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "quota" in err_str.lower():
            print("-> rate-limited, waiting 60s...")
            time.sleep(60)
            return verify_app(original)
        print(f"-> ERROR: {e}")
        return {"app_name": name, "error": str(e)}


def _load_apps() -> list[dict]:
    apps_file = BASE_DIR / "apps.json"
    with open(apps_file) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Verify research agent accuracy")
    parser.add_argument("--sample", type=int, default=20, help="Sample size (default 20)")
    parser.add_argument("--apps", type=str, help="Comma-separated app IDs to verify")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)

    if not RESULTS_FILE.exists():
        print("No results.json found. Run research_agent.py first.")
        sys.exit(1)

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    valid = [r for r in results if "error" not in r]
    print(f"Loaded {len(valid)} valid results (out of {len(results)} total)")

    if args.apps:
        ids = [int(x) for x in args.apps.split(",")]
        sample = [r for r in valid if r.get("id") in ids]
    else:
        sample = select_sample(valid, args.sample)

    print(f"\n{'=' * 60}")
    print(f"  Verification Agent")
    print(f"  Model        : {GEMINI_MODEL} (FREE)")
    print(f"  Sample size  : {len(sample)}")
    print(f"  Categories   : {len(set(r.get('category') for r in sample))}")
    print(f"{'=' * 60}\n")

    verifications = []
    for app_result in sample:
        v = verify_app(app_result)
        verifications.append(v)
        time.sleep(DELAY)

    valid_v = [v for v in verifications if "error" not in v]
    if valid_v:
        overall_accuracy = sum(v["accuracy"] for v in valid_v) / len(valid_v)
        field_accuracy = {}
        for field in COMPARE_FIELDS:
            matches = [
                v["field_matches"].get(field)
                for v in valid_v
                if "field_matches" in v
            ]
            field_accuracy[field] = (
                sum(m for m in matches if m) / len(matches) if matches else 0
            )

        mismatches = []
        for v in valid_v:
            for field, matched in v.get("field_matches", {}).items():
                if not matched:
                    mismatches.append({
                        "app": v["app_name"],
                        "field": field,
                        "original": v["original"].get(field),
                        "verified": v["verified"].get(field),
                        "notes": v.get("verification_notes", ""),
                    })
    else:
        overall_accuracy = 0
        field_accuracy = {}
        mismatches = []

    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "model": GEMINI_MODEL,
        "sample_size": len(sample),
        "valid_verifications": len(valid_v),
        "errors": len(verifications) - len(valid_v),
        "overall_accuracy": round(overall_accuracy, 4),
        "field_accuracy": {k: round(v, 4) for k, v in field_accuracy.items()},
        "mismatches": mismatches,
        "verifications": verifications,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"  Verification Complete")
    print(f"  Overall accuracy : {overall_accuracy:.1%}")
    print(f"  Field accuracy:")
    for field, acc in sorted(field_accuracy.items(), key=lambda x: x[1]):
        filled = int(acc * 20)
        bar = "#" * filled + "-" * (20 - filled)
        print(f"    {field:<30} [{bar}] {acc:.0%}")
    print(f"  Mismatches       : {len(mismatches)}")
    print(f"  Saved to         : {OUTPUT_FILE}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
