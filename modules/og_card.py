"""Runtime OG / Twitter card generator for analook.

Reuses the visual style of scripts/generate_og_cards.py (the static
cream-on-warm-dark Instrument-Serif brand pipeline). Adds two on-demand
paths the batch script doesn't cover:

  1. render_audit_share_card(product_name, url, score_band, key_stats)
     — used by /api/og/audit/{job_id}.png for share-audit pages.
     Each shared audit gets a custom 1200×630 card with the product
     name in giant Instrument Serif so Twitter/LinkedIn previews tell
     viewers WHAT the audit is about before they click.

  2. render_generic_card(title, accent, subtitle, kicker) — same render
     contract as scripts/generate_og_cards.py::make_card, exposed here
     so other code paths (zh page, dynamic blog) can call it without
     shelling out to the batch script.

Both return a bytes buffer (PNG) so callers can stream straight to HTTP
or cache to disk.
"""
from __future__ import annotations

import logging
import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

W, H = 1200, 630
BG = (10, 10, 10)             # --bg
INK = (245, 241, 235)          # --ink (cream)
INK_MUTED = (161, 161, 160)
INK_FAINT = (107, 104, 100)
ACCENT_ORANGE = (251, 146, 60)

_FONT_DIR = Path(__file__).parent.parent / "static" / "assets" / "fonts"
_INSTRUMENT_REG = _FONT_DIR / "InstrumentSerif-Regular.ttf"
_INSTRUMENT_ITAL = _FONT_DIR / "InstrumentSerif-Italic.ttf"

# Sans fallback — match the script: macOS HelveticaNeue on dev, fall back
# to PIL's bundled DejaVu / FreeSans on Fly. We probe a few common paths.
_SANS_CANDIDATES = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font_reg(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_INSTRUMENT_REG), size=size)


def _font_ital(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_INSTRUMENT_ITAL), size=size)


def _font_sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _SANS_CANDIDATES:
        try:
            if path.endswith(".ttc"):
                return ImageFont.truetype(path, size=size, index=(2 if bold else 0))
            if bold and "Bold" in path:
                return ImageFont.truetype(path, size=size)
            if not bold and "Regular" in path:
                return ImageFont.truetype(path, size=size)
        except (OSError, IOError):
            continue
    # Final fallback — Pillow's default bitmap font won't honor `size` but
    # avoids ImportError in the worst case.
    log.warning("No sans-serif TTF found; falling back to default")
    return ImageFont.load_default()


def _make_backdrop() -> Image.Image:
    """Dark canvas with subtle aurora-style multi-radial glow."""
    img = Image.new("RGB", (W, H), BG)
    # Blue glow upper-left
    blue_mask = Image.new("L", (W, H), 0)
    bd = ImageDraw.Draw(blue_mask)
    cx, cy = 200, 80
    for r in range(700, 100, -20):
        a = int(34 * (1 - (r - 100) / 600))
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    blue_mask = blue_mask.filter(ImageFilter.GaussianBlur(80))
    blue_color = Image.new("RGB", (W, H), (96, 165, 250))
    img = Image.composite(blue_color, img, blue_mask)
    # Orange glow lower-right
    or_mask = Image.new("L", (W, H), 0)
    od = ImageDraw.Draw(or_mask)
    cx, cy = W - 200, H - 80
    for r in range(550, 100, -20):
        a = int(30 * (1 - (r - 100) / 450))
        od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    or_mask = or_mask.filter(ImageFilter.GaussianBlur(80))
    orange_color = Image.new("RGB", (W, H), ACCENT_ORANGE)
    img = Image.composite(orange_color, img, or_mask)
    return img.convert("RGBA")


def _draw_top_stripe(img: Image.Image) -> None:
    """4px gradient stripe at top — orange→pink→amber."""
    stripe = Image.new("RGB", (W, 4))
    for x in range(W):
        t = x / W
        if t < 0.5:
            f = t * 2
            r = int(251 + (236 - 251) * f)
            g = int(146 + (72 - 146) * f)
            b = int(60 + (153 - 60) * f)
        else:
            f = (t - 0.5) * 2
            r = int(236 + (245 - 236) * f)
            g = int(72 + (158 - 72) * f)
            b = int(153 + (11 - 153) * f)
        for y in range(4):
            stripe.putpixel((x, y), (r, g, b))
    img.paste(stripe, (0, 0))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list:
    words = (text or "").split(" ")
    lines, line = [], ""
    for w in words:
        candidate = (line + " " + w).strip()
        bbox = font.getbbox(candidate)
        if bbox[2] - bbox[0] <= max_w or not line:
            line = candidate
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def _draw_brand_header(draw: ImageDraw.ImageDraw, chip_text: str = "Competitor intelligence") -> None:
    """Top row: 'Analook' brand mark + small uppercase chip on right."""
    brand_font = _font_ital(38)
    draw.text((80, 56), "Analook", font=brand_font, fill=INK)

    chip_font = _font_sans(15, bold=True)
    chip = chip_text.upper()
    bb = chip_font.getbbox(chip)
    cw = bb[2] - bb[0]
    draw.text((W - cw - 80, 67), chip, font=chip_font, fill=INK_MUTED)


