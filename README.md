# AI LinkedIn Newsletter

Automated two-pipeline system that curates AI developer news, publishes a daily static digest website, and posts the best story to LinkedIn weekly — with full human-in-the-loop approval via Telegram.

---

## What It Does

**Pipeline 1 — Daily Site Digest (`site_pipeline.py`, Mon–Sat 5 AM UTC)**

1. Scrapes 8 AI coding tool changelog pages (Claude Code, Cursor, Copilot, Windsurf, etc.)
2. Generates self-authored Claude Code feature spotlight articles from official docs
3. Ranks all items with Claude Haiku → picks the top 3
4. Writes a summary + developer considerations for each story with Claude Sonnet
5. Builds `site/news.json` and `site/index.html`
6. Commits + pushes → Vercel auto-deploys the static site

**Pipeline 2 — Weekly LinkedIn Post (`main.py`, Tue 7 AM UTC)**

1. Updates LinkedIn analytics for recent posts (7–21 days old) → computes adaptive ranking bonuses
2. Reads today's top 3 from `site/news.json`
3. Asks Claude Haiku to pick the single best story for LinkedIn
4. Writes a 2-sentence post with Claude Sonnet, critiques it with Claude Haiku (retry if score < 7)
5. Sends a Telegram preview with ✅/❌ inline buttons — waits up to 30 min for approval
6. On approval: publishes to LinkedIn, records to `history.json`, notifies via Telegram

---

## Architecture

### Site Pipeline (`site_pipeline.py`)

```
_scrape_changelogs()        — fetch 8 changelog pages, Claude Haiku extracts items
        │
        ▼
_generate_spotlights()      — fetch Claude Code docs pages, Claude Sonnet writes articles
        │
        ▼
rank_stories()              — Claude Haiku scores all items, returns top 3
        │
        ▼
write_site_entry()          — Claude Sonnet writes summary + developer considerations
        │
        ▼
_write_news_json()          — site/news.json (title, score, summary, considerations, og_image)
        │
        ▼
build_site()                — renders site/template.html → site/index.html
        │
        ▼
_commit_and_push()          — git commit + push → Vercel auto-deploy
```

### LinkedIn Pipeline (`main.py`)

```
load_history()              — load history.json (post metadata + analytics)
        │
        ▼
update_analytics()          — LinkedIn Analytics API for posts 7–21 days old
        │
        ▼
compute_performance_bonuses() — per-source/topic engagement bonuses from history
        │
        ▼
_load_news_json()           — read pre-ranked top 3 from site/news.json
        │
        ▼
_pick_linkedin_story()      — Claude Haiku selects best story for LinkedIn
        │
        ▼
write_post()                — Claude Sonnet writes 2-sentence post
        │
        ▼
critique_post()             — Claude Haiku evaluates quality (score ≥ 7 or retry)
        │
        ▼
request_approval()          — Telegram preview + inline ✅/❌ buttons (30 min timeout)
        │
   approved?
   ├─ NO  → skip + notify Telegram
   └─ YES ▼
publish()                   — POST to LinkedIn REST API
        │
        ▼
save_history() +            — record to history.json, git commit + push
  commit_history_to_git()
        │
        ▼
notify()                    — Telegram success notification
```

---

## Project Structure

