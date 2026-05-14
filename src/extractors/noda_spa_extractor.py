"""野田市 SPA-specific extractor.

野田市 (city_id 122084) publishes its waste schedule through a third-party
service at manage.delight-system.com/threeR/web/calendar — a SPA that
renders the calendar inside <td class="td1"|"td2"|..."> cells.

The SPA accepts `?jichitaiId=nodashi&areaId={N}` URL parameters and
renders that area's monthly calendar without further interaction. By
fetching one month and parsing the per-cell waste-type labels we can
derive the per-area schedule pattern.

Per-area inference rules (applied to one month of calendar data):
- A waste type that appears on every occurrence of a given weekday in
  the month → weekly on that weekday.
- A waste type that appears on a subset of a weekday's occurrences →
  monthly, week_of_month inferred from which weeks it appeared.

Usage:
    python3 src/extractors/noda_spa_extractor.py [--limit N]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parents[2]
CITIES_FILE = REPO / "data" / "cities" / "chiba.json"
SCHEDULES_DIR = REPO / "data" / "schedules" / "chiba"

CITY_ID = "122084"
CITY_NAME = "野田市"
BASE_URL = "https://manage.delight-system.com/threeR/web/calendar?jichitaiId=nodashi"

JP_DAYS = ["日", "月", "火", "水", "木", "金", "土"]

# Map source labels to our standardised waste_type keys
LABEL_MAP = [
    ("可燃ごみ", "burnable", "可燃ごみ"),
    ("不燃ごみ", "non_burnable", "不燃ごみ"),
    ("ペットボトル", "pet_bottles", "ペットボトル"),
    ("紙類", "paper", "古紙"),
    ("ガラスびん", "bottles", "びん"),
    ("衣類", "clothing", "衣類"),
    ("布類", "clothing", "衣類"),
    ("金属類", "metals", "金属類"),
    ("有害ごみ", "hazardous", "有害ごみ"),
    ("プラスチック", "plastic", "プラスチック"),
    ("段ボール", "cardboard", "段ボール"),
    ("資源物", "recyclable", "資源ごみ"),
]


def _classify_label(label: str) -> tuple[str, str] | None:
    for needle, key, ja in LABEL_MAP:
        if needle in label:
            return key, ja
    return None


async def _fetch_area_options(page) -> list[dict]:
    await page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    options = await page.eval_on_selector_all(
        "#cmbArea1 option",
        "(els) => els.map(e => ({val: e.value, text: e.textContent.trim()}))",
    )
    return [
        o for o in options
        if o["val"] and o["val"] != "-" and not o["text"].startswith("※")
    ]


def _parse_calendar_html(html: str) -> dict[int, list[str]]:
    """Return {day_of_month: [waste type label, ...]} from rendered calendar."""
    soup = BeautifulSoup(html, "html.parser")
    cells = soup.select("table td[class*='td']")
    day_to_labels: dict[int, list[str]] = {}
    for c in cells:
        text = c.get_text("\n", strip=True)
        if not text:
            continue
        # Cell text: "1\n可燃ごみ" or "6\n資源物（紙類）\n資源物（ガラスびん類、衣類、布類）"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue
        try:
            day_num = int(lines[0])
        except ValueError:
            continue
        if not (1 <= day_num <= 31):
            continue
        labels = [l for l in lines[1:] if any(kw in l for kw, _, _ in LABEL_MAP)]
        if labels:
            day_to_labels[day_num] = labels
    return day_to_labels


def _infer_schedules(
    day_to_labels: dict[int, list[str]],
    year: int,
    month: int,
) -> list[dict]:
    """Convert calendar observations into per-waste-type schedule entries.

    For each waste_type → list of (day_of_week, week_of_month) occurrences,
    decide if it's weekly (covers all occurrences of that weekday in the
    month) or monthly (specific weeks).
    """
    import calendar

    cal = calendar.Calendar(firstweekday=6)  # Sunday-first
    weekday_of_day = {}
    occurrence_count: dict[int, int] = defaultdict(int)  # weekday → occurrences in month
    occurrence_index: dict[int, dict[int, int]] = defaultdict(dict)
    # weekday → {day_of_month: which_week (1-5)}
    for d in cal.itermonthdays(year, month):
        if d == 0:
            continue
        import datetime
        wd = datetime.date(year, month, d).weekday()  # Mon=0 … Sun=6
        weekday_of_day[d] = wd
        occurrence_count[wd] += 1
        occurrence_index[wd][d] = occurrence_count[wd]

    # waste_type -> {weekday: set of week_numbers it appeared on}
    by_type: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for d, labels in day_to_labels.items():
        if d not in weekday_of_day:
            continue
        wd = weekday_of_day[d]
        week_in_month = occurrence_index[wd][d]
        for label in labels:
            cls = _classify_label(label)
            if not cls:
                continue
            key, _ja = cls
            by_type[key][wd].add(week_in_month)

    # Convert weekday number (Mon=0..Sun=6) to JP single-char (月..日)
    def jp_day(wd_mon0: int) -> str:
        # Mon=0..Sat=5, Sun=6  → 月,火,水,木,金,土,日
        return ["月", "火", "水", "木", "金", "土", "日"][wd_mon0]

    schedules: list[dict] = []
    for waste_type, wd_map in by_type.items():
        ja = next(ja for needle, k, ja in LABEL_MAP if k == waste_type)
        # Aggregate over weekdays
        # If every weekday appears with all weeks of that month → weekly
        weekly_days: list[str] = []
        monthly_weeks_by_day: dict[str, set[int]] = {}
        for wd, weeks_seen in wd_map.items():
            total_occurrences = occurrence_count[wd]
            if len(weeks_seen) == total_occurrences:
                weekly_days.append(jp_day(wd))
            else:
                monthly_weeks_by_day[jp_day(wd)] = weeks_seen
        if weekly_days:
            schedules.append({
                "waste_type": waste_type, "waste_type_ja": ja,
                "frequency": "weekly",
                "day_of_week": sorted(set(weekly_days), key=lambda d: JP_DAYS.index(d) if d in JP_DAYS else 99),
                "week_of_month": None,
            })
        for day, weeks in monthly_weeks_by_day.items():
            schedules.append({
                "waste_type": waste_type, "waste_type_ja": ja,
                "frequency": "monthly",
                "day_of_week": [day],
                "week_of_month": sorted(weeks),
            })
    return schedules


async def _extract_area(page, area_id: str, area_name: str) -> dict | None:
    url = f"{BASE_URL}&areaId={area_id}"
    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(800)
        # Read month/year from page header
        header = await page.evaluate("""
            () => {
                const txt = document.body.innerText.match(/(\\d{4})年(\\d{1,2})月/);
                return txt ? {year: parseInt(txt[1]), month: parseInt(txt[2])} : null;
            }
        """)
        if not header:
            return None
        html = await page.content()
    except Exception as e:
        logging.warning("area %s (%s) fetch failed: %s", area_id, area_name, e)
        return None

    day_labels = _parse_calendar_html(html)
    if not day_labels:
        return None
    schedules = _infer_schedules(day_labels, header["year"], header["month"])
    if not schedules:
        return None
    return {
        "area_name": area_name,
        "address_detail": None,
        "schedules": schedules,
    }


async def main_async(limit: int | None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        options = await _fetch_area_options(page)
        print(f"Found {len(options)} areas in 野田 SPA")
        targets = options[:limit] if limit else options

        areas: list[dict] = []
        for i, opt in enumerate(targets, 1):
            print(f"  [{i}/{len(targets)}] {opt['text']} (areaId={opt['val']})", end=" ", flush=True)
            area = await _extract_area(page, opt["val"], opt["text"])
            if area:
                areas.append(area)
                print(f"→ {len(area['schedules'])} schedules")
            else:
                print("→ no data")
        await b.close()

    # Build result
    from time import strftime
    result = {
        "city_id": CITY_ID,
        "city_name": CITY_NAME,
        "source_format": "spa",
        "source_url": BASE_URL,
        "areas": areas,
        "warnings": [],
        "stats": {
            "total_areas": len(areas),
            "waste_types_found": sorted({
                s["waste_type"]
                for a in areas for s in a["schedules"]
            }),
        },
        "extracted_at": strftime("%Y-%m-%dT%H:%M:%S"),
        "extraction_model": "playwright-noda-spa",
    }
    out_path = SCHEDULES_DIR / f"{CITY_ID}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path.relative_to(REPO)}: {len(areas)} areas, "
          f"{len(result['stats']['waste_types_found'])} waste types")
    return 0


def main() -> int:
    limit = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit = int(arg.split("=")[1])
    return asyncio.run(main_async(limit))


if __name__ == "__main__":
    sys.exit(main())
