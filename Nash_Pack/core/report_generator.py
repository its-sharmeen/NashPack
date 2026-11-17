"""PDF report generator using the same declaration-centric view model as the website."""

from html import escape
from statistics import median

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.presentation_engine import build_result_view_model


def _p(value, style):
    if value is None or value == "":
        return Paragraph("—", style)
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)


def _table(data, widths, cell_style, header_style):
    wrapped = []
    for row_index, row in enumerate(data):
        style = header_style if row_index == 0 else cell_style
        wrapped.append([_p(cell, style) for cell in row])
    table = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b9c0c5")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _rule7_text(font):
    if not font:
        return "Not measured\nRule 7: REVIEW"
    height = f"Measured: {font['height_mm']:.3f} mm"
    minimum = f"Required: {font['minimum_mm']:.3f} mm" if font.get("minimum_mm") is not None else "Required: not assigned"
    return f"{height}\n{minimum}\nRule 7: {font['rule7_status_label']}"


def generate_pdf_report(scan_id, product_label, result, output_path):
    presentation = build_result_view_model(result, {"id": scan_id, "product_label": product_label})

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Legal Metrology Inspection #{int(scan_id):04d}",
        author="SIH26034 Inspection System",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("report_title", parent=styles["Title"], alignment=TA_CENTER, fontSize=17, leading=20, spaceAfter=8)
    heading = ParagraphStyle("report_heading", parent=styles["Heading2"], fontSize=12, leading=15, spaceBefore=10, spaceAfter=5)
    cell = ParagraphStyle("report_cell", parent=styles["BodyText"], fontSize=6.8, leading=8.8, wordWrap="CJK")
    head = ParagraphStyle("report_head", parent=cell, fontName="Helvetica-Bold", fontSize=6.7, leading=8.5)
    small = ParagraphStyle("report_small", parent=styles["BodyText"], fontSize=7.5, leading=10)

    story = [
        Paragraph("LEGAL METROLOGY COMPLIANCE REPORT", title),
        Paragraph(f"Inspection #{int(scan_id):04d}", small),
        Spacer(1, 5),
    ]

    summary_rows = [
        ["Item", "Result"],
        ["Product", product_label or "Unlabelled package"],
        ["Status", presentation["header"]["verdict_label"]],
        ["Score", f"{result.get('score', '—')}%"],
        ["Applicable declarations", f"{presentation['font_summary']['applicable']}"],
        ["Font requirements", f"{presentation['font_summary']['passed']}/{presentation['font_summary']['applicable']} passed"],
        ["Views analysed", str(len(presentation["views"]))],
    ]
    story += [Paragraph("Inspection summary", heading), _table(summary_rows, [55 * mm, 123 * mm], cell, head)]

    story += [Paragraph("01 · Applicability", heading), _table([
        ["Item", "Assessment"],
        ["Commodity category", presentation["applicability"]["category"]],
        ["Package context", presentation["applicability"]["context"]],
        ["Scope state", presentation["applicability"]["state"]],
        ["Reason", presentation["applicability"]["reason"]],
    ], [45 * mm, 133 * mm], cell, head)]

    story += [Paragraph("02 · Applicable Legal Metrology declarations + Rule 7", heading)]
    declaration_data = [["Declaration", "Detected value", "Status", "Font height / Rule 7", "Measurement views"]]
    for row in presentation["declarations"]:
        font = row.get("font")
        declaration_data.append([
            f"{row['label']}\n{row['rule']}",
            row["value"] if row["value"] not in (None, "") else "Not detected",
            row["status_label"],
            _rule7_text(font),
            str(font["view_count"]) if font else "—",
        ])
    if len(declaration_data) == 1:
        declaration_data.append(["No applicable declaration", "—", "REVIEW", "Rule 7: REVIEW", "—"])
    story.append(_table(declaration_data, [39 * mm, 38 * mm, 18 * mm, 48 * mm, 20 * mm], cell, head))

    visual = presentation["visual_summary"]
    story += [Paragraph("Visual presentation", heading), _table([
        ["Overall readability", "Overall placement", "Visual status"],
        [visual["readability"], visual["placement"], visual["status_label"]],
    ], [56 * mm, 56 * mm, 51 * mm], cell, head)]

    # Drill-down evidence is kept compact: the main PDF gives the final legal
    # comparison, while glyph-level details remain available on the website.
    measured_rows = []
    for row in presentation["declarations"]:
        font = row.get("font")
        if not font:
            continue
        glyph_count = sum(len(v.get("glyphs") or []) for v in font["views"])
        measured_rows.append([row["label"], font["method"], font["view_count"], glyph_count, font["status_reason"]])
    if measured_rows:
        story += [Paragraph("Measurement evidence", heading), _table(
            [["Declaration", "Method", "Views", "Glyph components", "Assessment"]] + measured_rows,
            [35 * mm, 37 * mm, 15 * mm, 24 * mm, 67 * mm], cell, head
        )]

    if presentation["other_rules"]:
        story += [Paragraph("03 · Other rule checks", heading), _table(
            [["Rule", "Status", "Applicability", "Detected value", "Assessment"]] + [
                [r["rule"], r["status_label"], r["applicability"], r["value"] if r["value"] not in (None, "") else "—", r["reason"]]
                for r in presentation["other_rules"]
            ],
            [22 * mm, 18 * mm, 30 * mm, 35 * mm, 73 * mm], cell, head
        )]

    if presentation["findings"]["warnings"]:
        story += [Paragraph("Action items", heading), _table(
            [["Action / warning"]] + [[warning] for warning in presentation["findings"]["warnings"]],
            [178 * mm], cell, head
        )]

    doc.build(story)