```
.
├── .github/
│   └── workflows/
│       ├── update_site.yml   # Daily site digest + Vercel deploy (Mon–Sat 5 AM UTC)
│       └── post.yml          # Weekly LinkedIn post (Tue 7 AM UTC)
├── agents/
│   ├── analytics_agent.py    # Fetches LinkedIn post analytics, computes engagement bonuses
│   ├── changelog_agent.py    # Claude Haiku extracts items from scraped changelog pages
│   ├── feature_spotlight_agent.py  # Claude Sonnet writes articles from Claude Code docs
│   ├── feed_agent.py         # Fetches 30 RSS feeds, filters last 7 days
│   ├── notifier_agent.py     # Telegram messages + HITL approval with inline keyboard
│   ├── publisher_agent.py    # LinkedIn REST API — creates posts
│   ├── ranking_agent.py      # Claude Haiku scores stories 0–10 across editorial dimensions
│   ├── site_writer_agent.py  # Claude Sonnet writes summary + considerations per story
│   └── writer_agent.py       # Claude Sonnet writes post, Claude Haiku critiques it
├── utils/
│   ├── cursor_scraper.py     # Scrapes Cursor changelog (JS-rendered page)
│   ├── history.py            # Load/save history.json, git commit helper, topic/hashtag extractor
│   ├── og_meta.py            # Fetches og:image / og:title from article URLs
│   ├── page_scraper.py       # Generic HTTP page text fetcher
│   ├── site_builder.py       # Renders Jinja-style HTML template → site/index.html
│   └── url_utils.py          # URL normalisation and validation helpers
├── site/
│   ├── index.html            # Generated static site (committed by CI, served by Vercel)
│   ├── news.json             # Generated digest data (top 3 stories with metadata)
│   └── template.html         # HTML template for the site
├── config.py                 # All constants: feeds, focus topics, model names, paths
├── main.py                   # LinkedIn pipeline entry point
├── site_pipeline.py          # Site digest pipeline entry point
├── history.json              # Post history + LinkedIn analytics (auto-committed by CI)
├── requirements.txt          # anthropic, feedparser, requests
├── vercel.json               # Vercel config: serves site/ as static output
├── .env                      # Local secrets (gitignored)
└── CLAUDE.md                 # Instructions for Claude Code
```

---

## RSS Feed Sources (30)

Defined in `RSS_FEEDS` in `config.py`, all monitored for the **last 7 days**:

| Category | Sources |
|----------|---------|
| **AI Labs** | OpenAI, Anthropic, Google DeepMind, Google AI Blog, Microsoft Research |
| **Agentic AI & Frameworks** | LangChain, LlamaIndex, CrewAI, Haystack, Hugging Face, Omdena, n8n, Vellum AI, Zapier |
| **Practitioners & Researchers** | Simon Willison, The Batch, Sebastian Raschka, The Gradient, Jay Alammar, Latent Space |
| **LLM Efficiency & Prompt Engineering** | Chip Huyen, Eugene Yan, Lilian Weng, Interconnects, Hamel Husain |
| **AI Security & Tools** | Lakera AI, The AI Corner, Maxim AI |

Feed fetch failures are caught per-source and logged as warnings — a single failing feed never stops the pipeline.

### Changelog Sources (8, scraped directly)

Claude Code, Cursor, OpenAI Codex, GitHub Copilot, Windsurf, Aider, Continue.dev, Amazon Q

---

## Content Scoring (Claude Haiku)

Stories are scored 0–10 across these dimensions:

**Source Bonus**
- +3 LLM Efficiency & Prompt Engineering sources
- +2 Agentic AI & Framework sources
- +1 AI Labs / Practitioners

**Content Quality**
- +2 Concrete release (model, product, open-source, benchmark)
- +1 Technical but accessible
- −2 Opinion with no concrete news
- −3 Pure marketing

**Topic Relevance**
- +3 Directly covers a focus topic (agents, security, RAG, MCP, etc.)
- +1 AI-relevant but tangential
- −3 No meaningful AI angle

Only stories scoring ≥ **6/10** (`MIN_SCORE` in `config.py`) are published to LinkedIn.

---

## LLM Model Usage