def render_audit_share_card(
    product_name: str,
    audit_url: str,
    *,
    score_band: Optional[str] = None,
    key_stats: Optional[list] = None,
) -> bytes:
    """Build the dynamic share card for /share/audit/{job_id}.

    Layout:
        [TOP STRIPE]
        Analook  ·  GROWTH AUDIT
        ─────
                              <accent script>
        Growth audit for
        <product_name>            ← Instrument Serif italic, huge
                              </accent script>
        <key_stats line>   <score_band chip>
        ─────
        gingiris.tools · 2026-06    analook.com/share/audit/...
    """
    img = _make_backdrop()
    _draw_top_stripe(img)
    draw = ImageDraw.Draw(img)
    _draw_brand_header(draw, chip_text="Growth audit · Analook")

    # Top eyebrow
    eyebrow_font = _font_sans(16, bold=True)
    eyebrow = "GROWTH AUDIT FOR"
    draw.text((80, 200), eyebrow, font=eyebrow_font, fill=INK_FAINT)

    # Product name — italic Instrument Serif, sized to fit one line
    pname = (product_name or "your product").strip()
    pname = pname[:36] + "…" if len(pname) > 36 else pname
    # Auto-scale: start 130px, shrink until fits
    pname_font = None
    for s in (140, 130, 118, 104, 92, 82, 72):
        f = _font_ital(s)
        bb = f.getbbox(pname)
        if (bb[2] - bb[0]) <= W - 160:
            pname_font = f
            break
    pname_font = pname_font or _font_ital(72)
    draw.text((80, 232), pname, font=pname_font, fill=INK)

    # Key stats line — small uppercase mono-like meta
    if key_stats:
        stats_str = "  ·  ".join(s for s in key_stats[:3] if s)
        stats_font = _font_sans(17, bold=False)
        draw.text((80, 430), stats_str.upper(), font=stats_font, fill=INK_MUTED)

    # Score band chip (right side, small pill)
    if score_band:
        chip_font = _font_sans(16, bold=True)
        chip = score_band.upper()
        bb = chip_font.getbbox(chip)
        cw = bb[2] - bb[0]
        # Pill bg
        pad_x, pad_y = 18, 10
        pill_x = W - cw - 2 * pad_x - 80
        pill_y = 422
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + cw + 2 * pad_x, pill_y + 36],
            radius=18,
            fill=(20, 20, 22),
            outline=ACCENT_ORANGE,
            width=1,
        )
        draw.text((pill_x + pad_x, pill_y + 8), chip, font=chip_font, fill=ACCENT_ORANGE)

    # Bottom: tagline + URL
    tag_font = _font_sans(16, bold=False)
    draw.text((80, H - 80), "60-second teardown across SEO, traffic, social, PH, GitHub, pricing.",
              font=tag_font, fill=INK_MUTED)
    url_font = _font_sans(14, bold=True)
    url_display = (audit_url or "analook.com")
    if url_display.startswith("https://"):
        url_display = url_display[8:]
    if url_display.startswith("http://"):
        url_display = url_display[7:]
    url_display = url_display[:60]
    draw.text((80, H - 48), url_display.upper(), font=url_font, fill=INK_FAINT)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_generic_card(
    title: str,
    accent: Optional[str],
    subtitle: str,
    kicker: str,
) -> bytes:
    """Same shape as scripts/generate_og_cards.py::make_card, but returns
    bytes instead of writing to disk. Use when you need a one-off card
    (e.g. dynamically per-blog from a script or per-zh-page).
    """
    img = _make_backdrop()
    _draw_top_stripe(img)
    draw = ImageDraw.Draw(img)
    _draw_brand_header(draw)

    title_font = _font_reg(86)
    accent_font = _font_ital(86)
    line_h = 96
    title_lines = _wrap_text(title, title_font, max_w=W - 160)[:2]

    total_h = len(title_lines) * line_h + (line_h if accent else 0)
    start_y = (H - total_h) // 2 - 30

    y = start_y
    for line in title_lines:
        draw.text((80, y), line, font=title_font, fill=INK)
        y += line_h
    if accent:
        draw.text((80, y), accent, font=accent_font, fill=ACCENT_ORANGE)
        y += line_h

    sub_font = _font_sans(24, bold=False)
    draw.text((80, H - 130), subtitle, font=sub_font, fill=INK_MUTED)
    kicker_font = _font_sans(16, bold=True)
    draw.text((80, H - 60), kicker.upper(), font=kicker_font, fill=INK_FAINT)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
