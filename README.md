# AI LinkedIn Daily Newsletter

Automated LinkedIn AI news pipeline that discovers, curates, and publishes the best AI story of the week — with full editorial quality control powered by Claude.

---

## What It Does

1. **Fetches** AI news from 19 RSS sources spanning AI labs, framework authors, researchers, and industry media
2. **Detects** trending topics by cross-referencing which keywords appear across multiple independent sources
3. **Ranks** up to 40 candidate stories using Claude Haiku (scored 1–10 across 4 editorial dimensions)
4. **Selects** the top-scoring candidate with a valid URL and accessible thumbnail image
5. **Writes** a LinkedIn post using Claude Sonnet — natural, conversational, 2 sentences + hashtags
6. **Critiques** the draft with Claude Haiku; if quality score < 7/10, regenerates the post (up to 1 retry)
7. **Uploads** the article thumbnail to LinkedIn's Images API and attaches it to the post as rich media
8. **Publishes** the post to LinkedIn via REST API (only if story score ≥ 6/10)
9. **Notifies** via Telegram — success with full post preview, or error with exception detail

The entire pipeline runs as a single Python script (`daily_post.py`) with no external configuration files.

---

## Pipeline Architecture

```
fetch_feeds()               — 19 RSS sources, last 7 days, sorted newest-first
       │
       ▼
_detect_trending_topics()   — keyword frequency across sources (proxy for what's hot)
       │
       ▼
_rank_stories()             — Claude Haiku scores up to 40 stories, returns top 5 candidates
       │
       ▼
  for each candidate (ranked best-first):
       │
       ├─ score < 6?         → skip, try next
       ├─ invalid URL?        → skip, try next
       ├─ no og:image?        → skip, try next (thumbnail required for rich post)
       │
       ▼
_write_post()               — Claude Sonnet writes the LinkedIn post text
       │
       ▼
_critique_post()            — Claude Haiku evaluates quality (format, tone, banned words, value)
       │
       ├─ score ≥ 7?         → proceed
       └─ score < 7?         → regenerate post once, re-evaluate, proceed regardless
       │
       ▼
_upload_linkedin_image()    — download og:image, upload to LinkedIn Images API → image URN
       │
       ▼
publish_linkedin()          — POST to LinkedIn REST API with article card + thumbnail
       │
       ▼
send_telegram()             — best-effort notification (never fails the pipeline)
```

---

## RSS Feed Sources

19 sources across 4 categories, all monitored for the **last 7 days**:

| Category | Sources |
|----------|---------|
| **AI Labs** | OpenAI, Anthropic, Google DeepMind, Google AI Blog |
| **Agentic AI & Frameworks** | LangChain Blog, LlamaIndex Blog, Hugging Face |
| **Practitioners & Researchers** | Simon Willison, The Batch (deeplearning.ai), Sebastian Raschka, The Gradient, Microsoft Research |
| **Industry News** | TechCrunch AI, VentureBeat AI |
| **LLM Efficiency & Prompt Engineering** | Chip Huyen, Eugene Yan, Lilian Weng, Interconnects, Hamel Husain |

Feed fetch failures are caught per-source and logged as warnings — a single failing feed never stops the pipeline.

---

## Content Selection Logic

### Step 1 — Trending Topic Detection

Before ranking, the script scans all fetched article titles and summaries to find keywords that appear across **3 or more independent sources**. These become a dynamic "trending now" signal injected into the ranking prompt. This ensures the ranker gives extra weight to topics that multiple outlets are covering simultaneously — a proxy for what's genuinely newsworthy today.

### Step 2 — Scoring Rubric (Claude Haiku)

Each story starts at 0 and points are applied cumulatively, capped at 10:

