import os
from pathlib import Path

RSS_FEEDS = {
    # --- AI Labs ---
    "OpenAI":             "https://openai.com/news/rss.xml",
    "Anthropic":          "https://www.anthropic.com/rss.xml",
    "Google DeepMind":    "https://deepmind.google/blog/rss.xml",
    "Google AI Blog":     "https://blog.google/technology/ai/rss/",
    "Microsoft Research": "https://www.microsoft.com/en-us/research/feed/",

    # --- Opinionated / analytical voices (Simone Rizzo editorial DNA) ---
    "Ethan Mollick (One Useful Thing)": "https://www.oneusefulthing.org/feed",
    "Gary Marcus":                       "https://garymarcus.substack.com/feed",
    "AI Snake Oil":                      "https://aisnakeoil.substack.com/feed",
    "The Algorithmic Bridge":            "https://thealgorithmicbridge.substack.com/feed",
    "Matt Turck":                        "https://mattturck.com/feed/",
    "Benedict Evans":                    "https://www.ben-evans.com/benedictevans/rss.xml",
    "Simon Willison":                    "https://simonwillison.net/atom/everything/",
    "Interconnects":                     "https://www.interconnects.ai/feed",
    "Latent Space":                      "https://www.latent.space/feed",
    "The Gradient":                      "https://thegradient.pub/rss/",
    "The Batch (deeplearning.ai)":       "https://www.deeplearning.ai/the-batch/feed/",

    # --- Practitioner researchers ---
    "Sebastian Raschka":  "https://magazine.sebastianraschka.com/feed",
    "Chip Huyen":         "https://huyenchip.com/feed.xml",
    "Eugene Yan":         "https://eugeneyan.com/feed.xml",
    "Lilian Weng":        "https://lilianweng.github.io/index.xml",
    "Hamel Husain":       "https://hamel.dev/feed.xml",
    "Jay Alammar":        "https://newsletter.languagemodels.co/feed",

    # --- Industry news ---
    "TechCrunch AI":  "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",

    # --- Frameworks & tools (selected, high signal) ---
    "Hugging Face":   "https://huggingface.co/blog/feed.xml",
    "LangChain Blog": "https://blog.langchain.dev/rss/",
}

FOCUS_TOPICS = (
    "AI agents, agent orchestration, multi-agent systems, "
    "agent harness, agent test harness, agent scaffolding, agent evaluation frameworks, "
    "agent reliability, agent robustness, agent observability, agent tracing, "
    "goal-driven agents, goal-conditioned agents, task planning agents, "
    "autonomous agents, self-improving agents, recursive self-improvement, "
    "Claude Code, OpenAI Codex / Operator, "
    "LangChain, LangGraph, LlamaIndex, AutoGen, CrewAI, DSPy, LangSmith, Haystack, "
    "AI security, LLM security, model security, "
    "prompt injection, indirect prompt injection, jailbreaking, adversarial prompts, "
    "red-teaming, red team, LLM red team, adversarial evaluation, "
    "AI safety, model safety, AI alignment, AI risk, "
    "data poisoning, training data attacks, backdoor attacks, "
    "AI governance, AI regulation, EU AI Act, responsible AI, "
    "model robustness, out-of-distribution, hallucination detection, "
    "guardrails, content moderation, output filtering, "
    "mechanistic interpretability, model interpretability, neural network interpretability, "
    "circuits, superposition, features, sparse autoencoders, SAE, "
    "model internals, attention heads, MLP layers, residual stream, "
    "Chris Olah, Anthropic interpretability, transformer circuits, "
    "DSPy, prompt optimization, few-shot optimization, compiled prompts, "
    "LangSmith, LLM observability, LLM tracing, LLM evaluation, prompt monitoring, "
    "Haystack, deepset, document QA pipeline, retrieval pipeline, "
    "native multimodality, natively multimodal, vision-language model, VLM, "
    "multimodal agents, multimodal reasoning, image + text, audio + text, "
    "GPT-4o, Gemini multimodal, Claude multimodal, multimodal LLM, "
    "LLM capabilities, emergent capabilities, reasoning models, chain-of-thought, "
    "tree-of-thought, reflection, self-critique, model self-evaluation, "
    "instruction following, alignment, RLHF, RLAIF, constitutional AI, "
    "long-context models, extended context, needle-in-a-haystack, "
    "RAG (retrieval-augmented generation), vector databases, reranking, hybrid search, "
    "context window optimisation, prompt compression, KV-cache, "
    "token optimisation, token budget, token saving, prompt compression, "
    "prompt engineering, prompt design, system prompt optimisation, prompt templates, "
    "few-shot prompting, zero-shot prompting, chain-of-thought prompting, "
    "structured output, JSON mode, constrained generation, output formatting, "
    "LLM inference cost, API cost reduction, cost-per-token, batching strategies, "
    "prompt caching, KV-cache reuse, speculative decoding, "
    "LLMLingua, Selective Context, AutoCompressor, prompt distillation, "
    "token cost reduction, inference cost, quantisation, "
    "tool use / function calling, MCP (model context protocol), "
    "agent memory, agent skills / capabilities"
)