| Step | Model | Temp | Max tokens | Purpose |
|------|-------|------|------------|---------|
| Changelog extraction | `claude-haiku-4-5-20251001` | 0 | 800 | Extract items from scraped pages |
| Feature spotlight | `claude-sonnet-4-6` | 0.5 | 600 | Write self-authored feature articles |
| Story ranking (site + LinkedIn) | `claude-haiku-4-5-20251001` | 0 | 500 | Score and rank stories |
| Site entry writing | `claude-sonnet-4-6` | 0.4 | 400 | Summary + developer considerations |
| LinkedIn story selection | `claude-haiku-4-5-20251001` | 0 | 50 | Pick best story from top 3 |
| Post writing | `claude-sonnet-4-6` | 0.7 | 200 | 2-sentence LinkedIn post |
| Post critique | `claude-haiku-4-5-20251001` | 0 | 200 | Quality evaluation |

---

## Human-in-the-Loop (HITL) Flow

After the post is drafted, the pipeline sends a Telegram preview with two inline buttons:

```
📝 Post da pubblicare su LinkedIn

[Article Title]
⭐ Score: 8/10
🔗 https://example.com/article

[post text preview...]

[ ✅ Pubblica ]  [ ❌ Annulla ]
```

- **Tap ✅**: post is published to LinkedIn immediately
- **Tap ❌ or timeout (30 min)**: publish is skipped, Telegram notification sent

The pipeline long-polls `getUpdates` at 5-second intervals for up to 30 minutes.
Set `SKIP_CONFIRM=1` or pass `--no-confirm` to bypass approval (useful for testing).

---

## Analytics & Adaptive Ranking

After several weeks of publishing, `history.json` accumulates engagement data. The pipeline fetches LinkedIn Analytics for posts 7–21 days old and stores the results.

Engagement score per post:
```
engagement_score = reactions + comments × 2 + reposts × 3
```

Before ranking, a performance context block is injected into the Claude Haiku prompt:
```
HISTORICAL PERFORMANCE BONUS — apply +1 to stories from: Anthropic, Simon Willison
HISTORICAL PERFORMANCE PENALTY — apply -1 to stories from: VentureBeat AI
HIGH-ENGAGEMENT TOPICS: agents, reasoning, interpretability
SOURCE DIVERSITY: 'Anthropic' published last time — prefer a different source.
```

Bonus threshold: mean engagement ≥ 1.3× overall average. Penalty threshold: < 0.6× average (minimum 3 published posts required).

### `history.json` Schema

```json
{
  "urn:li:share:1234567890": {
    "post_id":       "urn:li:share:1234567890",
    "published_at":  "2026-04-22T07:15:26+00:00",
    "article_url":   "https://example.com/article",
    "article_title": "Anthropic releases Claude 4",
    "source":        "Anthropic",
    "score":         8,
    "comment_text":  "Anthropic released Claude 4...\n#AI #Anthropic",
    "topics":        ["agents", "reasoning"],
    "hashtags":      ["#AI", "#Anthropic"],
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

## LinkedIn API Details

- **Endpoint**: `https://api.linkedin.com/rest/posts`
- **Version**: `202603` (via `LinkedIn-Version` header)
- **Protocol**: REST.li `2.0.0`
- **Post visibility**: `PUBLIC`, distributed to `MAIN_FEED`
- **Post ID**: returned in `x-restli-id` response header

### Analytics API

- **Endpoint**: `GET https://api.linkedin.com/rest/memberCreatorPostAnalytics`
- **Required scope**: `r_member_social`
- **Graceful degradation**: 403 responses are silently skipped; pipeline falls back to static ranking

---

## Post Format

Claude Sonnet writes every LinkedIn post following strict constraints:

- **Exactly 2 sentences.** No lists, no call to action.
- Sentence 1: the news with one emoji placed naturally.
- Sentence 2: one plain-language takeaway — why it matters.
- Final line: 2–3 hashtags.
- Max one technical term, explained immediately.
- Tone: a colleague sharing something interesting at coffee, not a press release.

**Banned words**: game-changer, revolutionary, unlock, empower, leverage, synergy, groundbreaking, orchestration layer, control loop, paradigm, delve, transformative, unleash, harness, redefine, cutting-edge, state-of-the-art, next-gen.

### Quality Gate (Critic Loop)

