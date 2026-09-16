#!/usr/bin/env python3
"""
Report Generator
================
Reads data/results.json and data/verification.json, computes patterns,
and generates a single self-contained HTML page at output/report.html.

Usage:
    python generate_report.py
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

BASE_DIR = Path(__file__).parent
RESULTS_FILE = BASE_DIR / "data" / "results_final.json"
VERIFICATION_FILE = BASE_DIR / "data" / "verification.json"
OUTPUT_FILE = BASE_DIR / "output" / "report.html"


def load_data():
    with open(RESULTS_FILE) as f:
        results = json.load(f)
    verification = None
    if VERIFICATION_FILE.exists():
        with open(VERIFICATION_FILE) as f:
            verification = json.load(f)
    return results, verification


def compute_patterns(results):
    """Compute all pattern statistics from results."""
    valid = [r for r in results if "error" not in r]

    # Auth distribution
    auth_counter = Counter()
    for r in valid:
        auth_counter[r.get("primary_auth", "Unknown")] += 1

    all_auth = Counter()
    for r in valid:
        for a in r.get("auth_methods", []):
            all_auth[a] += 1

    # Self-serve distribution
    self_serve_counter = Counter()
    for r in valid:
        self_serve_counter[r.get("self_serve", "Unknown")] += 1

    # Self-serve by category
    self_serve_by_cat = {}
    for r in valid:
        cat = r.get("category", "Unknown")
        ss = r.get("self_serve", "Unknown")
        if cat not in self_serve_by_cat:
            self_serve_by_cat[cat] = Counter()
        self_serve_by_cat[cat][ss] += 1

    # API type
    api_type_counter = Counter()
    for r in valid:
        api_type_counter[r.get("api_type", "Unknown")] += 1

    # API breadth
    api_breadth_counter = Counter()
    for r in valid:
        api_breadth_counter[r.get("api_breadth", "Unknown")] += 1

    # Buildability
    build_counter = Counter()
    for r in valid:
        build_counter[r.get("buildability", "Unknown")] += 1

    # MCP status
    mcp_count = sum(1 for r in valid if r.get("has_existing_mcp"))
    composio_count = sum(1 for r in valid if r.get("has_composio_integration"))

    # Confidence
    conf_counter = Counter()
    for r in valid:
        conf_counter[r.get("confidence", "Unknown")] += 1

    # Blockers
    blocker_counter = Counter()
    for r in valid:
        blocker = r.get("main_blocker", "").lower()
        if "none" in blocker or "ready" in blocker:
            blocker_counter["No blocker"] += 1
        elif "auth" in blocker or "oauth" in blocker:
            blocker_counter["Auth complexity"] += 1
        elif "gated" in blocker or "sales" in blocker or "partner" in blocker:
            blocker_counter["Access gated"] += 1
        elif "paid" in blocker or "cost" in blocker or "pricing" in blocker:
            blocker_counter["Paid access required"] += 1
        elif "doc" in blocker or "documentation" in blocker:
            blocker_counter["Poor documentation"] += 1
        elif "limited" in blocker or "minimal" in blocker or "api" in blocker:
            blocker_counter["Limited API surface"] += 1
        elif "no api" in blocker or "no public" in blocker or "none" in blocker:
            blocker_counter["No public API"] += 1
        else:
            blocker_counter["Other"] += 1

    # Easy wins: self-serve + comprehensive/moderate API + ready/feasible
    easy_wins = [
        r for r in valid
        if r.get("self_serve") in ("self-serve-free", "self-serve-trial", "open-source")
        and r.get("api_breadth") in ("comprehensive", "moderate")
        and r.get("buildability") in ("ready", "feasible")
    ]

    # Needs outreach: partner-gated or contact-sales
    needs_outreach = [
        r for r in valid
        if r.get("self_serve") in ("partner-gated", "contact-sales")
    ]

    return {
        "total": len(results),
        "valid": len(valid),
        "errors": len(results) - len(valid),
        "auth_primary": dict(auth_counter.most_common()),
        "auth_all": dict(all_auth.most_common()),
        "self_serve": dict(self_serve_counter.most_common()),
        "self_serve_by_category": {
            cat: dict(counts) for cat, counts in sorted(self_serve_by_cat.items())
        },
        "api_type": dict(api_type_counter.most_common()),
        "api_breadth": dict(api_breadth_counter.most_common()),
        "buildability": dict(build_counter.most_common()),
        "mcp_count": mcp_count,
        "composio_count": composio_count,
        "confidence": dict(conf_counter.most_common()),
        "blockers": dict(blocker_counter.most_common()),
        "easy_wins": [r.get("app_name") for r in easy_wins],
        "easy_wins_count": len(easy_wins),
        "needs_outreach": [r.get("app_name") for r in needs_outreach],
        "needs_outreach_count": len(needs_outreach),
    }


def generate_html(results, verification, patterns):
    """Generate the complete HTML report."""

    results_json = json.dumps(results, indent=None)
    patterns_json = json.dumps(patterns, indent=None)
    verification_json = json.dumps(verification, indent=None) if verification else "null"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Composio App Research: 100 Apps Analyzed</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242836;
    --border: #2d3148;
    --text: #e4e6f0;
    --text-dim: #8b8fa3;
    --accent: #6c5ce7;
    --accent2: #00cec9;
    --green: #00b894;
    --yellow: #fdcb6e;
    --orange: #e17055;
    --red: #d63031;
    --blue: #0984e3;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 0 24px; }}
  a {{ color: var(--accent2); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  /* Hero */
  .hero {{
    padding: 60px 0 40px;
    text-align: center;
    border-bottom: 1px solid var(--border);
  }}
  .hero h1 {{
    font-size: 2.4rem;
    font-weight: 700;
    margin-bottom: 12px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .hero .subtitle {{
    color: var(--text-dim);
    font-size: 1.1rem;
    max-width: 700px;
    margin: 0 auto 30px;
  }}

  /* Stat cards */
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 30px 0;
  }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
  }}
  .stat-card .number {{
    font-size: 2.2rem;
    font-weight: 700;
    color: var(--accent2);
  }}
  .stat-card .label {{
    font-size: 0.85rem;
    color: var(--text-dim);
    margin-top: 4px;
  }}

  /* Sections */
  .section {{
    padding: 48px 0;
    border-bottom: 1px solid var(--border);
  }}
  .section h2 {{
    font-size: 1.6rem;
    margin-bottom: 8px;
  }}
  .section .section-desc {{
    color: var(--text-dim);
    margin-bottom: 24px;
  }}

  /* Pattern cards */
  .pattern-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 20px;
    margin-top: 20px;
  }}
  .pattern-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }}
  .pattern-card h3 {{
    font-size: 1.05rem;
    margin-bottom: 12px;
    color: var(--accent2);
  }}
  .pattern-card p {{ color: var(--text-dim); font-size: 0.9rem; }}

  /* Charts */
  .charts-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
    gap: 24px;
    margin-top: 24px;
  }}
  .chart-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
  }}
  .chart-box h3 {{
    font-size: 1rem;
    margin-bottom: 16px;
    color: var(--text-dim);
  }}

  /* Table */
  .table-controls {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }}
  .table-controls input, .table-controls select {{
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 0.9rem;
    outline: none;
  }}
  .table-controls input:focus, .table-controls select:focus {{
    border-color: var(--accent);
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }}
  thead th {{
    background: var(--surface2);
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    color: var(--text-dim);
    position: sticky;
    top: 0;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}
  thead th:hover {{ color: var(--accent2); }}
  tbody td {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tbody tr:hover {{ background: var(--surface); }}

  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    white-space: nowrap;
  }}
  .badge-ready {{ background: rgba(0,184,148,0.2); color: var(--green); }}
  .badge-feasible {{ background: rgba(9,132,227,0.2); color: var(--blue); }}
  .badge-challenging {{ background: rgba(253,203,110,0.2); color: var(--yellow); }}
  .badge-not-feasible {{ background: rgba(214,48,49,0.2); color: var(--red); }}

  .badge-selfserve {{ background: rgba(0,184,148,0.15); color: var(--green); }}
  .badge-trial {{ background: rgba(9,132,227,0.15); color: var(--blue); }}
  .badge-paid {{ background: rgba(253,203,110,0.15); color: var(--yellow); }}
  .badge-gated {{ background: rgba(214,48,49,0.15); color: var(--red); }}

  .conf-high {{ color: var(--green); }}
  .conf-medium {{ color: var(--yellow); }}
  .conf-low {{ color: var(--red); }}

  .expand-row {{ display: none; }}
  .expand-row.open {{ display: table-row; }}
  .expand-cell {{
    background: var(--surface);
    padding: 16px 24px;
    font-size: 0.85rem;
    line-height: 1.7;
  }}
  .expand-cell strong {{ color: var(--accent2); }}

  /* Verification */
  .accuracy-bar {{
    height: 8px;
    border-radius: 4px;
    background: var(--surface2);
    overflow: hidden;
    margin-top: 6px;
  }}
  .accuracy-fill {{
    height: 100%;
    border-radius: 4px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
  }}

  .mismatch-table {{ margin-top: 16px; }}
  .mismatch-table th {{ font-size: 0.8rem; }}
  .mismatch-table td {{ font-size: 0.8rem; }}

  /* Agent section */
  .arch-flow {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin: 20px 0;
  }}
  .arch-step {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
    min-width: 140px;
  }}
  .arch-step .step-num {{
    font-size: 0.75rem;
    color: var(--accent);
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .arch-step .step-label {{ font-size: 0.9rem; }}
  .arch-arrow {{ color: var(--text-dim); font-size: 1.5rem; }}

  /* Responsive */
  @media (max-width: 768px) {{
    .hero h1 {{ font-size: 1.6rem; }}
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-grid {{ grid-template-columns: 1fr; }}
    .pattern-grid {{ grid-template-columns: 1fr; }}
    .table-controls {{ flex-direction: column; }}
    table {{ display: block; overflow-x: auto; }}
  }}

  /* Footer */
  footer {{
    padding: 40px 0;
    text-align: center;
    color: var(--text-dim);
    font-size: 0.85rem;
  }}
</style>
</head>
<body>

<!-- ===== DATA ===== -->
<script>
const RESULTS = {results_json};
const PATTERNS = {patterns_json};
const VERIFICATION = {verification_json};
</script>

<!-- ===== HERO ===== -->
<div class="hero">
  <div class="container">
    <h1>100 Apps Analyzed for Agent Integration</h1>
    <p class="subtitle">
      A research agent investigated 100 apps across 10 categories to find which can become
      Composio agent toolkits today, what auth they use, and where the blockers are.
    </p>
    <div class="stats-grid" id="hero-stats"></div>
  </div>
</div>

<!-- ===== PATTERNS ===== -->
<div class="section">
  <div class="container">
    <h2>Key Patterns</h2>
    <p class="section-desc">The headline findings from analyzing all 100 apps.</p>
    <div class="pattern-grid" id="patterns"></div>
  </div>
</div>

<!-- ===== CHARTS ===== -->
<div class="section">
  <div class="container">
    <h2>Distribution Analysis</h2>
    <p class="section-desc">How auth methods, access models, and buildability break down.</p>
    <div class="charts-grid">
      <div class="chart-box"><h3>Primary Auth Method</h3><canvas id="chart-auth"></canvas></div>
      <div class="chart-box"><h3>Developer Access Model</h3><canvas id="chart-selfserve"></canvas></div>
      <div class="chart-box"><h3>API Breadth</h3><canvas id="chart-breadth"></canvas></div>
      <div class="chart-box"><h3>Buildability Verdict</h3><canvas id="chart-build"></canvas></div>
      <div class="chart-box"><h3>Common Blockers</h3><canvas id="chart-blockers"></canvas></div>
      <div class="chart-box"><h3>Self-Serve vs Gated by Category</h3><canvas id="chart-cataccess"></canvas></div>
    </div>
  </div>
</div>

<!-- ===== TABLE ===== -->
<div class="section">
  <div class="container">
    <h2>Full Research Data</h2>
    <p class="section-desc">Click any row to expand details. Click column headers to sort.</p>
    <div class="table-controls">
      <input type="text" id="search" placeholder="Search apps...">
      <select id="filter-cat"><option value="">All Categories</option></select>
      <select id="filter-auth"><option value="">All Auth</option></select>
      <select id="filter-build"><option value="">All Buildability</option></select>
      <select id="filter-access"><option value="">All Access</option></select>
    </div>
    <div style="overflow-x:auto;">
      <table id="main-table">
        <thead>
          <tr>
            <th data-key="id">#</th>
            <th data-key="app_name">App</th>
            <th data-key="category">Category</th>
            <th data-key="primary_auth">Auth</th>
            <th data-key="self_serve">Access</th>
            <th data-key="api_type">API</th>
            <th data-key="api_breadth">Breadth</th>
            <th data-key="buildability">Buildability</th>
            <th data-key="confidence">Conf.</th>
          </tr>
        </thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ===== AGENT ===== -->
<div class="section">
  <div class="container">
    <h2>The Research Agent</h2>
    <p class="section-desc">How the automated research pipeline works and where humans stepped in.</p>

    <div class="arch-flow">
      <div class="arch-step"><div class="step-num">STEP 1</div><div class="step-label">Load 100 apps<br><small style="color:var(--text-dim)">apps.json</small></div></div>
      <div class="arch-arrow">&rarr;</div>
      <div class="arch-step"><div class="step-num">STEP 2</div><div class="step-label">Fetch dev docs<br><small style="color:var(--text-dim)">httpx + BeautifulSoup</small></div></div>
      <div class="arch-arrow">&rarr;</div>
      <div class="arch-step"><div class="step-num">STEP 3</div><div class="step-label">Gemini analysis<br><small style="color:var(--text-dim)">Structured JSON output</small></div></div>
      <div class="arch-arrow">&rarr;</div>
      <div class="arch-step"><div class="step-num">STEP 4</div><div class="step-label">Verify sample<br><small style="color:var(--text-dim)">Second-pass agent</small></div></div>
      <div class="arch-arrow">&rarr;</div>
      <div class="arch-step"><div class="step-num">STEP 5</div><div class="step-label">Generate report<br><small style="color:var(--text-dim)">Patterns + HTML</small></div></div>
    </div>

    <div class="pattern-grid">
      <div class="pattern-card">
        <h3>What the agent does automatically</h3>
        <p>For each app: tries multiple URL patterns to find developer docs, scrapes and cleans the page content, sends it to Google Gemini with a structured JSON output schema (response_schema), extracts auth/access/API/MCP/buildability fields, saves results incrementally (crash-safe). Supports resume from any point.</p>
      </div>
      <div class="pattern-card">
        <h3>Where a human was needed</h3>
        <p>
          <strong>Gated apps:</strong> Apps behind partner agreements or sales walls (DealCloud, PitchBook, Gladly) couldn't be fully researched — noting "gated" IS the correct finding.<br><br>
          <strong>Ambiguous docs:</strong> Some apps have confusing auth docs (multiple methods, unclear which is primary). The verification pass catches most of these.<br><br>
          <strong>MCP/Composio status:</strong> Whether a community MCP server exists is hard to verify automatically — these had the lowest field accuracy.
        </p>
      </div>
    </div>
  </div>
</div>

<!-- ===== VERIFICATION ===== -->
<div class="section">
  <div class="container">
    <h2>Verification &amp; Accuracy</h2>
    <p class="section-desc">
      A second agent re-researched a stratified sample (2 per category) and compared field-by-field.
    </p>
    <div id="verification-content"></div>
  </div>
</div>

<footer>
  <div class="container">
    <p>Built with Google Gemini API + Python &middot; Composio App Research Assignment &middot; <span id="gen-date"></span></p>
  </div>
</footer>

<script>
// ===== RENDER FUNCTIONS =====

const COLORS = {{
  accent: '#6c5ce7', accent2: '#00cec9', green: '#00b894',
  yellow: '#fdcb6e', orange: '#e17055', red: '#d63031', blue: '#0984e3',
  purple: '#a29bfe', pink: '#fd79a8', teal: '#81ecec',
}};
const PALETTE = ['#6c5ce7','#00cec9','#0984e3','#00b894','#fdcb6e','#e17055','#d63031','#a29bfe','#fd79a8','#81ecec','#fab1a0','#74b9ff'];

function renderHeroStats() {{
  const el = document.getElementById('hero-stats');
  const p = PATTERNS;
  const valid = RESULTS.filter(r => !r.error);
  const stats = [
    {{ num: p.valid, label: 'Apps Researched' }},
    {{ num: p.easy_wins_count, label: 'Easy Wins (Ready Now)' }},
    {{ num: p.needs_outreach_count, label: 'Need Outreach' }},
    {{ num: p.mcp_count, label: 'Have MCP Servers' }},
    {{ num: p.composio_count, label: 'Already on Composio' }},
  ];
  el.innerHTML = stats.map(s =>
    `<div class="stat-card"><div class="number">${{s.num}}</div><div class="label">${{s.label}}</div></div>`
  ).join('');
}}

function renderPatterns() {{
  const el = document.getElementById('patterns');
  const p = PATTERNS;
  const topAuth = Object.entries(p.auth_primary).sort((a,b) => b[1]-a[1]);
  const topAccess = Object.entries(p.self_serve).sort((a,b) => b[1]-a[1]);
  const topBlocker = Object.entries(p.blockers).sort((a,b) => b[1]-a[1]).filter(x => x[0] !== 'No blocker');

  const patterns = [
    {{
      title: `${{topAuth[0]?.[0] || 'OAuth2'}} dominates auth (${{topAuth[0]?.[1] || 0}} of ${{p.valid}} apps)`,
      body: `Primary auth breakdown: ${{topAuth.slice(0,4).map(x => x[0]+': '+x[1]).join(', ')}}. OAuth2 is the standard for SaaS apps, while developer tools lean toward API keys.`
    }},
    {{
      title: `${{topAccess[0]?.[1] || 0}} apps are ${{topAccess[0]?.[0]?.replace(/-/g,' ') || 'self-serve'}}`,
      body: `Access model: ${{topAccess.map(x => x[0].replace(/-/g,' ')+': '+x[1]).join(', ')}}. Most apps offer some self-serve path, but ${{p.needs_outreach_count}} require outreach.`
    }},
    {{
      title: `#1 blocker: ${{topBlocker[0]?.[0] || 'Access gated'}} (${{topBlocker[0]?.[1] || 0}} apps)`,
      body: `Top blockers: ${{topBlocker.slice(0,4).map(x => x[0]+': '+x[1]).join(', ')}}. The most common obstacles are access restrictions and limited API surfaces.`
    }},
    {{
      title: `${{p.easy_wins_count}} easy wins ready for agent toolkits`,
      body: `These apps have self-serve access + solid APIs + ready/feasible buildability: ${{p.easy_wins.slice(0,10).join(', ')}}${{p.easy_wins.length > 10 ? '...' : ''}}.`
    }},
    {{
      title: `Only ${{p.mcp_count}} of 100 have MCP servers`,
      body: `MCP adoption is still early. Most MCP servers are community-built for popular dev tools. This is a massive opportunity for Composio to fill the gap.`
    }},
    {{
      title: `REST APIs dominate (${{p.api_type['REST'] || 0}} apps)`,
      body: `API types: ${{Object.entries(p.api_type).map(x => x[0]+': '+x[1]).join(', ')}}. GraphQL is a minority, mostly in modern dev/productivity tools.`
    }},
  ];

  el.innerHTML = patterns.map(p =>
    `<div class="pattern-card"><h3>${{p.title}}</h3><p>${{p.body}}</p></div>`
  ).join('');
}}

function makeChart(id, type, labels, datasets, opts = {{}}) {{
  const ctx = document.getElementById(id);
  if (!ctx) return;
  new Chart(ctx, {{
    type,
    data: {{ labels, datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: true,
      plugins: {{
        legend: {{ labels: {{ color: '#8b8fa3', font: {{ size: 11 }} }} }},
        ...opts.plugins,
      }},
      scales: type === 'bar' ? {{
        x: {{ ticks: {{ color: '#8b8fa3', font: {{ size: 10 }} }}, grid: {{ color: '#2d3148' }} }},
        y: {{ ticks: {{ color: '#8b8fa3' }}, grid: {{ color: '#2d3148' }} }},
      }} : undefined,
      ...opts,
    }}
  }});
}}

function renderCharts() {{
  const p = PATTERNS;

  // Auth
  const authEntries = Object.entries(p.auth_primary).sort((a,b) => b[1]-a[1]);
  makeChart('chart-auth', 'doughnut', authEntries.map(x=>x[0]), [{{
    data: authEntries.map(x=>x[1]),
    backgroundColor: PALETTE.slice(0, authEntries.length),
    borderWidth: 0,
  }}]);

  // Self-serve
  const ssEntries = Object.entries(p.self_serve).sort((a,b) => b[1]-a[1]);
  const ssColors = ssEntries.map(x => {{
    if (x[0].includes('free') || x[0].includes('open')) return COLORS.green;
    if (x[0].includes('trial')) return COLORS.blue;
    if (x[0].includes('paid')) return COLORS.yellow;
    return COLORS.red;
  }});
  makeChart('chart-selfserve', 'doughnut', ssEntries.map(x=>x[0].replace(/-/g,' ')), [{{
    data: ssEntries.map(x=>x[1]),
    backgroundColor: ssColors,
    borderWidth: 0,
  }}]);

  // Breadth
  const bEntries = Object.entries(p.api_breadth);
  const bOrder = ['comprehensive','moderate','limited','minimal','none'];
  bEntries.sort((a,b) => bOrder.indexOf(a[0]) - bOrder.indexOf(b[0]));
  makeChart('chart-breadth', 'bar', bEntries.map(x=>x[0]), [{{
    label: 'Apps',
    data: bEntries.map(x=>x[1]),
    backgroundColor: [COLORS.green, COLORS.blue, COLORS.yellow, COLORS.orange, COLORS.red],
    borderRadius: 4,
  }}], {{ plugins: {{ legend: {{ display: false }} }} }});

  // Buildability
  const buildEntries = Object.entries(p.buildability);
  const buildOrder = ['ready','feasible','challenging','not-feasible'];
  buildEntries.sort((a,b) => buildOrder.indexOf(a[0]) - buildOrder.indexOf(b[0]));
  const buildColors = [COLORS.green, COLORS.blue, COLORS.yellow, COLORS.red];
  makeChart('chart-build', 'doughnut', buildEntries.map(x=>x[0]), [{{
    data: buildEntries.map(x=>x[1]),
    backgroundColor: buildColors.slice(0, buildEntries.length),
    borderWidth: 0,
  }}]);

  // Blockers
  const blockEntries = Object.entries(p.blockers).sort((a,b) => b[1]-a[1]);
  makeChart('chart-blockers', 'bar', blockEntries.map(x=>x[0]), [{{
    label: 'Apps',
    data: blockEntries.map(x=>x[1]),
    backgroundColor: PALETTE.slice(0, blockEntries.length),
    borderRadius: 4,
  }}], {{ plugins: {{ legend: {{ display: false }} }}, indexAxis: 'y' }});

  // Self-serve by category (stacked bar)
  const cats = Object.keys(p.self_serve_by_category).map(c => c.length > 20 ? c.slice(0,18)+'...' : c);
  const ssTypes = [...new Set(Object.values(p.self_serve_by_category).flatMap(v => Object.keys(v)))];
  const ssDatasets = ssTypes.map((t, i) => ({{
    label: t.replace(/-/g,' '),
    data: Object.values(p.self_serve_by_category).map(v => v[t] || 0),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderRadius: 2,
  }}));
  makeChart('chart-cataccess', 'bar', cats, ssDatasets, {{
    plugins: {{ legend: {{ labels: {{ font: {{ size: 9 }} }} }} }},
    scales: {{
      x: {{ stacked: true, ticks: {{ color: '#8b8fa3', font: {{ size: 9 }} }}, grid: {{ color: '#2d3148' }} }},
      y: {{ stacked: true, ticks: {{ color: '#8b8fa3' }}, grid: {{ color: '#2d3148' }} }},
    }},
  }});
}}

function buildBadge(val, type) {{
  if (type === 'build') {{
    const cls = {{'ready':'badge-ready','feasible':'badge-feasible','challenging':'badge-challenging','not-feasible':'badge-not-feasible'}}[val] || '';
    return `<span class="badge ${{cls}}">${{val}}</span>`;
  }}
  if (type === 'access') {{
    let cls = 'badge-gated';
    if (val?.includes('free') || val?.includes('open')) cls = 'badge-selfserve';
    else if (val?.includes('trial')) cls = 'badge-trial';
    else if (val?.includes('paid')) cls = 'badge-paid';
    return `<span class="badge ${{cls}}">${{(val||'').replace(/-/g,' ')}}</span>`;
  }}
  return val || '';
}}

let sortKey = 'id', sortAsc = true;

function renderTable() {{
  const body = document.getElementById('table-body');
  const search = document.getElementById('search').value.toLowerCase();
  const catFilter = document.getElementById('filter-cat').value;
  const authFilter = document.getElementById('filter-auth').value;
  const buildFilter = document.getElementById('filter-build').value;
  const accessFilter = document.getElementById('filter-access').value;

  let data = RESULTS.filter(r => !r.error);

  if (search) data = data.filter(r =>
    r.app_name?.toLowerCase().includes(search) ||
    r.category?.toLowerCase().includes(search) ||
    r.one_liner?.toLowerCase().includes(search)
  );
  if (catFilter) data = data.filter(r => r.category === catFilter);
  if (authFilter) data = data.filter(r => r.primary_auth === authFilter);
  if (buildFilter) data = data.filter(r => r.buildability === buildFilter);
  if (accessFilter) data = data.filter(r => r.self_serve === accessFilter);

  data.sort((a,b) => {{
    let va = a[sortKey] ?? '', vb = b[sortKey] ?? '';
    if (typeof va === 'number') return sortAsc ? va-vb : vb-va;
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  }});

  body.innerHTML = data.map(r => `
    <tr class="data-row" data-id="${{r.id}}" onclick="toggleExpand(${{r.id}})">
      <td>${{r.id}}</td>
      <td><strong>${{r.app_name}}</strong></td>
      <td style="font-size:0.8rem">${{r.category}}</td>
      <td>${{r.primary_auth}}</td>
      <td>${{buildBadge(r.self_serve, 'access')}}</td>
      <td>${{r.api_type}}</td>
      <td>${{r.api_breadth}}</td>
      <td>${{buildBadge(r.buildability, 'build')}}</td>
      <td class="conf-${{r.confidence}}">${{r.confidence}}</td>
    </tr>
    <tr class="expand-row" id="expand-${{r.id}}">
      <td colspan="9" class="expand-cell">
        <strong>What it does:</strong> ${{r.one_liner || 'N/A'}}<br>
        <strong>Auth methods:</strong> ${{(r.auth_methods||[]).join(', ')}}<br>
        <strong>Access detail:</strong> ${{r.self_serve_detail || 'N/A'}}<br>
        <strong>API detail:</strong> ${{r.api_breadth_detail || 'N/A'}}<br>
        <strong>MCP:</strong> ${{r.mcp_detail || (r.has_existing_mcp ? 'Yes' : 'No known MCP')}}<br>
        <strong>Composio:</strong> ${{r.has_composio_integration ? 'Yes — listed on composio.dev' : 'Not yet on Composio'}}<br>
        <strong>Main blocker:</strong> ${{r.main_blocker || 'None'}}<br>
        <strong>Docs:</strong> <a href="${{r.docs_url}}" target="_blank">${{r.docs_url}}</a><br>
        <strong>Confidence note:</strong> ${{r.confidence_note || 'N/A'}}
      </td>
    </tr>
  `).join('');
}}

function toggleExpand(id) {{
  const row = document.getElementById('expand-' + id);
  if (row) row.classList.toggle('open');
}}

function initFilters() {{
  const valid = RESULTS.filter(r => !r.error);
  const cats = [...new Set(valid.map(r => r.category))].sort();
  const auths = [...new Set(valid.map(r => r.primary_auth))].filter(Boolean).sort();
  const builds = ['ready','feasible','challenging','not-feasible'];
  const access = [...new Set(valid.map(r => r.self_serve))].filter(Boolean).sort();

  const catSel = document.getElementById('filter-cat');
  cats.forEach(c => {{ const o = document.createElement('option'); o.value = c; o.textContent = c; catSel.appendChild(o); }});
  const authSel = document.getElementById('filter-auth');
  auths.forEach(a => {{ const o = document.createElement('option'); o.value = a; o.textContent = a; authSel.appendChild(o); }});
  const buildSel = document.getElementById('filter-build');
  builds.forEach(b => {{ const o = document.createElement('option'); o.value = b; o.textContent = b; buildSel.appendChild(o); }});
  const accSel = document.getElementById('filter-access');
  access.forEach(a => {{ const o = document.createElement('option'); o.value = a; o.textContent = a.replace(/-/g,' '); accSel.appendChild(o); }});

  document.getElementById('search').addEventListener('input', renderTable);
  catSel.addEventListener('change', renderTable);
  authSel.addEventListener('change', renderTable);
  buildSel.addEventListener('change', renderTable);
  accSel.addEventListener('change', renderTable);

  document.querySelectorAll('thead th[data-key]').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.key;
      if (sortKey === key) sortAsc = !sortAsc;
      else {{ sortKey = key; sortAsc = true; }}
      renderTable();
    }});
  }});
}}

function renderVerification() {{
  const el = document.getElementById('verification-content');
  if (!VERIFICATION) {{
    el.innerHTML = '<p style="color:var(--text-dim)">Verification data not yet available. Run <code>python verify.py</code> to generate it.</p>';
    return;
  }}

  const v = VERIFICATION;
  const overall = (v.overall_accuracy * 100).toFixed(1);

  let fieldBars = '';
  if (v.field_accuracy) {{
    const fields = Object.entries(v.field_accuracy).sort((a,b) => b[1]-a[1]);
    fieldBars = fields.map(([f, acc]) => `
      <div style="margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;font-size:0.85rem;">
          <span>${{f.replace(/_/g,' ')}}</span>
          <span style="color:var(--accent2)">${{(acc*100).toFixed(0)}}%</span>
        </div>
        <div class="accuracy-bar"><div class="accuracy-fill" style="width:${{acc*100}}%"></div></div>
      </div>
    `).join('');
  }}

  let mismatchRows = '';
  if (v.mismatches && v.mismatches.length > 0) {{
    mismatchRows = v.mismatches.map(m => `
      <tr>
        <td>${{m.app}}</td>
        <td>${{m.field.replace(/_/g,' ')}}</td>
        <td style="color:var(--orange)">${{String(m.original)}}</td>
        <td style="color:var(--green)">${{String(m.verified)}}</td>
      </tr>
    `).join('');
  }}

  el.innerHTML = `
    <div class="stats-grid" style="margin-bottom:24px;">
      <div class="stat-card">
        <div class="number">${{overall}}%</div>
        <div class="label">Overall Accuracy</div>
      </div>
      <div class="stat-card">
        <div class="number">${{v.sample_size}}</div>
        <div class="label">Apps Verified</div>
      </div>
      <div class="stat-card">
        <div class="number">${{v.valid_verifications}}</div>
        <div class="label">Successful Checks</div>
      </div>
      <div class="stat-card">
        <div class="number">${{v.mismatches?.length || 0}}</div>
        <div class="label">Field Mismatches</div>
      </div>
    </div>

    <div class="pattern-grid">
      <div class="pattern-card">
        <h3>Accuracy by Field</h3>
        ${{fieldBars || '<p style="color:var(--text-dim)">No field data</p>'}}
      </div>
      <div class="pattern-card">
        <h3>Methodology</h3>
        <p>The verification agent independently re-researched a stratified sample of ${{v.sample_size}} apps
        (2 per category). For each app, it fetched developer docs and pricing pages, then compared
        7 structured fields against the first-pass results. This catches systematic errors in the
        research agent's analysis.</p>
        <p style="margin-top:8px;">Fields checked: primary auth, self-serve access, API type, API breadth,
        buildability verdict, MCP status, Composio integration status.</p>
      </div>
    </div>

    ${{mismatchRows ? `
    <h3 style="margin-top:24px;font-size:1rem;">Mismatches (Honest Disclosure)</h3>
    <p style="color:var(--text-dim);font-size:0.85rem;margin:8px 0 12px;">
      Where the first-pass agent and verification agent disagreed. The verified value was used
      to correct the finding where appropriate.
    </p>
    <div style="overflow-x:auto;">
      <table class="mismatch-table">
        <thead><tr>
          <th>App</th><th>Field</th><th>Original</th><th>Verified</th>
        </tr></thead>
        <tbody>${{mismatchRows}}</tbody>
      </table>
    </div>` : '<p style="margin-top:16px;color:var(--green);">No mismatches found in the sample.</p>'}}
  `;
}}

// ===== INIT =====
document.getElementById('gen-date').textContent = new Date().toLocaleDateString();
renderHeroStats();
renderPatterns();
renderCharts();
initFilters();
renderTable();
renderVerification();
</script>
</body>
</html>"""

    return html


def main():
    results, verification = load_data()
    patterns = compute_patterns(results)
    html = generate_html(results, verification, patterns)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report generated: {OUTPUT_FILE}")
    print(f"  Apps: {patterns['valid']} valid / {patterns['total']} total")
    print(f"  Easy wins: {patterns['easy_wins_count']}")
    print(f"  Need outreach: {patterns['needs_outreach_count']}")
    print(f"  MCP servers: {patterns['mcp_count']}")
    print(f"\nOpen {OUTPUT_FILE} in a browser to view.")


if __name__ == "__main__":
    main()
