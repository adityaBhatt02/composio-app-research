#!/usr/bin/env python3
"""
Composio App Research Agent
============================
Researches 100 apps for API integration feasibility using Google Gemini (FREE)
+ web fetching.

For each app, the agent:
1. Fetches the developer docs page (tries multiple URL patterns)
2. Feeds page content + app context to Gemini for structured JSON analysis
3. Extracts: auth, self-serve status, API surface, MCP, buildability verdict
4. Saves results incrementally to data/results.json

Usage:
    python research_agent.py                    # Research all 100 apps
    python research_agent.py --start 51         # Resume from app #51
    python research_agent.py --only "Slack"     # Research one app
    python research_agent.py --dry-run          # Test without API calls
"""

from google import genai
from google.genai.types import GenerateContentConfig
import httpx
import json
import os
import sys
import time
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
APPS_FILE = BASE_DIR / "apps.json"
OUTPUT_FILE = BASE_DIR / "data" / "results_final.json"

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_PAGE_CHARS = 12_000
DELAY_BETWEEN_CALLS = 8.0  # 15 RPM free tier — 8s to be safe
REQUEST_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
api_key = os.getenv("GEMINI_API_KEY", "")

client = None
if api_key:
    client = genai.Client(api_key=api_key)

http_client = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    follow_redirects=True,
    headers={
        "User-Agent": (
            "Mozilla/5.0 (compatible; ComposioResearchBot/1.0; "
            "+https://github.com/composio-research)"
        )
    },
)

# ---------------------------------------------------------------------------
# The JSON schema Gemini must return
# ---------------------------------------------------------------------------
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "app_name": {"type": "string"},
        "category": {"type": "string"},
        "one_liner": {"type": "string"},
        "auth_methods": {
            "type": "array",
            "items": {"type": "string"},
        },
        "primary_auth": {"type": "string"},
        "self_serve": {"type": "string"},
        "self_serve_detail": {"type": "string"},
        "api_type": {"type": "string"},
        "api_breadth": {"type": "string"},
        "api_breadth_detail": {"type": "string"},
        "has_existing_mcp": {"type": "boolean"},
        "mcp_detail": {"type": "string"},
        "has_composio_integration": {"type": "boolean"},
        "buildability": {"type": "string"},
        "main_blocker": {"type": "string"},
        "docs_url": {"type": "string"},
        "evidence_urls": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "string"},
        "confidence_note": {"type": "string"},
    },
    "required": [
        "app_name", "category", "one_liner", "auth_methods", "primary_auth",
        "self_serve", "self_serve_detail", "api_type", "api_breadth",
        "api_breadth_detail", "has_existing_mcp", "mcp_detail",
        "has_composio_integration", "buildability", "main_blocker",
        "docs_url", "evidence_urls", "confidence", "confidence_note",
    ],
}

