"""Downloadable reports built from completed searches; no upstream requests."""
import csv
import io
import re
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

FILTERS = ("style", "level", "category", "division", "partner")
EVENT_EXCLUSIONS = ("excludeUncontested", "excludeThreeCouplePodiums")
CSV_COLUMNS = (
    ("Source", "source"),
    ("Date", "date"), ("Competition", "comp"), ("Event", "event"),
    ("Judging category", "category"), ("Division", "division"), ("Age", "age"),
    ("Style", "style"), ("Level", "level"), ("Dances", "dances"),
    ("Entry", "entry"), ("Partner", "partner"), ("Role", "role"),
    ("Place", "place"), ("Entries", "entries"), ("Made final", "made_final"),
    ("Percentile", "percentile"), ("Competition ID", "cid"), ("Event ID", "eid"),
    ("Results URL", "url"),
)


def is_three_couple_podium(event):
    place = event.get("place")
    return (event.get("entries") == 3 and place is not None and 1 <= place <= 3
            and event.get("category") != "Solo" and event.get("role") != "Solo")


def select_events(result, filters):
    if not isinstance(filters, dict) or any(
        (not isinstance(value, bool) if key in EVENT_EXCLUSIONS else
         key not in FILTERS or not isinstance(value, str)) for key, value in filters.items()
    ):
        raise ValueError("Invalid export filters.")
    return [event for event in result["events"]
            if not (filters.get("excludeUncontested") and event.get("entries") == 1)
            and not (filters.get("excludeThreeCouplePodiums") and is_three_couple_podium(event)) and all(
        not value or (event.get(key) or ("(solo)" if key == "partner" else "")) == value
        for key, value in filters.items() if key in FILTERS
    )]


def filename(name, fmt):
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", name or "results").strip("-")[:70] or "results"
    return f"{stem}-results.{fmt}"


def csv_report(events):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([label for label, _ in CSV_COLUMNS])
    for event in events:
        row = []
        for _, key in CSV_COLUMNS:
            value = event.get(key)
            if key == "source":
                value = "O2CM" if value == "o2cm" else "Ballroom Comp Express"
            if isinstance(value, list):
                value = "; ".join(value)
            elif isinstance(value, bool):
                value = "Yes" if value else "No"
            elif value is None:
                value = ""
            # Quoting alone does not prevent spreadsheet formula execution.
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            row.append(value)
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def pdf_report(result, events, filters):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    # ReportLab ships these Unicode fonts, so downloads need no external font service.
    font_dir = Path(reportlab.__file__).parent / "fonts"
    if "BCEReport" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("BCEReport", str(font_dir / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("BCEReportBold", str(font_dir / "VeraBd.ttf")))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("ReportTitle", fontName="BCEReportBold", fontSize=23, leading=29, spaceAfter=6))
    styles.add(ParagraphStyle("ReportBody", fontName="BCEReport", fontSize=9, leading=13, spaceAfter=5))
    styles.add(ParagraphStyle("ReportSection", fontName="BCEReportBold", fontSize=12, leading=16, spaceBefore=13, spaceAfter=7))
    styles.add(ParagraphStyle("ReportCell", fontName="BCEReport", fontSize=7, leading=10))
    styles.add(ParagraphStyle("ReportHead", fontName="BCEReportBold", fontSize=7, leading=10, textColor=colors.white))
    styles.add(ParagraphStyle("ReportNumber", parent=styles["ReportCell"], alignment=TA_RIGHT))

    def p(value, style="ReportBody"):
        return Paragraph(escape(str(value if value is not None else "")), styles[style])

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=36, rightMargin=36,
                            topMargin=36, bottomMargin=38, title=f"{result.get('name', '')} - Results",
                            author="Ballroom Stats Analyzer")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    o2cm = result.get("source") == "o2cm"
    combined = result.get("source") == "all"
    source_label = "ballroomcompexpress.com + results.o2cm.com" if combined else "results.o2cm.com" if o2cm else "ballroomcompexpress.com"
    scope = "; ".join("Uncontested events: excluded" if key == "excludeUncontested" else
                      "Top-3 finishes in 3-couple events: excluded" if key == "excludeThreeCouplePodiums" else
                      f"{key.title()}: {value}" for key, value in filters.items() if value) or "All search results"
    dates = sorted(e["date"] for e in events if e.get("date"))
    story = [p("BALLROOM STATS ANALYZER"), p(result.get("name") or "Dancer results", "ReportTitle"),
             p(("Sources: Ballroom Comp Express + O2CM" if combined else "Source: O2CM | Exact-name search" if o2cm else f"Dancer ID: {result.get('aid') or 'Not specified'}") + f" | Generated {generated}"),
             p(f"Scope: {scope}"),
             p(f"{len(events)} events across {len({e['cid'] for e in events})} competitions" +
               (f" | {dates[0]} to {dates[-1]}" if dates else "")), Spacer(1, 9)]
    if result.get("warnings"):
        story.append(p(" ".join(result["warnings"])))
    placed = [e["place"] for e in events if e.get("place") is not None]
    metrics = [("EVENTS", str(len(events))), ("FIRST PLACES", str(placed.count(1))),
               ("PODIUMS", str(sum(v <= 3 for v in placed))),
               ("FINALS", str(sum(bool(e.get("made_final")) for e in events))),
               ("AVERAGE PLACE", f"{sum(placed) / len(placed):.2f}" if placed else "-")]
    summary = Table([[p(label, "ReportCell") for label, _ in metrics],
                     [p(value, "ReportSection") for _, value in metrics]], colWidths=[doc.width / 5] * 5)
    summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f5f3")),
                                ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.extend([summary, p("Judging categories", "ReportSection")])
    categories = Counter(e.get("category") or "Unclassified" for e in events)
    story.append(p(" | ".join(f"{category}: {count}" for category, count in sorted(categories.items())) or "No events match these filters."))
    story.extend([p("Event results", "ReportSection"),
                  p("Every matching event is included, regardless of the page's row limit. YCN points and opponent comparisons are not included.")])
    rows = [[p(label, "ReportHead") for label in ("Date / competition", "Event", "Judging / role", "Partner", "Place / field")]]
    for e in events:
        rows.append([p(f"{e.get('date') or 'Date unknown'}\n{e['comp']}" +
                       (" | " + ("O2CM" if e.get("source") == "o2cm" else "Ballroom Comp Express") if combined else ""), "ReportCell"),
                     p(e["event"], "ReportCell"), p(f"{e.get('category', '')} / {e.get('role', '')}", "ReportCell"),
                     p(e.get("partner") or "(solo)", "ReportCell"),
                     p(f"{e['place'] if e.get('place') is not None else '-'} / {e.get('entries', '-')}" +
                       (" (final)" if e.get("made_final") else ""), "ReportNumber")])
    if events:
        widths = [doc.width * x for x in (.20, .35, .19, .16, .10)]
        table = LongTable(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
        commands = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17251d")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f5")]),
                    ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor("#17251d"))]
        for i, e in enumerate(events, 1):
            if e.get("place") == 1:
                commands.append(("BACKGROUND", (-1, i), (-1, i), colors.HexColor("#dcfce7")))
        table.setStyle(TableStyle(commands))
        story.append(table)
    else:
        story.append(p("No events match these filters."))

    def footer(canvas, document):
        canvas.setFont("BCEReport", 7)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(36, 22, f"Source: {source_label} | Ballroom Stats Analyzer")
        canvas.drawRightString(landscape(A4)[0] - 36, 22, f"Page {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
