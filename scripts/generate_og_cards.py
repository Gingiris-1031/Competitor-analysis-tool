#!/usr/bin/env python3
"""Generate per-page Open Graph + Twitter card images for analook.com.

Style: dark gradient + blue glow + clean typography (HelveticaNeue).
Inspired by the "Neo-Swiss Gradient" pattern from kostja94/social-cards-skills.

Output: 1200x630 PNG files to static/assets/og/

Run locally (requires PIL + macOS HelveticaNeue): python3 scripts/generate_og_cards.py
Pre-generated PNGs are committed to the repo; production does not need to
regenerate at deploy time.
"""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
OUT_DIR = Path(__file__).parent.parent / "static" / "assets" / "og"

# (filename, title, subtitle, kicker)
PAGES = [
    ("homepage.png",          "AI Competitive Intelligence",     "Analyze any competitor's full stack in 60 seconds",       "analook.com"),
    ("pricing.png",           "Pricing",                          "Free 2/mo · Pro $19 · Team $79 · Single $5",              "analook.com/pricing"),
    ("comparison.png",        "Multi-Competitor Comparison",      "Stack 2–4 competitors side by side, free",                "analook.com/comparison"),
    ("docs-mcp.png",          "MCP Server for AI Agents",         "io.github.Gingiris-1031/analook · Claude · Cursor",       "analook.com/docs/mcp"),
    # /compare/*
    ("compare-similarweb.png", "Analook vs SimilarWeb",           "Free competitive teardown vs $125/mo traffic data",       "analook.com/compare"),
    ("compare-semrush.png",    "Analook vs SEMrush",              "Founder-priced competitive intelligence",                 "analook.com/compare"),
    ("compare-ahrefs.png",     "Analook vs Ahrefs",               "Broader signals than backlink-only SEO tools",            "analook.com/compare"),
    ("compare-crayon.png",     "Analook vs Crayon",               "1.5% of enterprise CI cost, founder-led",                 "analook.com/compare"),
    ("compare-klue.png",       "Analook vs Klue",                 "Founder stack vs enterprise battlecards",                 "analook.com/compare"),
    ("compare-visualping.png", "Analook vs Visualping",           "Strategic teardown vs page-change monitoring",            "analook.com/compare"),
    ("compare-owler.png",      "Analook vs Owler",                "Strategic depth vs competitor news feed",                 "analook.com/compare"),
    ("compare-google-trends.png", "Analook vs Google Trends",     "Beyond the search-interest curve",                        "analook.com/compare"),
    ("compare-brand24.png",    "Analook vs Brand24",              "Teardown depth vs social mention monitoring",             "analook.com/compare"),
    ("compare-kompyte.png",    "Analook vs Kompyte",              "$19/mo vs $800+/mo enterprise CI",                        "analook.com/compare"),
    # /alternatives/*
    ("alt-similarweb.png",     "7 Best SimilarWeb Alternatives",  "Free + paid options ranked honestly for 2026",            "analook.com/alternatives"),
    ("alt-ahrefs.png",         "7 Best Ahrefs Alternatives",      "Free + paid SEO tools ranked",                            "analook.com/alternatives"),
    ("alt-semrush.png",        "7 Best SEMrush Alternatives",     "Free + paid marketing intelligence tools",                "analook.com/alternatives"),
    ("alt-crayon.png",         "6 Best Crayon Alternatives",      "Including a free competitive-intel tool",                 "analook.com/alternatives"),
    ("alt-klue.png",           "6 Best Klue Alternatives",        "From free founder stack to enterprise battlecards",       "analook.com/alternatives"),
]

# Font paths (macOS Helvetica Neue, multi-face .ttc)
FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"
FONT_REG_IDX = 0     # Regular
FONT_BOLD_IDX = 2    # Bold


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    idx = FONT_BOLD_IDX if bold else FONT_REG_IDX
    return ImageFont.truetype(FONT_PATH, size=size, index=idx)