SOURCE_CATEGORIES = {
    "LLM Efficiency & Prompt Engineering": [
        "Chip Huyen", "Eugene Yan", "Lilian Weng", "Interconnects", "Hamel Husain",
        "Jay Alammar", "Latent Space", "Lakera AI Blog", "The AI Corner", "Maxim AI Blog",
    ],
    "Agentic AI & Frameworks": [
        "LangChain Blog", "LlamaIndex Blog", "CrewAI Blog", "Haystack Blog", "Hugging Face",
        "Omdena Blog", "n8n Blog", "Vellum AI Blog", "Zapier Blog",
    ],
    "AI Labs": [
        "OpenAI", "Anthropic", "Google DeepMind", "Google AI Blog",
    ],
    "Practitioners & Researchers": [
        "Simon Willison", "The Batch (deeplearning.ai)", "Sebastian Raschka",
        "The Gradient", "Microsoft Research",
    ],
    "Industry News": [
        "TechCrunch AI", "VentureBeat AI",
    ],
}

BANNED_WORDS = [
    "game-changer", "revolutionary", "unlock", "empower", "leverage", "synergy",
    "groundbreaking", "orchestration layer", "control loop", "paradigm", "delve", "transformative",
    "unleash", "harness", "redefine", "cutting-edge", "state-of-the-art", "next-gen",
]

MIN_SCORE = 6
RANKED_TOP_N = 5
RANKED_SITE_TOP_N = 5

NEWSLETTER_URL = "https://ai-linkedin-newsletter.vercel.app"

LINKEDIN_API = "https://api.linkedin.com/rest/posts"
LINKEDIN_IMAGES_API = "https://api.linkedin.com/rest/images?action=initializeUpload"
LINKEDIN_VERSION = "202603"
ANALYTICS_ENDPOINT = "https://api.linkedin.com/rest/memberCreatorPostAnalytics"
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
ANALYTICS_MIN_AGE_DAYS = 7
ANALYTICS_MAX_AGE_DAYS = 21

# --- AI Coding Tools site pipeline ---

_ROOT = Path(__file__).parent
NEWS_JSON_PATH = _ROOT / "site" / "news.json"
NEWSLETTER_JSON_PATH = _ROOT / "site" / "newsletter.json"
TEMPLATE_PATH = _ROOT / "site" / "template.html"
SITE_OUTPUT_PATH = _ROOT / "site" / "index.html"

# Fallback og:image per source — used when the article/changelog URL returns no image.
CHANGELOG_SOURCE_HOMEPAGES = {
    "Claude Code":        "https://www.anthropic.com",
    "Claude Code Docs":   "https://www.anthropic.com",
    "Claude API":         "https://www.anthropic.com",
    "Cursor":             "https://www.cursor.com",
    "OpenAI Codex":       "https://openai.com",
    "GitHub Copilot":     "https://github.com/features/copilot",
    "Windsurf":           "https://codeium.com",
    "Aider":              "https://aider.chat",
    "Continue.dev":       "https://www.continue.dev",
    "Amazon Q":           "https://aws.amazon.com/q/developer/",
}

# Changelog/release-notes pages scraped directly (no RSS).
CHANGELOG_SOURCES = {
    "Claude Code":      "https://docs.anthropic.com/en/release-notes/claude-code",
    "Claude API":       "https://docs.anthropic.com/en/whats-new",
    "Cursor":           "https://www.cursor.com/changelog",
    "OpenAI Codex":     "https://platform.openai.com/docs/changelog",
    "GitHub Copilot":   "https://docs.github.com/en/copilot/about-github-copilot/github-copilot-release-notes",
    "Windsurf":         "https://codeium.com/blog",
    "Aider":            "https://aider.chat/CHANGELOG.md",
    "Continue.dev":     "https://github.com/continuedev/continue/releases",
    "Amazon Q":         "https://aws.amazon.com/q/developer/",
}

# Feature spotlight pages — INTENTIONALLY EMPTY.
# Doc-based spotlights generated "fake" news articles from static documentation pages.
# Real Claude Code news comes from CHANGELOG_SOURCES["Claude Code"] above.
# Add an entry here ONLY for a brand-new feature not yet in the release notes feed.
CLAUDE_CODE_FEATURE_PAGES: list[tuple[str, str]] = []

CODING_FOCUS_TOPICS = (
    "Claude Code, Cursor IDE, GitHub Copilot, OpenAI Codex, Windsurf, Codeium, "
    "Amazon Q Developer, Continue.dev, Aider, "
    "AI coding tools, AI code generation, AI code completion, AI pair programming, "
    "agentic coding, autonomous coding agents, coding agent frameworks, "
    "AI IDE integration, AI-assisted development, developer productivity AI, "
    "code review AI, AI refactoring, AI debugging, AI test generation, "
    "MCP (model context protocol), tool use in coding agents, "
    "AI terminal, AI CLI tools, AI shell assistants, "
    "hooks, sub-agents, memory, slash commands, GitHub Actions integration"
)
