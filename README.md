# AI Coding Tools Digest + LinkedIn Newsletter

Two automated pipelines powered by Claude:

1. **Daily Vercel site** — scrapes official changelogs and Claude Code docs, generates 3 curated stories with summaries and developer-focused analysis
2. **Weekly LinkedIn post** — reads the site's top 3, picks the best one, writes and publishes a post with Telegram approval

---

## What It Does

### Pipeline 1 — Daily Site (5 AM UTC, Mon–Sat)

1. **Scrapes** official changelog and release-note pages for 8 AI coding tools (no RSS)
2. **Generates** self-made feature spotlight articles from Claude Code documentation pages — Claude Sonnet reads the docs and writes original analysis
3. **Ranks** all collected items with Claude Haiku, prioritising Claude Code and coding-tool relevance
4. **Writes** a 2–3 sentence factual summary and a developer-focused "considerations" paragraph for each of the top 3
5. **Builds** a static HTML page and writes `site/news.json`
6. **Commits** and pushes — Vercel auto-deploys the site

### Pipeline 2 — Weekly LinkedIn Post (7 AM UTC, Tuesday)

1. **Reads** `site/news.json` (already built by Pipeline 1)
2. **Picks** the single best story for LinkedIn using Claude Haiku, applying historical performance bonuses and source diversity penalties
3. **Writes** a LinkedIn post with Claude Sonnet — natural, conversational, 2 sentences + hashtags
4. **Critiques** the draft with Claude Haiku; regenerates once if quality score < 7/10
5. **Sends** a Telegram preview with ✅ / ❌ approval buttons — waits up to 30 minutes
6. **Publishes** to LinkedIn with thumbnail on approval; records to `history.json`

---

## Sources

### Changelog sources (scraped directly, no RSS)

| Tool | URL scraped |
|------|-------------|
| **Claude Code** | `docs.anthropic.com/en/release-notes/claude-code` |
| **Cursor** | `cursor.com/changelog` |
| **OpenAI Codex** | `platform.openai.com/docs/changelog` |
| **GitHub Copilot** | `docs.github.com/en/copilot/…/github-copilot-release-notes` |
| **Windsurf** | `codeium.com/blog` |
| **Aider** | `aider.chat/CHANGELOG.md` |
| **Continue.dev** | `github.com/continuedev/continue/releases` |
| **Amazon Q** | `aws.amazon.com/q/developer/` |

### Claude Code feature spotlights (self-made articles)

Claude Sonnet reads each docs page and writes an original article explaining the feature, its non-obvious aspects, and practical implications for developers:

- Hooks · MCP · Sub-agents · Memory · GitHub Actions integration
- Slash Commands · Settings · Tutorials

These compete with changelog items for the 3 daily slots. Claude Code content gets a topic-relevance bonus in the ranking rubric.

---

## Architecture

### Site pipeline (`site_pipeline.py`)

```
CHANGELOG_SOURCES (8 URLs)
       │
       ▼
fetch_page_text()           — HTTP fetch + HTML strip → clean text (≤8000 chars)
       │
       ▼
extract_changelog_items()   — Claude Haiku: extract 2 recent items per source
       │                       returns {source, title, link, summary, published}
       ▼
CLAUDE_CODE_FEATURE_PAGES (8 docs URLs)
       │
       ▼
generate_feature_spotlight() — Claude Sonnet: write original article from docs
       │                        returns {title, summary, source="Claude Code Docs", ...}
       ▼
rank_stories(top_n=3)       — Claude Haiku scores all items 0–10, returns top 3
       │
       ▼
write_site_entry() × 3      — Claude Sonnet: factual summary + developer considerations
       │
       ▼
fetch_og_meta()             — og:image for each story
       │
       ▼
site/news.json              — structured data (rank, score, title, url, source,
       │                       summary, considerations, published, og_image)
       ▼
build_site()                — render site/template.html → site/index.html
       │
       ▼
git commit + push           — Vercel auto-deploys on push to main
```

### LinkedIn pipeline (`main.py`)

```
load_history() + update_analytics()   — fetch LinkedIn engagement for posts 7–21 days old
       │
       ▼
compute_performance_bonuses()         — per-source and per-topic adaptive bonuses
       │
       ▼
_load_news_json()                     — read site/news.json (3 pre-ranked stories)
       │
       ▼
_pick_linkedin_story()                — Claude Haiku picks best of 3 for LinkedIn
       │                                (applies performance bonus + source diversity)
       ▼
write_post()                          — Claude Sonnet writes the post
       │
       ▼
critique_post()                       — Claude Haiku scores quality 1–10
       │  score < 7 → regenerate once
       ▼
request_approval()                    — Telegram inline keyboard (✅/❌), 30 min timeout
       │
       ▼
publish()                             — LinkedIn REST API with thumbnail
       │
       ▼
save_history() + commit_history_to_git()
```

