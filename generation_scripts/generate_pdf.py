"""
generate_pdf.py — Assemble the full masterclass PDF.

Loads chapter content from pdf_content_*.py modules, builds the story,
generates body PDF via TocDocTemplate, merges with the pre-rendered
cover PDF, and runs preflight checks.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure scripts dir is on path
sys.path.insert(0, "/home/z/my-project/scripts")

from pdf_helpers import (
    TocDocTemplate, build_toc, TOC_TITLE, hr, ACCENT_EMERALD,
    chapter_break, BODY,
)
from pdf_content_ch0_ch1 import chapter_0, chapter_1
from pdf_content_ch2_ch3 import chapter_2, chapter_3
from pdf_content_ch4_ch5_appendix import chapter_4, chapter_5, appendix_a, appendix_b

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer, PageBreak

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

WORK_DIR = Path("/home/z/my-project/work")
DOWNLOAD_DIR = Path("/home/z/my-project/download")
COVER_PDF = WORK_DIR / "cover.pdf"
BODY_PDF = WORK_DIR / "body.pdf"
FINAL_PDF = DOWNLOAD_DIR / "Polymarket_Sports_Arbitrage_Masterclass.pdf"

# Page setup — must match pdf_helpers
PAGE_W, PAGE_H = A4
LEFT_MARGIN = 0.85 * inch
RIGHT_MARGIN = 0.85 * inch
TOP_MARGIN = 0.95 * inch
BOTTOM_MARGIN = 0.95 * inch


def build_story():
    """Assemble the full document story."""
    story = []

    # 1. TOC
    story.extend(build_toc())

    # 2. Chapter 0
    story.extend(chapter_0())

    # 3. Chapter 1
    story.extend(chapter_1())

    # 4. Chapter 2
    story.extend(chapter_2())

    # 5. Chapter 3
    story.extend(chapter_3())

    # 6. Chapter 4
    story.extend(chapter_4())

    # 7. Chapter 5
    story.extend(chapter_5())

    # 8. Appendix A
    story.extend(appendix_a())

    # 9. Appendix B (no chapter break before — flows from A)
    story.append(PageBreak())
    story.extend(appendix_b())

    return story


def build_body_pdf():
    """Generate the body PDF (no cover) using TocDocTemplate."""
    print(f"Building body PDF → {BODY_PDF}")
    doc = TocDocTemplate(
        str(BODY_PDF),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title="Sports Arbitrage on Polymarket — A Quant Developer's Masterclass",
        author="Z.ai",
        creator="Z.ai",
        subject="Quantitative trading and prediction market arbitrage",
    )

    story = build_story()
    print(f"  Story: {len(story)} flowables")

    doc.multiBuild(story)
    print(f"  ✓ Body PDF generated")


def merge_cover_and_body():
    """Merge cover.pdf + body.pdf → final PDF, normalized to A4."""
    from pypdf import PdfReader, PdfWriter

    print(f"Merging cover + body → {FINAL_PDF}")
    A4_W, A4_H = 595.28, 841.89

    def normalize_page(page):
        """Force-scale every page to exact A4 dimensions."""
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        if abs(w - A4_W) > 0.5 or abs(h - A4_H) > 0.5:
            page.scale_to(A4_W, A4_H)
        return page

    writer = PdfWriter()

    # Cover as page 1
    cover_pages = PdfReader(str(COVER_PDF)).pages
    for p in cover_pages:
        writer.add_page(normalize_page(p))

    # Body pages follow
    body_pages = PdfReader(str(BODY_PDF)).pages
    for p in body_pages:
        writer.add_page(normalize_page(p))

    writer.add_metadata({
        "/Title": "Sports Arbitrage on Polymarket — A Quant Developer's Masterclass",
        "/Author": "Z.ai",
        "/Creator": "Z.ai",
        "/Subject": "Quantitative trading and prediction market arbitrage",
    })

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(FINAL_PDF, "wb") as f:
        writer.write(f)

    n_pages = len(cover_pages) + len(body_pages)
    size_kb = os.path.getsize(FINAL_PDF) / 1024
    print(f"  ✓ Final PDF: {n_pages} pages, {size_kb:.0f} KB")


def main():
    # Step 1: Build body PDF
    build_body_pdf()

    # Step 2: Merge with cover
    if not COVER_PDF.exists():
        print(f"ERROR: cover PDF not found at {COVER_PDF}")
        print("Run html2poster.js on cover.html first.")
        sys.exit(1)
    merge_cover_and_body()

    print(f"\n✓ Done. Final PDF: {FINAL_PDF}")


if __name__ == "__main__":
    main()