SYSTEM_PROMPT = """\
You are a technical researcher evaluating apps for integration into Composio \
(composio.dev), a platform that turns apps into tools AI agents can call.

Your job: for each app, determine its API characteristics and whether it can \
become an agent-callable toolkit.

Return a JSON object with these exact fields:

- app_name: exact name of the app
- category: the category from the research set
- one_liner: what the app does in one sentence (max 20 words)
- auth_methods: array of ALL auth methods the API supports. Use labels like: \
  "OAuth2", "API Key", "Basic Auth", "Bearer Token", "JWT", "SAML", "Bot Token", "Other", "None"
- primary_auth: the single most common / recommended auth method
- self_serve: MUST be one of: "self-serve-free", "self-serve-trial", \
  "paid-plan-required", "admin-approval", "partner-gated", "contact-sales", "open-source"
  • self-serve-free = any dev can sign up and get API keys at no cost
  • self-serve-trial = free trial period, then paid
  • paid-plan-required = API access only on a paid plan
  • admin-approval = requires org admin or internal approval
  • partner-gated = need a partnership agreement
  • contact-sales = must talk to sales team
  • open-source = self-hosted, no credentials needed
- self_serve_detail: specific access path (e.g. "Free dev account, API key in settings")
- api_type: MUST be one of: "REST", "GraphQL", "REST+GraphQL", "gRPC", "WebSocket", \
  "SDK-only", "CLI-only", "None"
- api_breadth: MUST be one of: "comprehensive", "moderate", "limited", "minimal", "none"
  (comprehensive = most product features exposed; moderate = core features; \
  limited = few endpoints; minimal = barely an API; none = no public API)
- api_breadth_detail: what the API covers (resources / domains)
- has_existing_mcp: boolean — is there a known MCP (Model Context Protocol) server? \
  Only true if you are confident one exists (npm, GitHub, official docs).
- mcp_detail: MCP info or "No known MCP server"
- has_composio_integration: boolean — is this app listed on composio.dev? Only true if confident.
- buildability: MUST be one of: "ready", "feasible", "challenging", "not-feasible"
  (ready = good API + self-serve + no blockers; feasible = doable with effort; \
  challenging = significant obstacles; not-feasible = no usable API or fully gated)
- main_blocker: the single biggest obstacle, or "None — ready to build"
- docs_url: best developer documentation URL
- evidence_urls: array of all URLs used as evidence
- confidence: MUST be one of: "high", "medium", "low"
- confidence_note: what reduces confidence, if anything

Be precise and factual. If uncertain, lower confidence and explain why.\
"""


# ---------------------------------------------------------------------------
# Web fetching helpers
# ---------------------------------------------------------------------------
def fetch_page(url: str) -> str | None:
    """Fetch a URL and return cleaned text content, or None on failure."""
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


def build_candidate_urls(app: dict) -> list[str]:
    """Generate candidate developer-docs URLs from the hint field."""
    hint = app["hint"]
    raw = hint.split("(")[0].strip().rstrip("/")
    if not raw.startswith("http"):
        raw = "https://" + raw

    urls = [raw]

    if not any(p in raw for p in ["/docs", "/api", "/developer", "/rest", "github.com"]):
        base = raw.rstrip("/")
        urls += [
            base + "/developers",
            base + "/developer",
            base + "/docs/api",
            base + "/api",
            base + "/docs",
        ]
    return urls


def fetch_best_docs(app: dict) -> tuple[str | None, str | None]:
    """Try multiple URLs, return (content, url) for the best hit."""
    for url in build_candidate_urls(app):
        content = fetch_page(url)
        if content and len(content) > 300:
            return content, url
    return None, None


