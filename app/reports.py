"""
Client-facing PDF export for the diving comparison calculators.

Builds a one-page A3 (landscape) PDF from the live calculator state: DCN logo and
company details top-right, the key assumptions, the scenario comparison table and
the headline result, with a footer carrying the copyright notice and a disclaimer.
Intended for use as a proposal appendix, shared with clients, or printed.

The page callbacks assemble already-formatted strings and call build_comparison_pdf;
this module owns only the layout, so the two calculators stay the single source of
truth for the numbers.
"""
import io
import os
import datetime

from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, KeepInFrame)
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

_LOGO = os.path.join(os.path.dirname(__file__), "assets", "dcn_logo.png")

NAVY = colors.HexColor("#1e2a6e")
TEAL = colors.HexColor("#0f766e")
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
GRID = colors.HexColor("#cbd5e1")
SOFT = colors.HexColor("#f3f4f6")
WINBG = colors.HexColor("#dcfce7")
WHITE = colors.white

COMPANY_NAME = "DCN Diving B.V."
COMPANY_ADDR = "Van Konijnenburgweg 151, 4612 PL Bergen op Zoom, Netherlands"
DISCLAIMER = (
    "The figures in this document are calculated from the assumptions stated above and are believed to be "
    "correct but are not guaranteed. They are indicative, provided for comparison purposes only, and do not "
    "constitute a binding offer, advice or warranty. DCN Diving B.V. accepts no liability for any decision or "
    "action taken on the basis of this information."
)

PAGE = landscape(A3)            # (width, height) in points
LM = RM = 16 * mm
TM = 44 * mm                    # header band
BM = 26 * mm                    # footer band


def _wrap(canvas, text, x, y, max_w, font, size, leading, color):
    """Draw word-wrapped text; return the y after the last line."""
    canvas.setFont(font, size)
    canvas.setFillColor(color)
    line = ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if stringWidth(trial, font, size) <= max_w:
            line = trial
        else:
            canvas.drawString(x, y, line)
            y -= leading
            line = word
    if line:
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _decorator(title, subtitle):
    def draw(canvas, doc):
        canvas.saveState()
        W, H = PAGE

        # ---- logo + company, top-right ----
        ty = H - 16 * mm
        try:
            img = ImageReader(_LOGO)
            iw, ih = img.getSize()
            dw = 40 * mm
            dh = dw * ih / iw
            canvas.drawImage(img, W - RM - dw, H - 11 * mm - dh, dw, dh, mask="auto")
            ty = H - 11 * mm - dh - 3.5 * mm
        except Exception:
            pass
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(NAVY)
        canvas.drawRightString(W - RM, ty, COMPANY_NAME)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(W - RM, ty - 3.6 * mm, COMPANY_ADDR)

        # ---- title, left ----
        canvas.setFont("Helvetica-Bold", 19)
        canvas.setFillColor(INK)
        canvas.drawString(LM, H - 16 * mm, title)
        canvas.setFont("Helvetica", 10.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(LM, H - 22 * mm, subtitle)

        # header rule
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.8)
        canvas.line(LM, H - TM + 5 * mm, W - RM, H - TM + 5 * mm)

        # ---- footer ----
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.8)
        canvas.line(LM, BM - 1 * mm, W - RM, BM - 1 * mm)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(LM, BM - 5 * mm, "Disclaimer")
        _wrap(canvas, DISCLAIMER, LM, BM - 8.5 * mm, W - LM - RM,
              "Helvetica", 7, 9, MUTED)
        year = datetime.date.today().year
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(LM, 7 * mm, f"\u00a9 {year} {COMPANY_NAME}  \u00b7  All rights reserved.")
        canvas.drawRightString(W - RM, 7 * mm,
                               f"Generated {datetime.date.today():%d %B %Y}")
        canvas.restoreState()
    return draw


def build_comparison_pdf(title, subtitle, assumptions, headers, rows,
                         highlight_col=None, verdict=""):
    """
    title/subtitle : header text (left).
    assumptions    : single pre-formatted string for the grey assumptions strip.
    headers        : list of scenario column titles (N columns).
    rows           : list of (metric_label, [val0, ... val(N-1)]) — values are strings.
    highlight_col  : 0-based scenario index to highlight (the recommended option), or None.
    verdict        : headline result sentence.
    Returns PDF bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=LM, rightMargin=RM,
                            topMargin=TM, bottomMargin=BM, title=title,
                            author=COMPANY_NAME)
    W, _ = PAGE
    avail = W - LM - RM

    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=INK, leading=11)
    lbl = ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=8.5, textColor=MUTED, leading=10)
    head = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=9.5, textColor=WHITE,
                          leading=11, alignment=1)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=9, textColor=INK,
                          leading=11, alignment=1)
    assum_st = ParagraphStyle("assum", fontName="Helvetica", fontSize=8.5, textColor=INK, leading=12)
    verdict_st = ParagraphStyle("verdict", fontName="Helvetica-Bold", fontSize=11,
                                textColor=colors.HexColor("#14532d"), leading=14)

    story = []

    # ---- assumptions strip ----
    a_tbl = Table([[Paragraph("<b>Assumptions</b>&nbsp;&nbsp; " + assumptions, assum_st)]],
                  colWidths=[avail])
    a_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(a_tbl)
    story.append(Spacer(1, 10))

    # ---- comparison table ----
    n = len(headers)
    label_w = 64 * mm
    col_w = (avail - label_w) / n
    col_widths = [label_w] + [col_w] * n

    data = [[Paragraph("", head)] + [Paragraph(h, head) for h in headers]]
    for metric, vals in rows:
        line = [Paragraph(metric, lbl)]
        for v in vals:
            line.append(Paragraph(str(v), cell))
        data.append(line)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRID),
        ("BOX", (0, 0), (-1, -1), 0.6, GRID),
        ("LINEAFTER", (0, 0), (0, -1), 0.6, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if highlight_col is not None:
        cols = [highlight_col] if isinstance(highlight_col, int) else list(highlight_col)
        for hc in cols:
            c = hc + 1
            ts += [
                ("BACKGROUND", (c, 1), (c, -1), WINBG),
                ("BACKGROUND", (c, 0), (c, 0), TEAL),
                ("LINEABOVE", (c, 0), (c, -1), 1.0, TEAL),
                ("LINEBEFORE", (c, 0), (c, -1), 1.0, TEAL),
                ("LINEAFTER", (c, 0), (c, -1), 1.0, TEAL),
                ("LINEBELOW", (c, -1), (c, -1), 1.0, TEAL),
            ]
    tbl.setStyle(TableStyle(ts))
    story.append(tbl)

    # ---- verdict ----
    if verdict:
        story.append(Spacer(1, 12))
        v_tbl = Table([[Paragraph(verdict, verdict_st)]], colWidths=[avail])
        v_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WINBG),
            ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(v_tbl)

    # keep everything on the single page
    frame_h = PAGE[1] - TM - BM
    deco = _decorator(title, subtitle)
    doc.build([KeepInFrame(avail, frame_h, story, mode="shrink")],
              onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()
