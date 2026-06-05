#!/usr/bin/env python3
"""Generate per-page Open Graph + Twitter cards for analook.com.

v2 (2026-06-05): Aligned with the dark + Instrument-Serif brand identity.
- Cream-on-warm-dark (#F5F1EB on #0A0A0A) matching the live site
- Instrument Serif Regular for titles, Italic for accent word + brand mark
- Aurora-style multi-radial backdrop (subtle blue + warm orange glow)
- 4px gradient stripe at top (orange→pink→amber) matching site top-accent

Run: python3 scripts/generate_og_cards.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
OUT_DIR = Path(__file__).parent.parent / "static" / "assets" / "og"
FONT_DIR = Path(__file__).parent.parent / "static" / "assets" / "fonts"

FONT_REGULAR = FONT_DIR / "InstrumentSerif-Regular.ttf"
FONT_ITALIC = FONT_DIR / "InstrumentSerif-Italic.ttf"

# (filename, title, accent_word_or_None, subtitle, kicker)
PAGES = [
    ("homepage.png",           "Analyze any competitor in",        "60 seconds",     "AI-powered teardown across 15+ data sources.",                "analook.com"),
    ("pricing.png",            "Pricing",                          None,             "Free 2/mo · Pro $19 · Team $79 · Single $5",                  "analook.com/pricing"),
    ("comparison.png",         "Multi-competitor",                 "Comparison",     "Stack 2–4 competitors side by side, free.",                   "analook.com/comparison"),
    ("docs-mcp.png",           "MCP server for",                   "AI agents",      "io.github.Gingiris-1031/analook · Claude · Cursor",           "analook.com/docs/mcp"),
    ("compare-similarweb.png", "Analook vs",                       "SimilarWeb",     "Free competitive teardown vs $125/mo traffic data.",          "analook.com/compare"),
    ("compare-semrush.png",    "Analook vs",                       "SEMrush",        "Founder-priced competitive intelligence.",                    "analook.com/compare"),
    ("compare-ahrefs.png",     "Analook vs",                       "Ahrefs",         "Broader signals than backlink-only SEO.",                     "analook.com/compare"),
    ("compare-crayon.png",     "Analook vs",                       "Crayon",         "1.5% of enterprise CI cost, founder-led.",                    "analook.com/compare"),
    ("compare-klue.png",       "Analook vs",                       "Klue",           "Founder stack vs enterprise battlecards.",                    "analook.com/compare"),
    ("compare-visualping.png", "Analook vs",                       "Visualping",     "Strategic teardown vs page-change monitoring.",               "analook.com/compare"),
    ("compare-owler.png",      "Analook vs",                       "Owler",          "Strategic depth vs competitor news feed.",                    "analook.com/compare"),
    ("compare-google-trends.png", "Analook vs",                    "Google Trends",  "Beyond the search-interest curve.",                           "analook.com/compare"),
    ("compare-brand24.png",    "Analook vs",                       "Brand24",        "Teardown depth vs social mention monitoring.",                "analook.com/compare"),
    ("compare-kompyte.png",    "Analook vs",                       "Kompyte",        "$19/mo vs $800+/mo enterprise CI.",                           "analook.com/compare"),
    ("alt-similarweb.png",     "7 best SimilarWeb",                "alternatives",   "Free + paid options ranked honestly for 2026.",               "analook.com/alternatives"),
    ("alt-ahrefs.png",         "7 best Ahrefs",                    "alternatives",   "Free + paid SEO tools ranked.",                               "analook.com/alternatives"),
    ("alt-semrush.png",        "7 best SEMrush",                   "alternatives",   "Free + paid marketing intelligence tools.",                   "analook.com/alternatives"),
    ("alt-crayon.png",         "6 best Crayon",                    "alternatives",   "Including a free competitive-intel tool.",                    "analook.com/alternatives"),
    ("alt-klue.png",           "6 best Klue",                      "alternatives",   "From free founder stack to enterprise battlecards.",          "analook.com/alternatives"),
]

BG = (10, 10, 10)            # #0A0A0A
INK = (245, 241, 235)        # #F5F1EB cream-white
INK_MUTED = (160, 160, 158)  # gray-ish warm
INK_FAINT = (108, 104, 100)  # darker warm gray


def font_reg(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_REGULAR), size=size)


def font_ital(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_ITALIC), size=size)


def font_sans(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Inter not bundled — fall back to HelveticaNeue for the small sans labels
    path = "/System/Library/Fonts/HelveticaNeue.ttc"
    return ImageFont.truetype(path, size=size, index=(2 if bold else 0))


def make_backdrop() -> Image.Image:
    """Dark canvas with subtle aurora-style multi-radial glow."""
    img = Image.new("RGB", (W, H), BG)

    # Soft blue glow upper-left
    blue = Image.new("L", (W, H), 0)
    bd = ImageDraw.Draw(blue)
    cx, cy = 200, 80
    for r in range(700, 100, -20):
        a = int(34 * (1 - (r - 100) / 600))
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    blue = blue.filter(ImageFilter.GaussianBlur(80))
    blue_color = Image.new("RGB", (W, H), (96, 165, 250))
    img = Image.composite(blue_color, img, blue)

    # Warm orange glow lower-right
    orange = Image.new("L", (W, H), 0)
    od = ImageDraw.Draw(orange)
    cx, cy = W - 200, H - 80
    for r in range(550, 100, -20):
        a = int(30 * (1 - (r - 100) / 450))
        od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    orange = orange.filter(ImageFilter.GaussianBlur(80))
    orange_color = Image.new("RGB", (W, H), (251, 146, 60))
    img = Image.composite(orange_color, img, orange)

    return img.convert("RGBA")


def draw_top_stripe(img: Image.Image) -> None:
    """4px gradient stripe at top: orange→pink→amber."""
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


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list:
    words = text.split(" ")
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


def make_card(title: str, accent: str, subtitle: str, kicker: str, output: Path) -> None:
    img = make_backdrop()
    draw_top_stripe(img)
    draw = ImageDraw.Draw(img)

    # Brand mark top-left (Instrument Serif italic "Analook")
    brand_font = font_ital(38)
    draw.text((80, 56), "Analook", font=brand_font, fill=INK)

    # Tag chip top-right (small uppercase tracking)
    chip_font = font_sans(15, bold=True)
    chip = "Competitor intelligence".upper()
    bb = chip_font.getbbox(chip)
    cw = bb[2] - bb[0]
    draw.text((W - cw - 80, 67), chip, font=chip_font, fill=INK_MUTED)

    # Title — auto-wrap, vertically centered around 55% height
    title_font = font_reg(86)
    accent_font = font_ital(86)
    line_h = 96

    # Layout: title (regular) + accent (italic) flow as one block
    # First wrap title only
    title_lines = wrap_text(title, title_font, max_w=W - 160)[:2]

    # Where to start drawing title vertically
    total_h = len(title_lines) * line_h + (line_h if accent else 0)
    start_y = (H - total_h) // 2 - 30

    y = start_y
    for line in title_lines:
        draw.text((80, y), line, font=title_font, fill=INK)
        y += line_h

    # Accent line — italic, slightly offset / continuation of title flow
    if accent:
        # If short accent fits on same line as last title word, draw inline; otherwise new line.
        # For simplicity always put on its own line.
        draw.text((80, y), accent, font=accent_font, fill=INK)
        y += line_h

    # Subtitle
    sub_font = font_reg(30)
    sub_y = y + 20
    sub_lines = wrap_text(subtitle, sub_font, max_w=W - 200)[:2]
    for line in sub_lines:
        draw.text((80, sub_y), line, font=sub_font, fill=INK_MUTED)
        sub_y += 42

    # Bottom kicker (URL) — left
    kicker_font = font_sans(20)
    draw.text((80, H - 60), kicker, font=kicker_font, fill=INK_FAINT)

    # Bottom-right small label
    div_font = font_sans(18)
    div = "Free competitor analysis"
    db = div_font.getbbox(div)
    dw = db[2] - db[0]
    draw.text((W - dw - 80, H - 58), div, font=div_font, fill=INK_FAINT)

    img = img.convert("RGB")
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG", optimize=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, title, accent, subtitle, kicker in PAGES:
        out = OUT_DIR / filename
        make_card(title, accent, subtitle, kicker, out)
        print(f"  ✅ {out.relative_to(Path.cwd()) if str(out).startswith(str(Path.cwd())) else out}")
    print(f"\nGenerated {len(PAGES)} cards in {OUT_DIR}")


if __name__ == "__main__":
    main()