---

## Site Design

The static site (`site/index.html`) is a self-contained HTML/CSS page (no JavaScript framework, dark mode aware) showing 3 story cards:

- Rank badge · Score badge
- Title linked to original article
- Source · Publication date
- Factual summary paragraph
- "Claude's take:" blockquote with developer-focused considerations
- "Read full article →" link

Updated daily at 5 AM UTC. Deployed automatically via Vercel on every push to `main`.

### Changelog Sources (8, scraped directly)

Claude Code, Cursor, OpenAI Codex, GitHub Copilot, Windsurf, Aider, Continue.dev, Amazon Q

---

## LLM Model Usage

| Step | Model | Temp | Max tokens | Purpose |
|------|-------|------|------------|---------|
| `extract_changelog_items` | `claude-haiku-4-5-20251001` | 0 | 400 | Extract items from changelog HTML |
| `generate_feature_spotlight` | `claude-sonnet-4-6` | 0.4 | 300 | Write original Claude Code article |
| `rank_stories` (site) | `claude-haiku-4-5-20251001` | 0 | 500 | Rank all items, pick top 3 |
| `write_site_entry` | `claude-sonnet-4-6` | 0.3 | 300 | Summary + considerations per story |
| `_pick_linkedin_story` | `claude-haiku-4-5-20251001` | 0 | 50 | Pick 1 of 3 for LinkedIn |
| `write_post` | `claude-sonnet-4-6` | 0.7 | 400 | Write LinkedIn post |
| `critique_post` | `claude-haiku-4-5-20251001` | 0 | 150 | Quality evaluation |

Prompt caching is enabled on the static portions of the feature spotlight system prompt, site writer system prompt, and LinkedIn writer system prompt.

---

## Adaptive Ranking (LinkedIn)

After several weeks of publishing, the pipeline accumulates engagement data in `history.json`. Before picking which story to post on LinkedIn, it injects a performance context into the Claude Haiku selection prompt:

```
HISTORICAL PERFORMANCE BONUS — apply +1 to stories from: Claude Code Docs, Cursor
HISTORICAL PERFORMANCE PENALTY — apply -1 to stories from: Amazon Q
HIGH-ENGAGEMENT TOPICS: hooks, sub-agents, mcp
SOURCE DIVERSITY: 'GitHub Copilot' published last time — prefer a different source.
```

Engagement score formula: `reactions + comments × 2 + reposts × 3`

Bonus thresholds: +1 when source mean ≥ 1.3× overall average; −1 when ≤ 0.6× average.

---

## Post Format (LinkedIn)

Claude Sonnet writes every post following strict constraints:

- **Exactly 2 sentences** — no lists, no breakdowns, no call to action
- Sentence 1: shares the news simply, with one emoji placed naturally
- Sentence 2: one plain-language takeaway — why it matters or what's interesting
- Final line: 2–3 relevant hashtags

**Banned words**: game-changer, revolutionary, unlock, empower, leverage, synergy, groundbreaking, orchestration layer, control loop, paradigm, delve, transformative.

---

## `history.json` Schema

```json
{
  "urn:li:share:1234567890": {
    "post_id":       "urn:li:share:1234567890",
    "published_at":  "2026-04-22T07:15:26+00:00",
    "article_url":   "https://docs.anthropic.com/en/docs/claude-code/hooks",
    "article_title": "Claude Code Hooks: Build Custom Automation Around Every Tool Call",
    "source":        "Claude Code Docs",
    "score":         9,
    "comment_text":  "Claude Code now lets you intercept every tool call...\n#ClaudeCode #AI",
    "topics":        ["hooks", "claude", "automation"],
    "hashtags":      ["#ClaudeCode", "#AI", "#DevTools"],
    "analytics":     {
      "fetched_at":       "2026-04-29T07:10:00+00:00",
      "reactions":        142,
      "comments":         17,
      "reposts":          8,
      "impressions":      3200,
      "engagement_score": 201
    }
  }
}
```

`analytics` is `null` until the post is at least 7 days old.

---

## Project Structure

