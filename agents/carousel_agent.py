import io
import json
import logging
import re

import anthropic

from agents.publisher_agent import upload_document
from config import BANNED_WORDS

log = logging.getLogger(__name__)

_CAROUSEL_SYSTEM = """\
You are writing a LinkedIn carousel (document post) for Luca La Malfa, an AI Architect advising enterprises.
Audience: CTOs, Heads of Innovation, CEOs.

Produce 5 slides plus a short commentary for the LinkedIn post text.

Slide types:
  cover   — big punchy headline (≤10 words) + subtitle with source and date
  content — heading + 3 bullet points (each ≤12 words, concrete and specific)
  cta     — closing question a CTO would wrestle with + call to follow

Commentary: hook ≤8 words + 1 blank line + 2-3 hashtags (include at least one of:
#AIStrategy #EnterpriseAI #AIArchitecture #DigitalTransformation).
The commentary must NOT repeat slide content — it teases the carousel.

Banned words in all text: """ + ", ".join(BANNED_WORDS) + """.

Return ONLY valid JSON — no markdown fences:
{
  "commentary": "<hook text>\\n\\n<hashtags>",
  "slides": [
    {"type": "cover",   "title": "...", "subtitle": "Source · Month Year"},
    {"type": "content", "heading": "What Changed",      "bullets": ["...", "...", "..."]},
    {"type": "content", "heading": "Enterprise Impact", "bullets": ["...", "...", "..."]},
    {"type": "content", "heading": "The Key Insight",   "bullets": ["...", "...", "..."]},
    {"type": "cta",     "question": "...", "cta": "Follow Luca La Malfa for daily AI insights"}
  ]
}
"""


def _strip_json_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    return re.sub(r"\s*```$", "", text)


def generate_slides(story: dict, client: anthropic.Anthropic) -> dict | None:
    """Ask Claude Sonnet to produce slide content + commentary. Returns parsed dict or None."""
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%B %Y")
    body = (story.get("body") or "")[:2000]
    content_section = f"Article content:\n{body}\n\n" if body else ""

    user = (
        f"Story: {story['title']}\n"
        f"Source: {story.get('source', 'AI News')}\n"
        f"Date: {date_str}\n"
        f"{content_section}"
        "Generate 5 slides and a short commentary for this story."
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        temperature=0.7,
        system=[{"type": "text", "text": _CAROUSEL_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    raw = _strip_json_fences(msg.content[0].text)
    log.debug("Carousel raw: %s", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error("Carousel LLM returned invalid JSON: %s", raw)
        return None


def build_pdf(slides: list[dict]) -> bytes:
    """Generate a square PDF carousel from slide dicts using fpdf2. Returns raw bytes."""
    from fpdf import FPDF

    # 135 x 135 mm — optimal LinkedIn carousel square
    PAGE_W = 135
    PAGE_H = 135

    # Colours (R, G, B)
    BG = (10, 25, 47)        # navy #0A192F
    WHITE = (255, 255, 255)
    GRAY = (176, 196, 216)   # #B0C4D8
    ACCENT = (10, 102, 194)  # LinkedIn blue #0A66C2

    pdf = FPDF(unit="mm", format=(PAGE_W, PAGE_H))
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(0, 0, 0)

    def _fill_bg():
        pdf.set_fill_color(*BG)
        pdf.rect(0, 0, PAGE_W, PAGE_H, style="F")

    def _draw_accent_bar(y: float, h: float = 1.5):
        pdf.set_fill_color(*ACCENT)
        pdf.rect(10, y, PAGE_W - 20, h, style="F")

    for slide in slides:
        pdf.add_page()
        _fill_bg()

        stype = slide.get("type", "content")

        if stype == "cover":
            # Accent top bar
            _draw_accent_bar(12)
            # Title — large, white, centered
            pdf.set_font("Helvetica", style="B", size=20)
            pdf.set_text_color(*WHITE)
            pdf.set_xy(10, 30)
            pdf.multi_cell(PAGE_W - 20, 9, slide.get("title", ""), align="C")
            # Subtitle — small, gray, centered near bottom
            pdf.set_font("Helvetica", size=9)
            pdf.set_text_color(*GRAY)
            pdf.set_xy(10, PAGE_H - 22)
            pdf.multi_cell(PAGE_W - 20, 5, slide.get("subtitle", ""), align="C")
            _draw_accent_bar(PAGE_H - 14)

        elif stype == "content":
            _draw_accent_bar(10)
            # Heading
            pdf.set_font("Helvetica", style="B", size=13)
            pdf.set_text_color(*WHITE)
            pdf.set_xy(10, 18)
            pdf.multi_cell(PAGE_W - 20, 7, slide.get("heading", ""), align="L")
            # Bullets
            pdf.set_font("Helvetica", size=10)
            y_cursor = pdf.get_y() + 4
            for bullet in slide.get("bullets", []):
                # Arrow prefix in accent colour
                pdf.set_text_color(*ACCENT)
                pdf.set_xy(10, y_cursor)
                pdf.cell(6, 6, ">")
                # Bullet text in gray
                pdf.set_text_color(*GRAY)
                pdf.set_xy(16, y_cursor)
                pdf.multi_cell(PAGE_W - 26, 6, bullet, align="L")
                y_cursor = pdf.get_y() + 2
            _draw_accent_bar(PAGE_H - 10)

        elif stype == "cta":
            _draw_accent_bar(10)
            # Question
            pdf.set_font("Helvetica", style="B", size=12)
            pdf.set_text_color(*WHITE)
            pdf.set_xy(10, 20)
            pdf.multi_cell(PAGE_W - 20, 7, slide.get("question", ""), align="C")
            # CTA
            pdf.set_font("Helvetica", size=9)
            pdf.set_text_color(*ACCENT)
            pdf.set_xy(10, PAGE_H - 22)
            pdf.multi_cell(PAGE_W - 20, 5, slide.get("cta", ""), align="C")
            _draw_accent_bar(PAGE_H - 14)

    return bytes(pdf.output())


def create_carousel(
    story: dict,
    client: anthropic.Anthropic,
    person_id: str,
    token: str,
) -> tuple[str, str] | None:
    """Generate slides, build PDF, upload to LinkedIn. Returns (document_urn, commentary) or None."""
    result = generate_slides(story, client)
    if not result:
        return None

    slides = result.get("slides", [])
    commentary = result.get("commentary", "")
    if not slides or not commentary:
        log.error("Carousel generation returned empty slides or commentary")
        return None

    log.info("Building carousel PDF — %d slides", len(slides))
    try:
        pdf_bytes = build_pdf(slides)
    except Exception:
        log.exception("PDF build failed")
        return None

    log.info("Uploading carousel PDF (%d bytes)", len(pdf_bytes))
    try:
        document_urn = upload_document(pdf_bytes, person_id, token)
    except Exception:
        log.exception("Document upload failed")
        return None

    return document_urn, commentary
