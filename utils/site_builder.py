import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _format_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%B %-d, %Y")
    except Exception:
        return iso[:10] if iso else ""


def _render_story_card(story: dict) -> str:
    rank        = story.get("rank", "")
    title       = story.get("title", "")
    url         = story.get("url", "#")
    source      = story.get("source", "")
    published   = _format_date(story.get("published", ""))
    summary     = story.get("summary", "")
    considerations = story.get("considerations", "")
    score       = story.get("score", "")

    image_html = ""
    if story.get("og_image"):
        # onerror hides the element if the URL is broken at display time
        image_html = (
            f'<img class="card-image" src="{story["og_image"]}" alt="{source}"'
            f' loading="lazy" onerror="this.style.display=\'none\'">\n    '
        )

    take_html = ""
    if considerations:
        take_html = (
            f'    <div class="claude-take">\n'
            f'      <p class="claude-take-label">Claude\'s take</p>\n'
            f'      <p class="claude-take-text">{considerations}</p>\n'
            f'    </div>\n'
        )

    score_chip = (
        f'<span class="score-chip">&#9733;&nbsp;{score}/10</span>' if score else ""
    )

    return (
        f'    <article class="story-card">\n'
        f'    {image_html}'
        f'    <div class="card-body">\n'
        f'      <div class="card-top">\n'
        f'        <span class="rank-badge">#{rank}</span>\n'
        f'        <span class="source-chip">{source}</span>\n'
        f'        {score_chip}\n'
        f'      </div>\n'
        f'      <h2 class="story-title">'
        f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h2>\n'
        f'      <p class="story-date">{published}</p>\n'
        f'      <p class="story-summary">{summary}</p>\n'
        f'{take_html}'
        f'      <a class="read-link" href="{url}" target="_blank" rel="noopener noreferrer">'
        f'Read full article &#8594;</a>\n'
        f'    </div>\n'
        f'    </article>'
    )


def build_site(news_data: dict, template_path: str | Path, output_path: str | Path) -> None:
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
