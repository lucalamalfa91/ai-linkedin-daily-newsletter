import os

RSS_FEEDS = {
    "OpenAI":             "https://openai.com/news/rss.xml",
    "Anthropic":          "https://www.anthropic.com/rss.xml",
    "Google DeepMind":    "https://deepmind.google/blog/rss.xml",
    "Google AI Blog":     "https://blog.google/technology/ai/rss/",
    "LangChain Blog":     "https://blog.langchain.dev/rss/",
    "LlamaIndex Blog":    "https://www.llamaindex.ai/blog/rss.xml",
    "CrewAI Blog":        "https://www.crewai.com/blog/rss.xml",
    "Haystack Blog":      "https://haystack.deepset.ai/blog/rss.xml",
    "Hugging Face":       "https://huggingface.co/blog/feed.xml",
    "Omdena Blog":        "https://www.omdena.com/blog/rss.xml",
    "n8n Blog":           "https://blog.n8n.io/rss/",
    "Vellum AI Blog":     "https://www.vellum.ai/blog/rss.xml",
    "Zapier Blog":        "https://zapier.com/blog/feeds/latest/",
    "Simon Willison":     "https://simonwillison.net/atom/everything/",
    "The Batch (deeplearning.ai)": "https://www.deeplearning.ai/the-batch/feed/",
    "Sebastian Raschka":  "https://magazine.sebastianraschka.com/feed",
    "The Gradient":       "https://thegradient.pub/rss/",
    "Microsoft Research": "https://www.microsoft.com/en-us/research/feed/",
    "TechCrunch AI":      "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI":     "https://venturebeat.com/category/ai/feed/",
    "Chip Huyen":         "https://huyenchip.com/feed.xml",
    "Eugene Yan":         "https://eugeneyan.com/feed.xml",
    "Lilian Weng":        "https://lilianweng.github.io/index.xml",
    "Interconnects":      "https://www.interconnects.ai/feed",
    "Hamel Husain":       "https://hamel.dev/feed.xml",
    "Jay Alammar":        "https://newsletter.languagemodels.co/feed",
    "Latent Space":       "https://www.latent.space/feed",
    "Lakera AI Blog":     "https://www.lakera.ai/blog/rss.xml",
    "The AI Corner":      "https://www.the-ai-corner.com/feed",
    "Maxim AI Blog":      "https://www.getmaxim.ai/blog/rss.xml",
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

LINKEDIN_API = "https://api.linkedin.com/rest/posts"
LINKEDIN_IMAGES_API = "https://api.linkedin.com/rest/images?action=initializeUpload"
LINKEDIN_VERSION = "202603"
ANALYTICS_ENDPOINT = "https://api.linkedin.com/rest/memberCreatorPostAnalytics"
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
ANALYTICS_MIN_AGE_DAYS = 7
ANALYTICS_MAX_AGE_DAYS = 21