def make_gradient_bg() -> Image.Image:
    """Dark navy-to-near-black vertical gradient with subtle blue glow top-left."""
    top = Image.new("RGB", (W, H), (10, 10, 18))       # near-black
    bot = Image.new("RGB", (W, H), (24, 18, 56))       # deep indigo
    mask = Image.linear_gradient("L").resize((W, H))
    bg = Image.composite(bot, top, mask)

    # Blue radial glow top-left
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    # Draw concentric circles with falloff
    cx, cy = -150, -150
    for r in range(1000, 100, -25):
        a = int(40 * (1 - (r - 100) / 900))
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    blue = Image.new("RGB", (W, H), (96, 165, 250))
    bg = Image.composite(blue, bg, glow)

    # Subtle dot grid
    grid = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(grid)
    for x in range(40, W, 40):
        for y in range(40, H, 40):
            gd.ellipse([x - 1, y - 1, x + 1, y + 1], fill=20)
    grid_color = Image.new("RGB", (W, H), (255, 255, 255))
    bg = Image.composite(grid_color, bg, grid)

    return bg.convert("RGBA")


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word wrap to fit within max_w pixels."""
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


def make_card(title: str, subtitle: str, kicker: str, output: Path) -> None:
    img = make_gradient_bg()
    draw = ImageDraw.Draw(img)

    # Top-right brand chip
    brand_font = font(24, bold=True)
    brand_text = "ANALOOK"
    bb = brand_font.getbbox(brand_text)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    chip_x, chip_y = W - bw - 80, 60
    # background pill
    pad = 16
    draw.rounded_rectangle(
        [chip_x - pad, chip_y - 10, chip_x + bw + pad, chip_y + bh + 12],
        radius=8,
        outline=(96, 165, 250, 180),
        width=2,
    )
    draw.text((chip_x, chip_y), brand_text, font=brand_font, fill=(220, 230, 245, 255))

    # Accent stripe top-left (4px tall, blue → purple)
    stripe = Image.new("RGB", (160, 4), (96, 165, 250))
    for x in range(160):
        # blue (96,165,250) → purple (168,85,247)
        t = x / 160
        r = int(96 + (168 - 96) * t)
        g = int(165 + (85 - 165) * t)
        b = int(250 + (247 - 250) * t)
        stripe.putpixel((x, 0), (r, g, b))
        stripe.putpixel((x, 1), (r, g, b))
        stripe.putpixel((x, 2), (r, g, b))
        stripe.putpixel((x, 3), (r, g, b))
    img.paste(stripe, (80, 60))

    # Title (max 2 lines, big bold)
    title_font = font(72, bold=True)
    title_lines = wrap_text(title, title_font, max_w=W - 160)
    title_lines = title_lines[:2]  # cap at 2 lines
    line_h = 88
    title_total_h = len(title_lines) * line_h
    title_start_y = (H - title_total_h) // 2 - 40
    for i, line in enumerate(title_lines):
        draw.text((80, title_start_y + i * line_h), line, font=title_font, fill=(255, 255, 255, 255))

    # Subtitle (single line max)
    sub_font = font(30)
    sub_lines = wrap_text(subtitle, sub_font, max_w=W - 160)[:2]
    sub_y = title_start_y + title_total_h + 30
    for i, line in enumerate(sub_lines):
        draw.text((80, sub_y + i * 42), line, font=sub_font, fill=(190, 200, 220, 255))

    # Bottom-left kicker (URL)
    kicker_font = font(22)
    draw.text((80, H - 70), kicker, font=kicker_font, fill=(130, 145, 170, 255))

    # Bottom-right divider line + tagline
    divider = "AI competitive intelligence · gingiris.tools"
    div_font = font(20)
    db = div_font.getbbox(divider)
    dw = db[2] - db[0]
    draw.text((W - dw - 80, H - 68), divider, font=div_font, fill=(110, 125, 150, 255))

    # Save
    img = img.convert("RGB")
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG", optimize=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, title, subtitle, kicker in PAGES:
        out = OUT_DIR / filename
        make_card(title, subtitle, kicker, out)
        print(f"  ✅ {out.relative_to(Path.cwd()) if str(out).startswith(str(Path.cwd())) else out}")
    print(f"\nGenerated {len(PAGES)} cards in {OUT_DIR}")


if __name__ == "__main__":
    main()