| Criterion | Max pts |
|-----------|---------|
| Format (2 sentences + emoji + hashtag line) | 3 |
| Tone (natural, no hyperbole, no CTA) | 3 |
| Banned words (none of 18 prohibited words) | 2 |
| Value (clear takeaway) | 2 |

Score ≥ 7 → proceed. Score < 7 → regenerate once, re-evaluate, proceed regardless.

---

## Quick Start

### Prerequisites

- Python 3.12+
- LinkedIn Developer App with OAuth token
- Anthropic API key
- Telegram Bot (for HITL notifications)

### Local Setup

```bash
git clone https://github.com/lucalamalfa91/ai-linkedin-newsletter.git
cd ai-linkedin-newsletter

python -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows

pip install -r requirements.txt
```

Create a `.env` file in the project root:
```
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_ACCESS_TOKEN=AQV...
LINKEDIN_PERSON_ID=urn:li:person:XXXXX
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_CHAT_ID=123456789
```

### Running the Pipelines

```bash
# Build the site digest (writes site/news.json + site/index.html)
python site_pipeline.py

# Publish LinkedIn post (reads site/news.json, sends Telegram approval request)
python main.py

# Skip Telegram approval and publish immediately
python main.py --no-confirm

# Override focus topic
python main.py --topic "RAG and vector databases"
```

`site_pipeline.py` requires only `ANTHROPIC_API_KEY`.  
`main.py` requires all 5 environment variables.

---

## Environment Variables

