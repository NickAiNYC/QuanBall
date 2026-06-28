"""
generate_pdf.py — Masterclass guide PDF generator.

Produces the 60-70 page "Sports Arbitrage on Polymarket" guide using
ReportLab. Cover is rendered separately via Playwright (cover.html) and
merged in via pypdf.

Workflow:
    1. Generate body PDF (this script) — starts with TOC, no cover
    2. Cover PDF already generated from cover.html via html2poster.js
    3. Merge cover + body via pypdf
    4. Run pdf_qa.py + meta.brand + font.check
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# Ensure pdf skill scripts are importable for install_font_fallback
PDF_SKILL_DIR = "/home/z/my-project/skills/pdf"
sys.path.insert(0, os.path.join(PDF_SKILL_DIR, "scripts"))

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm, cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Frame, HRFlowable, Image, KeepTogether,
    NextPageTemplate, PageBreak, PageTemplate, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

# ─────────────────────────────────────────────────────────────────────────────
# Font registration
# ─────────────────────────────────────────────────────────────────────────────

FONT_DIR = "/usr/share/fonts"

pdfmetrics.registerFont(TTFont("FreeSerif", f"{FONT_DIR}/truetype/freefont/FreeSerif.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif-Bold", f"{FONT_DIR}/truetype/freefont/FreeSerifBold.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif-Italic", f"{FONT_DIR}/truetype/freefont/FreeSerifItalic.ttf"))
pdfmetrics.registerFont(TTFont("FreeSerif-BoldItalic", f"{FONT_DIR}/truetype/freefont/FreeSerifBoldItalic.ttf"))
pdfmetrics.registerFont(TTFont("FreeSans", f"{FONT_DIR}/truetype/freefont/FreeSans.ttf"))
pdfmetrics.registerFont(TTFont("FreeSans-Bold", f"{FONT_DIR}/truetype/freefont/FreeSansBold.ttf"))
pdfmetrics.registerFont(TTFont("FreeSans-Italic", f"{FONT_DIR}/truetype/freefont/FreeSansOblique.ttf"))
pdfmetrics.registerFont(TTFont("FreeSans-BoldItalic", f"{FONT_DIR}/truetype/freefont/FreeSansBoldOblique.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSansMono", f"{FONT_DIR}/truetype/dejavu/DejaVuSansMono.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSansMono-Bold", f"{FONT_DIR}/truetype/dejavu/DejaVuSansMono-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSansMono-Oblique", f"{FONT_DIR}/truetype/dejavu/DejaVuSansMono-Oblique.ttf"))

registerFontFamily("FreeSerif", normal="FreeSerif", bold="FreeSerif-Bold",
                   italic="FreeSerif-Italic", boldItalic="FreeSerif-BoldItalic")
registerFontFamily("FreeSans", normal="FreeSans", bold="FreeSans-Bold",
                   italic="FreeSans-Italic", boldItalic="FreeSans-BoldItalic")
registerFontFamily("DejaVuSansMono", normal="DejaVuSansMono",
                   bold="DejaVuSansMono-Bold", italic="DejaVuSansMono-Oblique")

# Install font fallback (handles missing glyphs automatically)
try:
    from pdf import install_font_fallback
    install_font_fallback()
except Exception as e:
    print(f"Warning: could not install font fallback: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Palette — Cascade (minimal mode, monochrome harmony)
# ─────────────────────────────────────────────────────────────────────────────

# XL tier: backgrounds
PAGE_BG       = colors.HexColor('#f6f6f5')
SECTION_BG    = colors.HexColor('#eeeeed')

# L tier: surfaces
CARD_BG       = colors.HexColor('#eae9e4')
TABLE_STRIPE  = colors.HexColor('#f0f0ef')

# M tier: structural fills
HEADER_FILL   = colors.HexColor('#645c45')
COVER_BLOCK   = colors.HexColor('#6e6855')

# S tier: edges & icons
BORDER        = colors.HexColor('#d3ccb7')
ICON          = colors.HexColor('#7d6c3a')

# XS tier: emphasis
ACCENT        = colors.HexColor('#a88727')      # warm gold for inline emphasis
ACCENT_EMERALD = colors.HexColor('#0F766E')     # matches cover emerald for KPI accents
ACCENT_AMBER  = colors.HexColor('#B45309')      # amber for warnings

# Typography
TEXT_PRIMARY  = colors.HexColor('#272623')
TEXT_MUTED    = colors.HexColor('#817f77')

# Semantic
SEM_SUCCESS   = colors.HexColor('#487e5a')
SEM_WARNING   = colors.HexColor('#a08348')
SEM_ERROR     = colors.HexColor('#a55149')
SEM_INFO      = colors.HexColor('#557493')

# Code block colors
CODE_BG       = colors.HexColor('#1a1a18')      # dark terminal background
CODE_TEXT     = colors.HexColor('#e5e7eb')      # light text on dark
CODE_COMMENT  = colors.HexColor('#9ca3af')
CODE_KEYWORD  = colors.HexColor('#10B981')      # emerald keywords
CODE_STRING   = colors.HexColor('#F59E0B')      # amber strings

# Table colors (derived)
TABLE_HEADER_COLOR = HEADER_FILL
TABLE_HEADER_TEXT  = colors.white
TABLE_ROW_EVEN     = colors.white
TABLE_ROW_ODD      = TABLE_STRIPE

# ─────────────────────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = A4   # 595.28 x 841.89 pt
LEFT_MARGIN   = 0.85 * inch
RIGHT_MARGIN  = 0.85 * inch
TOP_MARGIN    = 0.95 * inch
BOTTOM_MARGIN = 0.95 * inch
CONTENT_W     = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN  # ≈ 451pt

# ─────────────────────────────────────────────────────────────────────────────
# Paragraph styles
# ─────────────────────────────────────────────────────────────────────────────

styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    name="H1", parent=styles["Heading1"],
    fontName="FreeSans-Bold", fontSize=22, leading=28,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT,
    spaceBefore=18, spaceAfter=10, keepWithNext=True,
)
H1_KICKER = ParagraphStyle(
    name="H1Kicker", fontName="DejaVuSansMono", fontSize=9, leading=12,
    textColor=ACCENT_EMERALD, alignment=TA_LEFT,
    spaceBefore=0, spaceAfter=4,
)
H2 = ParagraphStyle(
    name="H2", parent=styles["Heading2"],
    fontName="FreeSans-Bold", fontSize=15, leading=20,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT,
    spaceBefore=14, spaceAfter=6, keepWithNext=True,
)
H3 = ParagraphStyle(
    name="H3", parent=styles["Heading3"],
    fontName="FreeSans-Bold", fontSize=12, leading=16,
    textColor=HEADER_FILL, alignment=TA_LEFT,
    spaceBefore=10, spaceAfter=4, keepWithNext=True,
)
H4 = ParagraphStyle(
    name="H4", fontName="FreeSans-Bold", fontSize=10.5, leading=14,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT,
    spaceBefore=6, spaceAfter=3, keepWithNext=True,
)

BODY = ParagraphStyle(
    name="Body", parent=styles["BodyText"],
    fontName="FreeSerif", fontSize=10.5, leading=16,
    textColor=TEXT_PRIMARY, alignment=TA_JUSTIFY,
    spaceBefore=0, spaceAfter=8, firstLineIndent=0,
)
BODY_TIGHT = ParagraphStyle(
    name="BodyTight", parent=BODY,
    spaceAfter=4, leading=15,
)
BULLET = ParagraphStyle(
    name="Bullet", parent=BODY,
    leftIndent=18, bulletIndent=4, spaceAfter=4,
    firstLineIndent=0, alignment=TA_LEFT,
)
NUMBERED = ParagraphStyle(
    name="Numbered", parent=BULLET,
    leftIndent=22, bulletIndent=4,
)
CAPTION = ParagraphStyle(
    name="Caption", fontName="FreeSans-Italic", fontSize=9, leading=12,
    textColor=TEXT_MUTED, alignment=TA_CENTER,
    spaceBefore=3, spaceAfter=12,
)
CALLOUT = ParagraphStyle(
    name="Callout", fontName="FreeSerif", fontSize=10, leading=15,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT,
    leftIndent=14, rightIndent=10,
    spaceBefore=6, spaceAfter=10, firstLineIndent=0,
)
CALLOUT_LABEL = ParagraphStyle(
    name="CalloutLabel", fontName="FreeSans-Bold", fontSize=9, leading=12,
    textColor=ACCENT_EMERALD, alignment=TA_LEFT,
    leftIndent=14, spaceBefore=8, spaceAfter=2,
)
MATH = ParagraphStyle(
    name="Math", fontName="FreeSerif-Italic", fontSize=11, leading=16,
    textColor=TEXT_PRIMARY, alignment=TA_CENTER,
    spaceBefore=8, spaceAfter=10, leftIndent=20, rightIndent=20,
)
INLINE_CODE_STYLE = "DejaVuSansMono"

# Code block style (dark theme)
CODE_STYLE = ParagraphStyle(
    name="Code", fontName="DejaVuSansMono", fontSize=8.2, leading=11,
    textColor=CODE_TEXT, alignment=TA_LEFT,
    leftIndent=10, rightIndent=10,
    spaceBefore=0, spaceAfter=0, firstLineIndent=0,
)
CODE_LABEL = ParagraphStyle(
    name="CodeLabel", fontName="DejaVuSansMono-Bold", fontSize=8, leading=11,
    textColor=CODE_TEXT, alignment=TA_LEFT,
    leftIndent=10, rightIndent=10,
    spaceBefore=0, spaceAfter=4, firstLineIndent=0,
)

# TOC styles
TOC_TITLE = ParagraphStyle(
    name="TOCTitle", fontName="FreeSans-Bold", fontSize=20, leading=26,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT, spaceAfter=18,
)
TOC_L0 = ParagraphStyle(
    name="TOCL0", fontName="FreeSans-Bold", fontSize=11, leading=18,
    leftIndent=0, textColor=TEXT_PRIMARY,
)
TOC_L1 = ParagraphStyle(
    name="TOCL1", fontName="FreeSerif", fontSize=10, leading=15,
    leftIndent=20, textColor=TEXT_PRIMARY,
)
TOC_L2 = ParagraphStyle(
    name="TOCL2", fontName="FreeSerif-Italic", fontSize=9.5, leading=14,
    leftIndent=40, textColor=TEXT_MUTED,
)

# ─────────────────────────────────────────────────────────────────────────────
# TocDocTemplate
# ─────────────────────────────────────────────────────────────────────────────

class TocDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, **kw)
        # Single frame for body content
        frame = Frame(
            LEFT_MARGIN, BOTTOM_MARGIN,
            CONTENT_W, PAGE_H - TOP_MARGIN - BOTTOM_MARGIN,
            id="body", showBoundary=0,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )
        self.addPageTemplates([
            PageTemplate(id="Body", frames=[frame], onPage=self._draw_header_footer),
        ])

    def _draw_header_footer(self, canvas, doc):
        """Draw header rule and footer with page number."""
        canvas.saveState()

        # Header: title left, version right
        canvas.setFont("DejaVuSansMono", 7.5)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawString(LEFT_MARGIN, PAGE_H - TOP_MARGIN + 22,
                          "SPORTS ARBITRAGE ON POLYMARKET — QUANT MASTERCLASS")
        canvas.drawRightString(PAGE_W - RIGHT_MARGIN, PAGE_H - TOP_MARGIN + 22,
                               "v1.0 · 2026")
        # Header rule
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(LEFT_MARGIN, PAGE_H - TOP_MARGIN + 14,
                    PAGE_W - RIGHT_MARGIN, PAGE_H - TOP_MARGIN + 14)
        # Accent micro-rule
        canvas.setStrokeColor(ACCENT_EMERALD)
        canvas.setLineWidth(1.5)
        canvas.line(LEFT_MARGIN, PAGE_H - TOP_MARGIN + 14,
                    LEFT_MARGIN + 36, PAGE_H - TOP_MARGIN + 14)

        # Footer: page number centered, footer left
        canvas.setFont("DejaVuSansMono", 8)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawCentredString(PAGE_W / 2, BOTTOM_MARGIN - 26,
                                 f"Page {doc.page}")
        canvas.drawString(LEFT_MARGIN, BOTTOM_MARGIN - 26,
                          "Z.AI · QUANT RESEARCH")
        canvas.drawRightString(PAGE_W - RIGHT_MARGIN, BOTTOM_MARGIN - 26,
                               "POLYMARKET · MATIC · USDC")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        """Notify TOC of new headings."""
        if hasattr(flowable, "bookmark_name"):
            level = getattr(flowable, "bookmark_level", 0)
            text = getattr(flowable, "bookmark_text", "")
            key = getattr(flowable, "bookmark_key", "")
            self.notify("TOCEntry", (level, text, self.page, key))


# ─────────────────────────────────────────────────────────────────────────────
# Heading helpers
# ─────────────────────────────────────────────────────────────────────────────

def heading(text: str, style, level: int = 0):
    """Create a heading with TOC bookmark."""
    key = "h_" + hashlib.md5(text.encode()).hexdigest()[:8]
    p = Paragraph(f'<a name="{key}"/>{text}', style)
    p.bookmark_name = key
    p.bookmark_level = level
    p.bookmark_text = text
    p.bookmark_key = key
    return p


def h1(text: str):
    return heading(text, H1, level=0)


def h2(text: str):
    return heading(text, H2, level=1)


def h3(text: str):
    return heading(text, H3, level=2)


def h4(text: str):
    """H4 not added to TOC (level 3 would clutter)."""
    return Paragraph(text, H4)


def kicker(text: str):
    return Paragraph(text.upper(), H1_KICKER)


def body(text: str):
    return Paragraph(text, BODY)


def bullet(text: str):
    return Paragraph(f"• {text}", BULLET)


def numbered(n: int, text: str):
    return Paragraph(f"<b>{n}.</b> {text}", NUMBERED)


# ─────────────────────────────────────────────────────────────────────────────
# Code block
# ─────────────────────────────────────────────────────────────────────────────

def code_block(code: str, label: str = None, max_lines: int = None):
    """Render a code block with light gray background, monospace font,
    and emerald left border accent. Uses Preformatted (which CAN split
    across pages) — not a wrapping Table (which cannot split).
    """
    lines = code.rstrip().split("\n")
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines] + ["# ... (truncated)"]
        code = "\n".join(lines)

    # Escape XML special chars for ReportLab paragraph parser
    escaped = (code.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;"))

    # Splittable code style — light background, dark text, monospace
    code_style = ParagraphStyle(
        name="CodeSplittable", fontName="DejaVuSansMono", fontSize=8.0, leading=11,
        textColor=TEXT_PRIMARY, alignment=TA_LEFT,
        leftIndent=12, rightIndent=8,
        spaceBefore=0, spaceAfter=0, firstLineIndent=0,
        backColor=colors.HexColor("#F3F4F6"),
        borderColor=ACCENT_EMERALD, borderWidth=0, borderPadding=4,
    )

    out = []
    if label:
        label_style = ParagraphStyle(
            name="CodeLblSplittable", fontName="DejaVuSansMono-Bold", fontSize=7.5,
            leading=10, textColor=ACCENT_EMERALD, alignment=TA_LEFT,
            leftIndent=12, spaceBefore=6, spaceAfter=2,
        )
        out.append(Paragraph(f"&#9656; {label}", label_style))

    pre = Preformatted(escaped, code_style)
    out.append(pre)
    out.append(Spacer(1, 10))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Callout box
# ─────────────────────────────────────────────────────────────────────────────

def callout(label: str, text: str, color=ACCENT_EMERALD):
    """Boxed callout with left accent border and label."""
    label_p = Paragraph(f"<font color='#{color.hexval()[2:]}'><b>{label.upper()}</b></font>",
                        ParagraphStyle(name="CL", parent=CALLOUT_LABEL, textColor=color))
    body_p = Paragraph(text, CALLOUT)
    t = Table([[label_p], [body_p]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
    ]))
    return [Spacer(1, 6), t, Spacer(1, 10)]


def warning(text: str):
    return callout("!  Warning", text, color=ACCENT_AMBER)


def info(text: str):
    return callout("i  Note", text, color=SEM_INFO)


def key_insight(text: str):
    return callout("*  Key Insight", text, color=ACCENT_EMERALD)


def math_block(text: str):
    """Centered math expression (plain text, italic)."""
    return Paragraph(text, MATH)


# ─────────────────────────────────────────────────────────────────────────────
# Standard table builder
# ─────────────────────────────────────────────────────────────────────────────

def std_table(headers, rows, col_ratios=None, header_style=None, cell_style=None):
    """Build a standard themed table.

    headers: list of header strings
    rows: list of list of cell strings (or Paragraphs)
    col_ratios: list of floats summing to 1.0; defaults to equal
    """
    n_cols = len(headers)
    if col_ratios is None:
        col_ratios = [1.0 / n_cols] * n_cols
    col_widths = [r * CONTENT_W for r in col_ratios]

    if header_style is None:
        header_style = ParagraphStyle(
            name="TH", fontName="FreeSans-Bold", fontSize=9.5, leading=12,
            textColor=colors.white, alignment=TA_LEFT,
        )
    if cell_style is None:
        cell_style = ParagraphStyle(
            name="TD", fontName="FreeSerif", fontSize=9, leading=12,
            textColor=TEXT_PRIMARY, alignment=TA_LEFT,
        )

    def to_para(x, style):
        if isinstance(x, Paragraph):
            return x
        return Paragraph(str(x), style)

    data = [[to_para(h, header_style) for h in headers]]
    for row in rows:
        data.append([to_para(c, cell_style) for c in row])

    t = Table(data, colWidths=col_widths, hAlign="CENTER", repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, HEADER_FILL),
        ("LINEBELOW", (0, -1), (-1, -1), 0.75, BORDER),
    ]
    # Alternating row colors
    for i in range(1, len(data)):
        if i % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), TABLE_ROW_EVEN))
        else:
            style.append(("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ODD))
    t.setStyle(TableStyle(style))
    return t


def caption(text: str):
    return Paragraph(text, CAPTION)


def hr(color=BORDER, thickness=0.5, space=8):
    return HRFlowable(width="100%", color=color, thickness=thickness,
                      spaceBefore=space, spaceAfter=space)


def soft_break():
    """Vertical spacer."""
    return Spacer(1, 6)


# ─────────────────────────────────────────────────────────────────────────────
# Page-break helpers
# ─────────────────────────────────────────────────────────────────────────────

def chapter_break():
    """Page break before new chapter (only structural breaks allowed)."""
    return PageBreak()


# ─────────────────────────────────────────────────────────────────────────────
# Story builder — TOC
# ─────────────────────────────────────────────────────────────────────────────

def build_toc():
    story = []
    story.append(Paragraph("Table of Contents", TOC_TITLE))
    story.append(hr(color=ACCENT_EMERALD, thickness=1.5, space=4))
    story.append(Spacer(1, 10))

    toc = TableOfContents()
    toc.levelStyles = [TOC_L0, TOC_L1, TOC_L2]
    story.append(toc)
    story.append(PageBreak())
    return story


# Module is intentionally split — chapter content is in build_story()
if __name__ == "__main__":
    print("This module defines helpers. Run build_pdf.py to generate the PDF.")