# ---------------------------------------------------------------------------
# Core research function
# ---------------------------------------------------------------------------
def research_app(app: dict, dry_run: bool = False) -> dict:
    """Research a single app with retries. Returns a structured dict."""
    label = f"[{app['id']:>3}/100] {app['name']}"
    print(f"  {label}...", end=" ", flush=True)

    # Step 1: fetch docs
    docs_content, fetched_url = fetch_best_docs(app)
    fetch_status = f"fetched {fetched_url}" if docs_content else "no docs fetched"
    print(f"({fetch_status})", end=" ", flush=True)

    if dry_run:
        print("(dry run — skipping API call)")
        return {
            "app_name": app["name"],
            "id": app["id"],
            "category": app["category"],
            "_meta": {"dry_run": True},
        }

    # Step 2: build prompt
    user_msg = (
        f"Research this app for Composio integration feasibility:\n\n"
        f"App: {app['name']}\n"
        f"Category: {app['category']}\n"
        f"Hint / Website: {app['hint']}\n"
    )

    if docs_content:
        user_msg += (
            f"\nI fetched the developer page at {fetched_url}. Content below:\n\n"
            f"<fetched_docs>\n{docs_content}\n</fetched_docs>\n\n"
            f"Use this content together with your existing knowledge.\n"
        )
    else:
        user_msg += (
            "\nCould not fetch the developer docs page. "
            "Use your knowledge of this app's API. "
            "Note reduced confidence due to missing live docs.\n"
        )

    # Step 3: call Gemini with retry logic (max 4 attempts)
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=SYSTEM_PROMPT + "\n\n" + user_msg,
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RESULT_SCHEMA,
                    temperature=0.2,
                ),
            )

            result = json.loads(response.text)
            result["id"] = app["id"]
            result["_meta"] = {
                "fetched_url": fetched_url,
                "docs_fetched": docs_content is not None,
                "model": GEMINI_MODEL,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            conf = result.get("confidence", "?")
            print(f"-> {conf} confidence")
            return result

        except json.JSONDecodeError as e:
            print(f"-> ERROR: bad JSON ({e})")
            return _error_result(app, f"JSON decode error: {e}")
        except Exception as e:
            err_str = str(e)
            is_retryable = (
                "429" in err_str or "503" in err_str
                or "quota" in err_str.lower()
                or "rate" in err_str.lower()
                or "UNAVAILABLE" in err_str
            )
            if is_retryable and attempt < max_retries - 1:
                wait = [10, 30, 60, 90][attempt]
                print(f"-> retry {attempt+1}/{max_retries} (wait {wait}s)...", end=" ", flush=True)
                time.sleep(wait)
                continue
            print(f"-> ERROR: {e}")
            return _error_result(app, str(e))

    return _error_result(app, "Max retries exceeded")


def _error_result(app: dict, error: str) -> dict:
    return {
        "app_name": app["name"],
        "id": app["id"],
        "category": app["category"],
        "error": error,
        "_meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Research apps for Composio integration feasibility"
    )
    parser.add_argument(
        "--start", type=int, default=1, help="Start from app ID (for resuming)"
    )
    parser.add_argument("--end", type=int, default=100, help="End at app ID")
    parser.add_argument("--only", type=str, help="Research a single app by name")
    parser.add_argument(
        "--dry-run", action="store_true", help="Test flow without API calls"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-research even if result exists"
    )
    args = parser.parse_args()

    if not args.dry_run and not client:
        print("ERROR: Set GEMINI_API_KEY in your .env file.")
        print("Get a free key at: https://aistudio.google.com/apikey")
        sys.exit(1)

    with open(APPS_FILE) as f:
        apps = json.load(f)

    if args.only:
        apps = [a for a in apps if a["name"].lower() == args.only.lower()]
        if not apps:
            print(f"App '{args.only}' not found.")
            sys.exit(1)
    else:
        apps = [a for a in apps if args.start <= a["id"] <= args.end]

    # Load existing results for incremental saves
    existing = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            for r in json.load(f):
                existing[r.get("app_name", "")] = r

    print(f"\n{'=' * 60}")
    print(f"  Composio App Research Agent")
    print(f"  Model       : {GEMINI_MODEL} (FREE)")
    print(f"  Apps queued  : {len(apps)}")
    print(f"  Already done : {len(existing)}")
    print(f"  Output       : {OUTPUT_FILE}")
    print(f"{'=' * 60}\n")

    results = dict(existing)
    start_time = time.time()

    for i, app in enumerate(apps):
        if app["name"] in results and not args.force and not args.only:
            print(f"  [{app['id']:>3}/100] {app['name']} — cached, skipping")
            continue

        result = research_app(app, dry_run=args.dry_run)
        results[result.get("app_name", app["name"])] = result

        # Save after every app (crash-safe)
        sorted_results = sorted(results.values(), key=lambda r: r.get("id", 999))
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(sorted_results, f, indent=2)

        if not args.dry_run:
            time.sleep(DELAY_BETWEEN_CALLS)

    elapsed = time.time() - start_time
    all_results = list(results.values())
    errors = sum(1 for r in all_results if "error" in r)
    by_conf = {}
    for r in all_results:
        c = r.get("confidence", "n/a")
        by_conf[c] = by_conf.get(c, 0) + 1

    print(f"\n{'=' * 60}")
    print(f"  Done in {elapsed:.0f}s")
    print(f"  Total results : {len(all_results)}")
    print(f"  Errors        : {errors}")
    print(f"  Confidence    : {by_conf}")
    print(f"  Saved to      : {OUTPUT_FILE}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