| Variable | Required by | Description |
|----------|-------------|-------------|
| `ANTHROPIC_API_KEY` | Both pipelines | Claude API key — [console.anthropic.com](https://console.anthropic.com/) |
| `LINKEDIN_ACCESS_TOKEN` | `main.py` | OAuth 2.0 token — [LinkedIn Developer Portal](https://www.linkedin.com/developers/) |
| `LINKEDIN_PERSON_ID` | `main.py` | Format: `urn:li:person:XXXXX` — from `https://api.linkedin.com/v2/userinfo` |
| `TELEGRAM_BOT_TOKEN` | `main.py` | Bot token from [@BotFather](https://t.me/botfather) |
| `TELEGRAM_CHAT_ID` | `main.py` | Chat ID from [@userinfobot](https://t.me/userinfobot) |

### Getting LinkedIn Credentials

1. Create a LinkedIn App at [developers.linkedin.com](https://www.linkedin.com/developers/)
2. Add **"Share on LinkedIn"** and **"Marketing Developer Platform"** products
3. Request OAuth 2.0 scopes:
   - `w_member_social` — publish posts
   - `r_member_social` — read analytics (requires [LinkedIn partner approval](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics); silently skipped if unavailable)
4. Generate an OAuth 2.0 token and retrieve your Person URN from `https://api.linkedin.com/v2/userinfo`

---

## GitHub Actions Setup

### Workflows

| Workflow | Schedule | Entry point | Purpose |
|----------|----------|-------------|---------|
| `update_site.yml` | Mon–Sat 5 AM UTC | `site_pipeline.py` | Build digest + deploy to Vercel |
| `post.yml` | Tue 7 AM UTC | `main.py` | Post to LinkedIn |

### Required Secrets

Go to **Settings → Secrets and variables → Actions** and add:

**For `post.yml`:**
- `ANTHROPIC_API_KEY`
- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_PERSON_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**For `update_site.yml` (site + Vercel deploy):**
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (failure notifications only)
- `VERCEL_TOKEN` — create at [vercel.com/account/tokens](https://vercel.com/account/tokens)
- `VERCEL_ORG_ID` — found in `.vercel/project.json` after running `vercel link`
- `VERCEL_PROJECT_ID` — found in `.vercel/project.json` after running `vercel link`

### Connecting to Vercel (first-time setup)

1. Install the Vercel CLI: `npm i -g vercel`
2. Run `vercel link` in the project root — this creates `.vercel/project.json` with `orgId` and `projectId`
3. Add `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` as GitHub repository secrets
4. On the next `update_site.yml` run, the site is deployed automatically to Vercel after the digest is built

Alternatively: import the GitHub repository directly from the [Vercel dashboard](https://vercel.com/new) and enable the GitHub integration (Vercel auto-deploys on every push to main).

### Manual Trigger

Go to **Actions → LinkedIn AI Post → Run workflow** (optionally provide a custom topic).  
Go to **Actions → Update AI Coding Tools Digest → Run workflow** to rebuild the site on demand.

### Repository Write Permission

Both workflows use `permissions: contents: write` to allow `git push` after each run. The `GITHUB_TOKEN` is used — no additional PAT needed.

The commit message includes `[skip ci]` to prevent recursive workflow runs.

---

## Vercel Static Site

The `site/` directory is deployed as a static site via Vercel:

- **`site/index.html`**: rendered from `template.html` — shows the daily top 3 with scores, summaries, and developer considerations
- **`site/news.json`**: machine-readable digest — also consumed by `main.py` for the LinkedIn pipeline
- **`vercel.json`**: `outputDirectory: "site"`, no build command

The site is rebuilt daily by `update_site.yml` and deployed to Vercel automatically after each successful run.

---

## Troubleshooting

### `site/news.json not found`
Run `site_pipeline.py` first (or trigger the `update_site.yml` workflow manually). `main.py` reads the pre-built digest and aborts if the file is missing.

### `LLM returned invalid JSON`
Claude responses are stripped of markdown fences automatically. If the error persists, check debug logs for the raw response. Ranking failures return an empty list and skip publishing.

### `LinkedIn error 401`
Your `LINKEDIN_ACCESS_TOKEN` has expired. LinkedIn OAuth tokens are short-lived. Generate a new token and update the GitHub Secret.

### `LinkedIn error 422`
Usually a malformed payload or API version mismatch. Check `LINKEDIN_VERSION` in `config.py` (currently `202603`) against the [LinkedIn API changelog](https://learn.microsoft.com/en-us/linkedin/marketing/versioning).

### Analytics not collected
The `r_member_social` scope is required. If your token lacks it, every analytics request returns 403 and the pipeline silently skips collection. Check logs for `"403 for REACTION"`. Request the scope through the LinkedIn Developer Portal and regenerate your token.

### Telegram approval timeout
The pipeline waits up to 30 minutes for a tap on the inline buttons. After timeout it skips publishing and sends a notification. Use `--no-confirm` or `SKIP_CONFIRM=1` to bypass approval entirely.

### `history.json` push conflict
If two workflow runs overlap, the second push may be rejected. Re-run the failed workflow — on the next run it fetches the latest `history.json` via checkout and applies cleanly.

### Vercel not deploying
Ensure `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` are set as GitHub secrets. Check the `update_site.yml` run logs for the Vercel CLI output.

---

## Configuration

All constants live in `config.py`. Key extension points:

- **`RSS_FEEDS`** — add or remove RSS sources (30 currently)
- **`CHANGELOG_SOURCES`** — add or remove changelog pages to scrape (8 currently)
- **`CLAUDE_CODE_FEATURE_PAGES`** — docs pages to generate spotlight articles from
- **`FOCUS_TOPICS`** — topics that receive +3 scoring bonus
- **`CODING_FOCUS_TOPICS`** — focus topics for the site pipeline
- **`BANNED_WORDS`** — words prohibited in LinkedIn post copy
- **`MIN_SCORE`** — publication threshold (default: 6)
- **`RANKED_TOP_N`** — candidates returned by the LinkedIn ranker (default: 5)
- **`RANKED_SITE_TOP_N`** — stories shown on the site (default: 3)
- **`ANALYTICS_MIN_AGE_DAYS` / `ANALYTICS_MAX_AGE_DAYS`** — analytics collection window (default: 7–21 days)

---

## License

MIT License — free to use and modify.
