"""匝瑳市 (122351) PDF table extractor.

The source PDF "匝瑳市ごみ収集日地区別一覧" (1648443257_doc_139_0.pdf)
lists 14 districts in a single table with two collection categories:

- 普通ごみ (burnable): weekly day_of_week (月・木 / 火・金 / 水・土)
- 資源(有害)ごみ (recyclable + hazardous): monthly by calendar date
  (e.g., "8日・22日" → collected on the 8th and 22nd of every month)

Day-of-month doesn't fit the day_of_week / week_of_month schema used by
most cities, so this extractor populates the optional `day_of_month`
schedule field added to the schema specifically to cover such cases.

Usage:
    python3 src/extractors/sosa_pdf_extractor.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from time import strftime

import pdfplumber

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "raw" / "chiba" / "122351"
SCHED_DIR = REPO / "data" / "schedules" / "chiba"

CITY_ID = "122351"
CITY_NAME = "匝瑳市"
SOURCE_PAGE = "https://www.city.sosa.lg.jp/page/page003574.html"
PDF_URL = "https://www.city.sosa.lg.jp/data/doc/1648443257_doc_139_0.pdf"
PDF_FILENAME = "1648443257_doc_139_0.pdf"

JP_DAYS = "月火水木金土日"
FULL_TO_HALF = str.maketrans("０１２３４５６７８９", "0123456789")


def _ensure_pdf() -> Path:
    cached = RAW_DIR / PDF_FILENAME
    if cached.exists() and cached.stat().st_size > 1000:
        return cached
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        cached.write_bytes(r.read())
    return cached


# Heuristic threshold (PDF units): when a line break occurs with less than
# this much horizontal room left in the cell, treat it as a forced typographic
# wrap (mid-word) and DO NOT insert a "・" separator. Above this threshold the
# line break is a deliberate visual grouping and the missing "・" separator
# between items is reinserted.
WRAP_REMAINING_THRESHOLD = 35.0


def _join_detail_lines(detail_bbox, page) -> str:
    """Reconstruct an address_detail cell, restoring "・" separators that were
    dropped at deliberate line breaks while leaving forced typographic wraps
    (mid-word) joined without a separator. Parentheticals like "（…除く）"
    are always appended without a "・"."""
    cropped = page.within_bbox(detail_bbox)
    cell_right = detail_bbox[2]
    by_y: dict[float, list] = {}
    for c in cropped.chars:
        by_y.setdefault(round(c["top"], 0), []).append((c["x0"], c["text"]))
    if not by_y:
        return ""
    lines = []
    for y in sorted(by_y):
        chars = sorted(by_y[y])
        text = "".join(t for _x, t in chars)
        right_edge = chars[-1][0]
        lines.append((text, cell_right - right_edge))

    out = lines[0][0]
    for (line, _rem_next), (_prev_line, rem_prev) in zip(lines[1:], lines[:-1]):
        if out.endswith("・"):
            sep = ""
        elif line.startswith("（") or line.startswith("("):
            sep = ""
        elif rem_prev < WRAP_REMAINING_THRESHOLD:
            sep = ""  # forced wrap mid-word
        else:
            sep = "・"  # deliberate visual break — restore separator
        out += sep + line
    return out.strip()


def _parse_weekdays(cell: str | None) -> list[str]:
    if not cell:
        return []
    days: list[str] = []
    for ch in cell:
        if ch in JP_DAYS and ch not in days:
            days.append(ch)
    return days


def _parse_days_of_month(cell: str | None) -> list[int]:
    if not cell:
        return []
    half = cell.translate(FULL_TO_HALF)
    return sorted({int(m.group(0)) for m in re.finditer(r"\d+", half)})


def _build_schedules(weekdays: list[str], dom: list[int]) -> list[dict]:
    schedules: list[dict] = []
    if weekdays:
        schedules.append({
            "waste_type": "burnable",
            "waste_type_ja": "普通ごみ",
            "frequency": "weekly",
            "day_of_week": weekdays,
            "week_of_month": None,
            "day_of_month": None,
            "collection_time": "daytime",
        })
    if dom:
        # 資源(有害)ごみ is collected together — emit both waste types
        # sharing the same monthly calendar dates.
        for waste_type, waste_ja in (
            ("recyclable", "資源ごみ"),
            ("hazardous", "有害ごみ"),
        ):
            schedules.append({
                "waste_type": waste_type,
                "waste_type_ja": waste_ja,
                "frequency": "monthly",
                "day_of_week": None,
                "week_of_month": None,
                "day_of_month": dom,
                "collection_time": "daytime",
            })
    return schedules


def extract() -> dict:
    pdf_path = _ensure_pdf()
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        tables = page.find_tables()
        if not tables:
            raise RuntimeError(f"No tables found in {pdf_path}")
        table = tables[0]

        areas: list[dict] = []
        for row in table.rows:
            cells = row.cells
            if len(cells) < 4 or any(c is None for c in cells[:4]):
                continue
            name_text = page.within_bbox(cells[0]).extract_text() or ""
            regular_text = page.within_bbox(cells[2]).extract_text() or ""
            dom_text = page.within_bbox(cells[3]).extract_text() or ""
            name = name_text.replace("\n", "").strip()
            if not name or "地区名" in name or "普通ごみ" in regular_text:
                continue
            weekdays = _parse_weekdays(regular_text)
            dom = _parse_days_of_month(dom_text)
            schedules = _build_schedules(weekdays, dom)
            if not schedules:
                continue
            areas.append({
                "area_name": name,
                "address_detail": _join_detail_lines(cells[1], page),
                "schedules": schedules,
            })

    waste_types = sorted({s["waste_type"] for a in areas for s in a["schedules"]})
    return {
        "city_id": CITY_ID,
        "city_name": CITY_NAME,
        "source_format": "pdf_table",
        "source_url": SOURCE_PAGE,
        "source_pdf_url": PDF_URL,
        "areas": areas,
        "warnings": [],
        "stats": {
            "total_areas": len(areas),
            "waste_types_found": waste_types,
        },
        "extracted_at": strftime("%Y-%m-%dT%H:%M:%S"),
        "extraction_model": "pdfplumber-sosa-table",
    }


def main() -> int:
    result = extract()
    SCHED_DIR.mkdir(parents=True, exist_ok=True)
    out = SCHED_DIR / f"{CITY_ID}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {out.relative_to(REPO)}: "
        f"{len(result['areas'])} areas, "
        f"{len(result['stats']['waste_types_found'])} waste types "
        f"({result['stats']['waste_types_found']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