```
.
├── .github/workflows/
│   ├── post.yml              # LinkedIn pipeline — Tue 7 AM UTC
│   └── update_site.yml       # Site pipeline — daily 5 AM UTC, Mon–Sat
│
├── agents/
│   ├── analytics_agent.py    # LinkedIn engagement data + adaptive bonuses
│   ├── changelog_agent.py    # Claude Haiku: extract items from changelog pages
│   ├── feature_spotlight_agent.py  # Claude Sonnet: self-made Claude Code articles
│   ├── notifier_agent.py     # Telegram notifications + HITL approval
│   ├── publisher_agent.py    # LinkedIn REST API
│   ├── ranking_agent.py      # Claude Haiku: score and rank stories
│   ├── site_writer_agent.py  # Claude Sonnet: summary + considerations for site
│   └── writer_agent.py       # Claude Sonnet: LinkedIn post + Haiku critique
│
├── utils/
│   ├── cursor_scraper.py     # HTML scraper for cursor.com/changelog
│   ├── history.py            # Load/save history.json, git commit
│   ├── og_meta.py            # og:image fetch + LinkedIn image upload
│   ├── page_scraper.py       # Generic HTML/Markdown fetcher → clean text
│   ├── site_builder.py       # Render template.html → index.html
│   └── url_utils.py          # URL normalisation and validation
│
├── site/
│   ├── template.html         # HTML/CSS template (authored once, never overwritten)
│   ├── index.html            # Generated daily by site_pipeline.py
│   └── news.json             # Generated daily; read by main.py
│
├── main.py                   # LinkedIn pipeline entry point
├── site_pipeline.py          # Site generation entry point
├── config.py                 # All constants, URLs, and source lists
├── vercel.json               # Vercel static deployment config (outputDirectory: site)
├── history.json              # Post history + analytics (auto-committed by CI)
├── requirements.txt          # anthropic, feedparser, requests
└── CLAUDE.md                 # Instructions for Claude Code
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- Anthropic API key
- LinkedIn Developer App with OAuth token
- Telegram Bot
- Vercel account (free tier is sufficient)

### Local Setup

```bash
git clone https://github.com/lucalamalfa91/ai-linkedin-newsletter.git
cd ai-linkedin-newsletter
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_ACCESS_TOKEN=AQV...
LINKEDIN_PERSON_ID=urn:li:person:XXXXX
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_CHAT_ID=123456789
```

Run the site pipeline (generates `site/news.json` and `site/index.html`):
```bash
python site_pipeline.py
```

Run the LinkedIn pipeline (reads `site/news.json`):
```bash
python main.py
python main.py --no-confirm    # skip Telegram approval
```

---

## Environment Variables

| Variable | Required by | Description |
|----------|------------|-------------|
| `ANTHROPIC_API_KEY` | both pipelines | Claude API key |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn pipeline | OAuth 2.0 token |
| `LINKEDIN_PERSON_ID` | LinkedIn pipeline | `urn:li:person:XXXXX` |
| `TELEGRAM_BOT_TOKEN` | LinkedIn pipeline | Telegram bot token |
| `TELEGRAM_CHAT_ID` | LinkedIn pipeline | Telegram chat ID |

The site pipeline (`site_pipeline.py`) only requires `ANTHROPIC_API_KEY`.

### Getting LinkedIn Credentials

1. Create a LinkedIn App at [developers.linkedin.com](https://www.linkedin.com/developers/)
2. Add **"Share on LinkedIn"** and **"Marketing Developer Platform"** products
3. Request OAuth scopes: `w_member_social` (publish) and `r_member_social` (analytics — requires LinkedIn partner approval; silently skipped if not granted)
4. Retrieve your Person URN from `https://api.linkedin.com/v2/userinfo`

---

## GitHub Actions Setup

### Secrets

Add all 5 environment variables under **Settings → Secrets and variables → Actions**.

### Workflows

| Workflow | File | Schedule | Secrets needed |
|----------|------|----------|----------------|
| Update site | `update_site.yml` | Daily 5 AM UTC, Mon–Sat | `ANTHROPIC_API_KEY` (+ Telegram for failure alerts) |
| LinkedIn post | `post.yml` | Tuesday 7 AM UTC | All 5 |

Both workflows have `permissions: contents: write` to commit `site/news.json`, `site/index.html`, and `history.json`.

### Vercel Setup (one-time)

1. Connect the GitHub repo to Vercel
2. Set root directory: leave as repo root
3. Build command: none
4. Output directory: `site`
5. Every push to `main` auto-deploys the static site

---

## Troubleshooting

**`site/news.json not found`** — Run `python site_pipeline.py` first, or trigger `update_site.yml` via workflow dispatch.

**`LinkedIn error 401`** — Token expired. Regenerate from the LinkedIn Developer Portal and update the GitHub Secret.

**`LinkedIn error 422`** — API version mismatch. Check `LINKEDIN_VERSION` in `config.py` (currently `202603`).

**`No thumbnail — skipping`** — The selected story's `og:image` could not be fetched. The pipeline only skips this candidate; others are tried if available. Feature spotlight articles link to docs pages which may not have og:image — ensure changelog items are also in the top 3.

**Analytics silently skipped** — `r_member_social` scope not granted. The pipeline continues with static ranking.

**`history.json` push conflict** — Two workflow runs overlapped. Re-run the failed workflow; it will pick up the latest `history.json` via fresh checkout.

**Cursor scraper returns no items** — The changelog page structure changed. Update `utils/cursor_scraper.py` to match the new HTML.

---

## License

MIT License — free to use and modify.
