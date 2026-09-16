# Composio App Research — 100 Apps Analyzed for Agent Integration

An AI-powered research pipeline that investigates 100 apps across 10 categories to determine which can become Composio agent toolkits, what authentication they use, and where the blockers are.

## Live Deliverable

👉 **[View the Report](https://your-deployment-url.vercel.app)** _(replace after deployment)_

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  apps.json   │────▶│  research_   │────▶│  data/       │
│  (100 apps)  │     │  agent.py    │     │  results.json│
└──────────────┘     │              │     └──────┬───────┘
                     │ • Fetch docs │            │
                     │ • Gemini API │     ┌──────▼───────┐
                     │ • Structured │     │  verify.py   │
                     │   JSON output│     │ (20-app      │
                     └──────────────┘     │  sample)     │
                                          └──────┬───────┘
                                                 │
                                          ┌──────▼───────┐
                                          │ generate_    │
                                          │ report.py    │
                                          │              │
                                          │ ▶ Patterns   │
                                          │ ▶ Charts     │
                                          │ ▶ HTML page  │
                                          └──────┬───────┘
                                                 │
                                          ┌──────▼───────┐
                                          │ output/      │
                                          │ report.html  │
                                          └──────────────┘
```

### How the Research Agent Works

1. **Loads** the 100-app list from `apps.json`
2. **Fetches** each app's developer docs (tries multiple URL patterns: `/developers`, `/docs/api`, `/api`)
3. **Sends** the page content + app context to Google Gemini API with structured JSON output (response_schema)
4. **Extracts**: auth methods, self-serve status, API type/breadth, MCP status, Composio integration, buildability verdict
5. **Saves** results after every app (crash-safe, supports resume)

### Verification Loop

The verification agent (`verify.py`) independently re-researches a stratified sample of 20 apps (2 per category), fetching docs and pricing pages separately, then compares 7 structured fields against the first pass. This catches systematic errors and reports per-field accuracy.

## Quick Start

### Prerequisites

- Python 3.11+
- A **free** [Gemini API key](https://aistudio.google.com/apikey)

### Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/composio-app-research.git
cd composio-app-research

# Install dependencies
pip install -r requirements.txt

# Set your API key (free from Google AI Studio)
cp .env.example .env
# Edit .env and paste your GEMINI_API_KEY
```

### Run the Pipeline

```bash
# Step 1: Research all 100 apps (~10-15 min, completely FREE)
python research_agent.py

# Step 2: Verify a 20-app sample (~5 min, also free)
python verify.py

# Step 3: Generate the HTML report
python generate_report.py

# Open the report
# → output/report.html
```

### Useful Flags

```bash
# Resume from app #51 (if interrupted)
python research_agent.py --start 51

# Research a single app
python research_agent.py --only "Slack"

# Re-research even if cached
python research_agent.py --force

# Dry run (test without API calls)
python research_agent.py --dry-run

# Verify specific apps
python verify.py --apps 1,21,41,61,81

# Larger verification sample
python verify.py --sample 30
```

## What the Agent Got Right and Wrong

See the **Verification** section of the HTML report for:
- Overall accuracy percentage
- Per-field accuracy breakdown
- Every mismatch between first-pass and verification, shown honestly

Common areas of lower accuracy:
- **MCP/Composio status** — hardest to verify automatically
- **Self-serve vs paid** — some apps have confusing tier structures
- **Gated apps** — DealCloud, PitchBook, Gladly etc. have minimal public info

## Tech Stack

| Component | Tool | Why |
|-----------|------|-----|
| LLM | Google Gemini 2.0 Flash (FREE) | Structured JSON output, generous free tier |
| Web fetching | httpx + BeautifulSoup | Reliable, no browser needed |
| Data format | JSON | Simple, portable |
| Report | Single HTML + Chart.js | Self-contained, deployable anywhere |

## Deployment

The output is a single `report.html` file. Deploy it anywhere:

```bash
# Vercel (static)
npx vercel output/

# Netlify (drag & drop)
# → Drop output/ folder at app.netlify.com/drop

# GitHub Pages
# → Push output/report.html to a gh-pages branch
```

## Cost

**$0** — Uses Google Gemini 2.0 Flash free tier (1,500 requests/day, 1M tokens/min).
The entire pipeline (100 research + 20 verification) uses ~120 requests, well within limits.

## File Structure

```
├── apps.json               # 100 apps with categories and hints
├── research_agent.py       # Main research agent
├── verify.py               # Verification agent
├── generate_report.py      # HTML report generator
├── requirements.txt        # Python dependencies
├── .env.example            # API key template
├── data/
│   ├── results.json        # Research results (generated)
│   └── verification.json   # Verification results (generated)
└── output/
    └── report.html         # Final deliverable (generated)
```