**Content Quality**
- +2 Concrete announcement: model/product release, open-source launch, measurable benchmark
- +2 From a top-tier source (OpenAI, Anthropic, DeepMind, LangChain, HuggingFace, Simon Willison, and others)
- +1 Technical but accessible — a non-expert can understand why it matters
- −2 Pure opinion or commentary with no concrete news behind it
- −3 Pure product marketing, no substantive technical content
- −2 Vague "AI is transforming X" framing with no concrete details

**Topic Relevance**
- +3 Directly covers a focus topic (see Focus Topics below)
- +1 Clearly AI-relevant but tangential to focus topics
- −3 No meaningful AI angle (pure sysadmin, DevOps, or unrelated tech)

**Trend & Timing**
- +2 Topic appears in the trending list (covered by multiple sources today)
- +1 Topic at the center of current AI discourse: agentic AI, reasoning models, multimodal, cost reduction, AI coding, local/on-device AI
- −1 Story is clearly old news already widely covered days ago

**LinkedIn Profile Value** (for a senior software engineer's personal brand)
- +2 Surprising, specific or counterintuitive — makes someone stop scrolling
- +1 Sharing this positions the author as knowledgeable and ahead of the curve
- −1 Too niche for anyone outside a narrow research subfield
- −2 Sharing this looks like reposting a press release — zero credibility value

The top 5 candidates by score are returned. Any candidate scoring below **6/10** is automatically skipped.

### Step 3 — Focus Topics

The scoring rubric grants +3 to stories directly covering these areas:

- **Agentic systems & orchestration**: AI agents, multi-agent systems, agent evaluation frameworks, agent observability/tracing, autonomous agents, LangChain, LangGraph, LlamaIndex, AutoGen, CrewAI, Claude Code, OpenAI Codex/Operator
- **AI security & safety**: prompt injection, jailbreaking, red-teaming, adversarial evaluation, AI alignment, data poisoning, AI governance, EU AI Act, guardrails, hallucination detection
- **LLM capabilities & reasoning**: emergent capabilities, chain-of-thought, reasoning models, long-context, RLHF, constitutional AI
- **RAG & retrieval**: retrieval-augmented generation, vector databases, reranking, hybrid search, KV-cache
- **Token & prompt optimisation**: prompt engineering, prompt caching, speculative decoding, cost-per-token, batching, LLMLingua, structured output, JSON mode
- **Tooling & protocols**: tool use / function calling, MCP (model context protocol), agent memory

---

## Post Format

Claude Sonnet writes every post following strict constraints:

- **Exactly 2 sentences.** No lists, no breakdowns, no call to action.
- Sentence 1: shares the news simply, with one emoji placed naturally.
- Sentence 2: one plain-language takeaway — why it matters or what's interesting.
- Final line: 2–3 relevant hashtags.
- Max one technical term, explained immediately in plain words.
- Tone: friendly, direct, like a colleague sharing something cool at coffee. Not AI-sounding.

**Banned words**: game-changer, revolutionary, unlock, empower, leverage, synergy, groundbreaking, orchestration layer, control loop, paradigm, delve, transformative.

### Examples of the target tone

```
OpenAI cut GPT-4o prices again. 💰
A few months ago this would've been unthinkable — now it's almost routine.
#AI #OpenAI #LLM
```

```
🚀 Anthropic released a new way to structure AI agents — splitting them into planner, generator and checker roles.
Simpler to debug and more reliable on long tasks — honestly a smart move.
#AI #Agents #Anthropic
```

---

## Quality Gate (Critic Loop)

After the initial draft is generated, Claude Haiku evaluates it on a 1–10 scale:

| Criterion | Max pts | What's checked |
|-----------|---------|---------------|
| Format | 3 | Exactly 2 sentences + one hashtag line, one emoji in sentence 1 |
| Tone | 3 | Natural, not AI-sounding, no hyperbole, no call-to-action |
| Banned words | 2 | None of the 12 prohibited words appear |
| Value | 2 | Clear takeaway, explains why the story matters |

- Score **≥ 7**: post proceeds as-is.
- Score **< 7**: Sonnet rewrites the post once, Haiku re-evaluates. The result proceeds regardless.

---

## LinkedIn Integration

### Thumbnail Upload

For each candidate story, the script fetches the article's `og:image` tag (Open Graph metadata scraped from the article HTML). If no image is found, the candidate is skipped entirely — a thumbnail is required for rich post formatting.

When an image is available:
1. Downloads the image (max 5 MB, must be `image/*` content type)
2. Initialises a LinkedIn Images API upload session
3. Uploads the binary via pre-signed PUT URL
4. Attaches the resulting image URN to the LinkedIn post payload

### API Details

- **Endpoint**: `https://api.linkedin.com/rest/posts`
- **Version header**: `LinkedIn-Version: 202603`
- **Protocol**: `X-Restli-Protocol-Version: 2.0.0`
- **Post visibility**: `PUBLIC`, distributed to `MAIN_FEED`
- **Post ID**: returned in `x-restli-id` response header, included in the Telegram success notification

---

## LLM Model Usage

| Step | Model | Temp | Max tokens | Purpose |
|------|-------|------|------------|---------|
| `_rank_stories` | `claude-haiku-4-5-20251001` | 0 | 500 | Deterministic story scoring |
| `_write_post` | `claude-sonnet-4-6` | 0.7 | 200 | Creative post generation |
| `_critique_post` | `claude-haiku-4-5-20251001` | 0 | 150 | Quality evaluation |

**Prompt caching** is enabled on the static portions of the ranking rubric and the writer system prompt. On repeated runs the invariant content (focus topics, scoring criteria, voice guidelines, examples) is read from Anthropic's cache rather than billed as fresh input tokens.

---

## Quick Start

### Prerequisites

- Python 3.12+
- LinkedIn Developer App with OAuth token
- Anthropic API key
- Telegram Bot (optional, for notifications)

### Local Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/lucalamalfa91/ai-linkedin-daily-newsletter.git
   cd ai-linkedin-daily-newsletter
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv

   # macOS/Linux
   source venv/bin/activate

   # Windows
   venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Create a `.env` file in the project root:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   LINKEDIN_ACCESS_TOKEN=AQV...
   LINKEDIN_PERSON_ID=urn:li:person:XXXXX
   TELEGRAM_BOT_TOKEN=123456789:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```

5. **Run the pipeline**
   ```bash
   python daily_post.py
   ```

---

## Environment Variables

| Variable | Description | How to Get |
|----------|-------------|------------|
| `ANTHROPIC_API_KEY` | Claude API key | [console.anthropic.com](https://console.anthropic.com/) |
| `LINKEDIN_ACCESS_TOKEN` | OAuth 2.0 access token with `w_member_social` scope | [LinkedIn Developer Portal](https://www.linkedin.com/developers/) |
| `LINKEDIN_PERSON_ID` | Your LinkedIn person URN | Format: `urn:li:person:XXXXX` — retrieve from `https://api.linkedin.com/v2/userinfo` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | [@BotFather](https://t.me/botfather) |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | [@userinfobot](https://t.me/userinfobot) |

All 5 variables are required. The script calls `require_env()` at startup and exits immediately if any are missing. Telegram failures after startup do not stop the pipeline.

### Getting LinkedIn Credentials

1. Create a LinkedIn App at [developers.linkedin.com](https://www.linkedin.com/developers/)
2. Add the **"Share on LinkedIn"** product to your app
3. Generate an OAuth 2.0 token with the `w_member_social` scope
4. Retrieve your Person URN from `https://api.linkedin.com/v2/userinfo` after authenticating

---

## GitHub Actions Setup

The workflow in `.github/workflows/daily-post.yml` runs the pipeline on a schedule.

### 1. Add Repository Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add all 5 environment variables:

- `ANTHROPIC_API_KEY`
- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_PERSON_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 2. Enable Actions

The workflow file is already present. GitHub Actions will run it automatically on the configured schedule.

### 3. Manual Trigger

- Go to the **Actions** tab
- Select "Daily LinkedIn AI Post"
- Click **Run workflow**

---

## Expected Log Output

A successful run looks like this:

```
2026-04-17T07:15:01 INFO Fetching OpenAI ...
2026-04-17T07:15:02 INFO Fetching Anthropic ...
2026-04-17T07:15:03 INFO Fetching Google DeepMind ...
...
2026-04-17T07:15:18 INFO Found 84 items in the last 7 days
2026-04-17T07:15:22 INFO Candidate rank=1 score=8 url_valid=True title=Anthropic releases Claude 4 with extended thinking
2026-04-17T07:15:23 INFO Writing post for rank=1 score=8
2026-04-17T07:15:24 INFO Critic attempt=1 score=9 issues=[]
2026-04-17T07:15:25 INFO LinkedIn image uploaded: urn:li:image:C5500AQH...
2026-04-17T07:15:26 INFO LinkedIn post published — ID: urn:li:share:1234567890
2026-04-17T07:15:26 INFO Telegram notification sent
2026-04-17T07:15:26 INFO Pipeline completed successfully
```

### No Qualifying News

If all candidates score below 6/10:
```
2026-04-17T07:15:22 INFO No qualifying news in 7 days — skipping LinkedIn post.
```

---

## Project Structure

```
.
├── .github/
│   └── workflows/
│       └── daily-post.yml    # GitHub Actions schedule & runner
├── daily_post.py             # Entire pipeline — single script, ~680 lines
├── requirements.txt          # anthropic, feedparser, requests
├── .env                      # Local secrets (gitignored)
├── .gitignore
├── CLAUDE.md                 # Instructions for Claude Code
└── README.md                 # This file
```

---

## Troubleshooting

### `LLM returned invalid JSON`
The script strips markdown code fences from LLM responses automatically. If the error persists, check the raw response in debug logs (`log.debug`). Ranking failures return an empty list and skip publishing. Writing failures try the next candidate.

### `LinkedIn error 401`
Your `LINKEDIN_ACCESS_TOKEN` has expired. LinkedIn OAuth tokens are short-lived. Generate a new token from the LinkedIn Developer Portal and update the GitHub Secret.

### `LinkedIn error 422` or `422 Unprocessable Entity`
Usually a malformed payload or an API version mismatch. Check `LINKEDIN_VERSION` in `daily_post.py` (currently `202603`) and compare against the [LinkedIn API changelog](https://learn.microsoft.com/en-us/linkedin/marketing/versioning).

### `Missing environment variable`
Check your `.env` file locally or the repository Secrets in GitHub Actions. All 5 variables must be present — the script will list which ones are missing.

### `No items found in last 7 days`
One or more RSS feeds may be down or returning no recent entries. The script logs a warning per failing source and continues. If all sources fail, `fetch_feeds()` returns an empty list and the pipeline exits cleanly with a Telegram notification.

### Telegram notifications fail
Telegram is best-effort. Failures are logged as warnings and never stop the pipeline. Verify `TELEGRAM_BOT_TOKEN` is valid and that you have sent at least one message to the bot before (required to open a chat session).

### No thumbnail — candidate skipped
If `og:image` cannot be fetched from the article URL (paywalled, non-HTML response, missing OG tags), the candidate is skipped and the next-ranked story is tried. If no candidate has a reachable thumbnail, no post is published.

---

## Contributing

This is a personal automation project, but feel free to fork and adapt it. The main extension points are:

- **`RSS_FEEDS`** — add or remove sources (lines 29–54)
- **`FOCUS_TOPICS`** — adjust which topics get scoring bonuses (lines 57–96)
- **`MIN_SCORE`** — raise or lower the publication threshold (default: 6)
- **`RANKED_TOP_N`** — how many candidates the ranker returns (default: 5)
- **`_write_post` system prompt** — tune voice, format constraints, examples

---

## License

MIT License — free to use and modify.
