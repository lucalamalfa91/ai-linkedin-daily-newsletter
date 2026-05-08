import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _format_date(iso: str) -> str:
    """Return a human-readable date like 'May 7, 2026' from an ISO timestamp."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%B %-d, %Y")
    except Exception:
        return iso[:10] if iso else ""


def _render_story_card(story: dict) -> str:
    rank = story.get("rank", "")
    title = story.get("title", "")
    url = story.get("url", "#")
    source = story.get("source", "")
    published = _format_date(story.get("published", ""))
    summary = story.get("summary", "")
    considerations = story.get("considerations", "")
    score = story.get("score", "")

    source_date = " · ".join(filter(None, [source, published]))

    og_image_html = ""
    if story.get("og_image"):
        og_image_html = f'<img class="card-image" src="{story["og_image"]}" alt="" loading="lazy">\n        '

    considerations_html = ""
    if considerations:
        considerations_html = f'<blockquote class="considerations">{considerations}</blockquote>\n        '

    score_badge = f'<span class="score-badge">{score}/10</span>' if score else ""

    return f"""\
    <article class="story-card">
        {og_image_html}<div class="card-meta">
            <span class="rank">#{rank}</span>
            {score_badge}
        </div>
        <h2><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h2>
        <p class="source-date">{source_date}</p>
        <p class="summary">{summary}</p>
        {considerations_html}<a class="read-more" href="{url}" target="_blank" rel="noopener noreferrer">Read full article →</a>
    </article>"""


def build_site(news_data: dict, template_path: str | Path, output_path: str | Path) -> None:
    """Render site/index.html from template and news_data."""
    template = Path(template_path).read_text(encoding="utf-8")

    stories_html = "\n".join(_render_story_card(s) for s in news_data.get("stories", []))

    raw_date = news_data.get("date", "")
    try:
        display_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        display_date = raw_date

    generated_at = news_data.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        generated_at_display = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        generated_at_display = generated_at

    html = (
        template
        .replace("{{ DATE }}", display_date)
        .replace("{{ STORIES_HTML }}", stories_html)
        .replace("{{ GENERATED_AT }}", generated_at_display)
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    log.info("Built site: %s", output_path)
