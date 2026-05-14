"""Phase 4: Extract structured waste schedules from crawled pages using Gemini.

Strategy:
- HTML pages: Extract <table> elements, strip attributes (keep rowspan/colspan),
  send clean HTML to Gemini. HTML preserves table structure that markdown loses.
- PDF pages: (future) Render as images and use Gemini multimodal.

Gemini returns compact JSON per area, which we expand to the full schema.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
SCHEDULES_DIR = DATA_DIR / "schedules"
CITIES_DIR = DATA_DIR / "cities"

load_dotenv(DATA_DIR.parent / ".env")

GEMINI_MODEL = "gemini-3.1-pro-preview"


# --- Gemini client ---

class QuotaExhaustedError(Exception):
    pass


def _init_gemini() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=api_key)


def _call_gemini(
    client: genai.Client, prompt: str,
    retries: int = 2, max_output_tokens: int = 65536,
) -> dict | list | None:
    """Call Gemini and parse JSON response, with retries."""
    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt)],
                    ),
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=max_output_tokens,
                ),
            )

            candidate = response.candidates[0]
            finish = getattr(candidate, "finish_reason", None)
            if finish and str(finish) not in ("STOP", "FinishReason.STOP", "1"):
                logger.warning("Gemini finish_reason: %s", finish)

            text = ""
            for part in candidate.content.parts:
                if part.text and not getattr(part, "thought", False):
                    text += part.text
            text = text.strip()

            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str and "per_model_per_day" in err_str:
                raise QuotaExhaustedError(f"Daily quota exhausted for {GEMINI_MODEL}") from e
            logger.warning("Gemini error (attempt %d/%d): %s", attempt + 1, retries + 1, e)
            if attempt < retries:
                time.sleep(2)
    return None


# --- HTML table extraction ---

def extract_schedule_tables(html: str) -> str:
    """Extract schedule tables from HTML, stripping all attributes except rowspan/colspan.

    Returns clean HTML containing only the schedule <table> elements.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    schedule_tables = []
    seen_row_counts = set()

    for t in tables:
        rows = t.find_all("tr")
        if len(rows) < 2:
            continue

        # Check if this looks like a schedule table
        table_text = t.get_text(strip=True)[:500]
        has_waste_keywords = any(
            kw in table_text
            for kw in ["町", "地区", "可燃", "不燃", "ごみ", "収集", "曜", "カレンダー"]
        )
        if not has_waste_keywords:
            continue

        # Deduplicate tables with same content (many pages have display/print duplicates)
        table_content = t.get_text(strip=True)[:200]
        if table_content in seen_row_counts:
            continue
        seen_row_counts.add(table_content)

        # Strip all attributes except rowspan/colspan
        for tag in t.find_all(True):
            allowed = {}
            for attr in ("rowspan", "colspan"):
                if tag.get(attr):
                    allowed[attr] = tag[attr]
            tag.attrs = allowed

        schedule_tables.append(t)

    if not schedule_tables:
        return ""

    return "\n".join(str(t) for t in schedule_tables)


def classify_source(html: str, markdown: str) -> str:
    """Classify the source format.

    Returns: "html_table", "text", "pdf_links", or "insufficient"
    """
    # Check HTML for tables first
    if html and len(html) > 500:
        tables_html = extract_schedule_tables(html)
        if tables_html and len(tables_html) > 200:
            return "html_table"

    # Fall back to markdown analysis
    if not markdown or len(markdown) < 200:
        return "insufficient"

    has_waste = any(kw in markdown for kw in ["可燃", "不燃", "ごみ", "収集"])
    has_pdf = ".pdf" in markdown.lower()

    if has_pdf and has_waste:
        return "pdf_links"
    if has_waste and len(markdown) > 1000:
        return "text"
    return "insufficient"


# --- Extraction prompt ---

EXTRACTION_PROMPT = """あなたは日本の自治体のごみ収集スケジュールデータを構造化するエキスパートです。

以下は「{city_name}」（city_id: {city_id}）のごみ収集スケジュールデータです。
{format_note}

---
{content}
---

各行を解析し、以下のコンパクトなJSON配列に変換してください。

出力形式 — 各エリアを1オブジェクトで表現：
[
  {{
    "a": "町名＋丁目",
    "d": "番地詳細（なければ空文字）",
    "t": "daytime/nighttime（なければ空文字）",
    "b": "月木",
    "nb": "2木",
    "r": "水",
    "p": "水",
    "v": "水"
  }}
]

フィールド説明：
- a: area_name（町名＋丁目）
- d: address_detail（番地詳細）
- t: collection_time（昼→daytime, 夜→nighttime）
- b: burnable（可燃ごみ/燃えるごみ/普通ごみ）の収集日
- nb: non_burnable（不燃ごみ）の収集日
- 以下はページのカラムに応じて使い分け：
  - r: recyclable（資源ごみ）, p: pet_bottles（ペットボトル）, v: valuables（有価物）
  - bn: bottles（びん）, c: cans（缶）, pp: paper（古紙/紙類）, cl: clothing（衣類/布類）
  - pl: plastic（プラスチック）, m: metals（金属類）, h: hazardous（有害ごみ）
  - br: branches（木の枝/刈り草）, cd: cardboard（段ボール）

収集日の表記ルール：
- 「月木」「火金」「水土」= 毎週（曜日をそのまま記載）
- 「2木」「3火」= 第N回目の曜日（数字＋曜日をそのまま記載）
- 「ー」や該当なし = 空文字

すべての地区を漏れなく出力してください。省略禁止。
JSON配列のみを出力してください。"""


# --- Compact output expansion ---

COMPACT_FIELD_MAP = {
    "b": ("burnable", "可燃ごみ"),
    "nb": ("non_burnable", "不燃ごみ"),
    "r": ("recyclable", "資源ごみ"),
    "p": ("pet_bottles", "ペットボトル"),
    "v": ("valuables", "有価物"),
    "bn": ("bottles", "びん"),
    "c": ("cans", "缶"),
    "pp": ("paper", "古紙"),
    "cl": ("clothing", "衣類"),
    "pl": ("plastic", "プラスチック"),
    "m": ("metals", "金属類"),
    "h": ("hazardous", "有害ごみ"),
    "br": ("branches", "木の枝・刈り草"),
    "cd": ("cardboard", "段ボール"),
}


def _parse_schedule_value(val: str) -> dict | None:
    """Parse a compact schedule value like '月木', '2木', 'on_demand'.

    Handles Gemini output variations:
    - Clean: "2木", "1,3火", "月木"
    - With 第/曜日: "第2木", "第1・第3火曜日", "第2,4火曜"
    - Split format: "1火3火", "第1火・第3火"
    - Duplicated days: "火火" → deduplicated to "火"
    """
    if not val or val == "null":
        return None

    val = val.strip()

    if val in ("予約制", "on_demand"):
        return {"frequency": "on_demand", "day_of_week": None, "week_of_month": None}

    # Normalize: strip 第, 曜日, 曜, whitespace, ・between 第N groups
    normalized = val
    normalized = re.sub(r'第', '', normalized)
    normalized = re.sub(r'曜日?', '', normalized)
    normalized = re.sub(r'\s+', '', normalized)

    # Monthly: "2木", "3火", "1・3金", "2,4水", "1火3火"
    # After normalization, "第2,4火曜日" → "2,4火", "第1火・第3火" → "1火・3火"
    days_in_val = re.findall(r'[月火水木金土日]', normalized)
    weeks_in_val = re.findall(r'[0-9]', normalized)

    if weeks_in_val and days_in_val:
        # Has both week numbers and day chars → monthly
        unique_days = list(dict.fromkeys(days_in_val))
        weeks = [int(w) for w in weeks_in_val]
        # Validate week numbers (1-5 only)
        weeks = sorted(set(w for w in weeks if 1 <= w <= 5))
        if weeks and len(unique_days) == 1:
            return {"frequency": "monthly", "day_of_week": unique_days, "week_of_month": weeks}
        elif weeks and len(unique_days) > 1:
            # Multiple different days with week numbers (rare) — treat each day as monthly
            # Return first day with all weeks (best effort)
            return {"frequency": "monthly", "day_of_week": [unique_days[0]], "week_of_month": weeks}

    # Weekly: "月木", "火金", "水土", "月", etc.
    if days_in_val:
        unique_days = list(dict.fromkeys(days_in_val))
        return {"frequency": "weekly", "day_of_week": unique_days, "week_of_month": None}

    return None


def _expand_compact_areas(compact_list: list[dict]) -> list[dict]:
    """Expand compact Gemini output to full schema."""
    areas = []
    for item in compact_list:
        if not isinstance(item, dict):
            continue

        if "schedules" in item:
            areas.append(item)
            continue

        area_name = item.get("a", item.get("area_name", ""))
        address_detail = item.get("d", item.get("address_detail", ""))
        collection_time = item.get("t", "")

        ct = None
        if collection_time == "nighttime":
            ct = "nighttime"
        elif collection_time == "daytime":
            ct = "daytime"

        schedules = []
        for key, (waste_type, waste_type_ja) in COMPACT_FIELD_MAP.items():
            val = item.get(key, "")
            if not val:
                continue
            parsed = _parse_schedule_value(str(val))
            if parsed:
                schedule = {
                    "waste_type": waste_type,
                    "waste_type_ja": waste_type_ja,
                    **parsed,
                }
                if ct and waste_type == "burnable":
                    schedule["collection_time"] = ct
                schedules.append(schedule)

        if schedules:
            areas.append({
                "area_name": area_name,
                "address_detail": address_detail or None,
                "schedules": schedules,
            })

    return areas


def _schedule_signature(s: dict) -> tuple:
    """Hashable comparison key for a schedule entry."""
    return (
        s.get("frequency"),
        tuple(s.get("day_of_week") or []),
        tuple(s.get("week_of_month") or []),
        s.get("collection_time"),
    )


def _deduplicate_areas(areas: list[dict]) -> list[dict]:
    """Merge areas sharing the same (area_name, address_detail).

    Areas are merged when their schedules are compatible (no waste_type appears
    in two areas with different (frequency, days, weeks)). When schedules
    conflict — i.e. multiple PDFs reported the same area name for distinct
    sub-zones — the entries are kept separate, with area_name suffixed `#N`
    to flag that the source did not disambiguate them.
    """
    from collections import OrderedDict

    groups: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for area in areas:
        name = area.get("area_name", "")
        detail = area.get("address_detail") or ""
        groups.setdefault((name, detail), []).append(area)

    result: list[dict] = []
    for (name, _detail), group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        # Detect schedule conflicts within the group
        type_sigs: dict[str, tuple] = {}
        conflict = False
        for area in group:
            for s in area.get("schedules", []):
                wt = s.get("waste_type")
                if not wt:
                    continue
                sig = _schedule_signature(s)
                if wt in type_sigs and type_sigs[wt] != sig:
                    conflict = True
                    break
                type_sigs.setdefault(wt, sig)
            if conflict:
                break

        if conflict:
            # Keep each variant; disambiguate via #N suffix so downstream
            # consumers can tell them apart and source maintainers can fix.
            for i, area in enumerate(group, 1):
                disamb = dict(area)
                disamb["area_name"] = f"{name} #{i}" if name else f"area #{i}"
                result.append(disamb)
        else:
            merged = dict(group[0])
            merged["schedules"] = list(group[0].get("schedules", []))
            seen_types = {s.get("waste_type") for s in merged["schedules"]}
            for area in group[1:]:
                for s in area.get("schedules", []):
                    if s.get("waste_type") not in seen_types:
                        merged["schedules"].append(s)
                        seen_types.add(s.get("waste_type"))
            result.append(merged)

    return result


def _validate_and_fix_areas(areas: list[dict], warnings: list[str]) -> list[dict]:
    """Post-processing fixes for common extraction errors."""
    for area in areas:
        for schedule in area.get("schedules", []):
            # Fix duplicate day_of_week entries
            days = schedule.get("day_of_week")
            if days and len(days) != len(set(days)):
                unique_days = list(dict.fromkeys(days))
                # If same day repeated (e.g. ["火","火"]), likely monthly not weekly
                if len(unique_days) == 1 and schedule.get("frequency") == "weekly":
                    schedule["frequency"] = "monthly"
                    schedule["week_of_month"] = [1, 3]  # common default for biweekly
                    warnings.append(
                        f"{area.get('area_name')}: {schedule['waste_type']} "
                        f"duplicate day {days} → assumed monthly 1,3"
                    )
                schedule["day_of_week"] = unique_days

            # Validate week_of_month values (must be 1-5)
            weeks = schedule.get("week_of_month")
            if weeks:
                valid_weeks = [w for w in weeks if isinstance(w, int) and 1 <= w <= 5]
                if valid_weeks != weeks:
                    schedule["week_of_month"] = valid_weeks or None
                    if not valid_weeks:
                        schedule["frequency"] = "weekly"

    return areas


# --- PDF extraction ---

def _find_pdf_links(html: str, base_url: str) -> list[dict]:
    """Extract PDF links from an HTML page, categorized by type."""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "html.parser")
    pdfs = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" not in href.lower():
            continue
        text = a.get_text(strip=True)
        full_url = urljoin(base_url, href)
        pdfs.append({"url": full_url, "text": text})
    return pdfs


def _download_pdf(url: str, timeout: int = 60) -> bytes | None:
    """Download a PDF file, return bytes or None on failure.

    Falls back to Playwright for SPA sites that block direct HTTP (403).
    """
    import requests
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 403:
            logger.info("  HTTP 403, trying Playwright download...")
            return _download_pdf_playwright(url)
        resp.raise_for_status()
        if len(resp.content) < 100:
            return None
        # Verify it's actually a PDF
        if not resp.content[:5].startswith(b"%PDF"):
            logger.warning("  Not a PDF (got %s)", resp.headers.get("content-type", "unknown"))
            return None
        return resp.content
    except Exception as e:
        logger.warning("PDF download failed for %s: %s", url, e)
        return None


def _download_pdf_playwright(url: str) -> bytes | None:
    """Download a PDF using Playwright browser context (for SPA sites)."""
    import asyncio
    from playwright.async_api import async_playwright

    async def _download():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                resp = await page.request.get(url)
                if resp.status != 200:
                    return None
                data = await resp.body()
                if len(data) < 100 or not data[:5].startswith(b"%PDF"):
                    return None
                return data
            except Exception as e:
                logger.warning("Playwright PDF download failed: %s", e)
                return None
            finally:
                await browser.close()

    try:
        return asyncio.run(_download())
    except RuntimeError:
        # Already in an event loop
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_download())


def _call_gemini_with_pdf(
    client: genai.Client, pdf_data: bytes, prompt: str,
    max_output_tokens: int = 65536, retries: int = 2,
) -> dict | list | None:
    """Call Gemini with a PDF file + text prompt."""
    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=pdf_data, mime_type="application/pdf"),
                            types.Part.from_text(text=prompt),
                        ],
                    ),
                ],
                config=types.GenerateContentConfig(max_output_tokens=max_output_tokens),
            )

            candidate = response.candidates[0]
            finish = getattr(candidate, "finish_reason", None)
            if finish and str(finish) not in ("STOP", "FinishReason.STOP", "1"):
                logger.warning("Gemini finish_reason: %s", finish)

            text = ""
            for part in candidate.content.parts:
                if part.text and not getattr(part, "thought", False):
                    text += part.text
            text = text.strip()

            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str and "per_model_per_day" in err_str:
                raise QuotaExhaustedError(f"Daily quota exhausted for {GEMINI_MODEL}") from e
            logger.warning("Gemini PDF error (attempt %d/%d): %s", attempt + 1, retries + 1, e)
            if attempt < retries:
                time.sleep(3)
    return None


PDF_SCHEDULE_PROMPT = """このPDFは「{city_name}」のごみ収集スケジュールに関するデータです。

このPDFから、地区別のごみ収集スケジュールを以下のコンパクトなJSON配列に変換してください。

出力形式：
[
  {{
    "a": "町名/地区名",
    "d": "番地詳細（なければ空文字）",
    "t": "",
    "b": "月木",
    "nb": "2木",
    "r": "水",
    "p": "水",
    "v": "水"
  }}
]

フィールド：a=地区名, d=番地詳細, t=収集時間(昼→daytime,夜→nighttime), b=可燃/燃えるごみ/普通ごみ, nb=不燃ごみ
以下はPDFのカラムに応じて使い分け：
r=資源ごみ, p=ペットボトル, v=有価物, bn=びん, c=缶, pp=古紙/紙類, cl=衣類, pl=プラスチック, m=金属類, h=有害ごみ, br=木の枝/刈り草, cd=段ボール

収集日の表記ルール：
- 毎週のパターン → 「月木」「火金」「水土」（曜日をそのまま）
- 月Nの回目 → 「2木」（第2木曜）、「1,3水」（第1・3水曜）
- パターンが不規則な場合 → 該当なし（空文字）

PDFがカレンダー形式（月ごとに日付がマークされている）の場合：
- カレンダーから規則的な曜日パターンを読み取ってください
- 例：毎月第2・第4金曜に印がある → 「2,4金」
- 例：毎週月・木に印がある → 「月木」
- 明確なパターンがない場合は、無理に規則を見つけず空文字にしてください

すべての地区を漏れなく出力。JSON配列のみ。"""


def _gather_pdfs_from_raw_dir(prefecture: str, city_id: str) -> list[dict]:
    """Find candidate PDF links by scanning cached .html files in raw/<pref>/<city>/.

    Used as a fallback when a city's primary `waste_page_url` is a direct PDF
    that yields a thin extraction — the deep crawler may have visited related
    HTML pages whose PDFs cover other waste types or zones.
    """
    raw_dir = RAW_DIR / prefecture / city_id
    if not raw_dir.exists():
        return []

    seen_urls = set()
    pdfs: list[dict] = []
    for f in sorted(raw_dir.glob("*.html")):
        try:
            html = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # Reconstruct base URL from filename (Playwright dump pattern)
        # e.g. "https_www.city.kamogawa.lg.jp_site_gomino-bunbetsu_226.html.html"
        stem = f.stem
        if stem == "waste_page":
            # Cannot reconstruct; rely on absolute hrefs only
            base_url = ""
        else:
            base_url = stem.replace("_", "/").replace("https/", "https://").replace("http/", "http://")
            if not base_url.startswith(("http://", "https://")):
                base_url = ""

        for p in _find_pdf_links(html, base_url):
            if p["url"] in seen_urls:
                continue
            if not p["url"].startswith(("http://", "https://")):
                continue
            seen_urls.add(p["url"])
            pdfs.append(p)
    return pdfs


def extract_from_pdfs(
    client: genai.Client,
    city_id: str,
    city_name: str,
    html_content: str,
    waste_page_url: str,
) -> dict:
    """Extract schedule data from PDF links found in the waste page HTML."""
    pdf_links = _find_pdf_links(html_content, waste_page_url)

    if not pdf_links:
        return {
            "city_id": city_id,
            "city_name": city_name,
            "source_format": "pdf_no_links",
            "areas": [],
            "warnings": ["No PDF links found"],
        }

    # Try each PDF until we get results
    # Prioritize PDFs with schedule-related keywords (収集日/カレンダー first, 分け方 last)
    high_priority = ["収集日", "カレンダー", "calendar", "地区別", "曜日", "スケジュール"]
    med_priority = ["地区", "収集", "一覧"]
    low_priority = ["分別", "分け方", "出し方"]

    def pdf_score(p):
        combined = p["text"] + p["url"]
        score = sum(10 for kw in high_priority if kw in combined.lower())
        score += sum(3 for kw in med_priority if kw in combined)
        score += sum(1 for kw in low_priority if kw in combined)
        return -score

    pdf_links.sort(key=pdf_score)

    # Filter out accessibility/duplicate/old-year PDFs
    filtered_pdfs = []
    # Determine latest fiscal year in the links
    import re as _re
    years_found = set()
    for p in pdf_links:
        combined = p["text"] + p["url"]
        for m in _re.findall(r'令和(\d+)年度', combined):
            years_found.add(int(m))
        for m in _re.findall(r'[Rr](\d+)[_\-]', p["url"]):
            years_found.add(int(m))
    latest_year = max(years_found) if years_found else None

    for p in pdf_links:
        text = p["text"]
        url = p["url"]
        combined = text + url
        # Skip accessibility versions
        if "弱視" in text or "音声" in text or "点字" in text:
            continue
        # Skip English/foreign language versions
        if url.startswith("e2") or "/e2" in url:
            continue
        foreign_kw = ["English", "英語", "中国語", "タイ語", "ベトナム", "ペルシャ",
                      "Español", "Garbage Calendar", "Calendario", "シンハラ"]
        if any(kw in text for kw in foreign_kw):
            continue
        # Skip older fiscal years if we found multiple
        if latest_year and years_found and len(years_found) > 1:
            year_matches = _re.findall(r'令和(\d+)年度', combined)
            url_year = _re.findall(r'[Rr](\d+)[_\-]', url)
            found_year = None
            if year_matches:
                found_year = int(year_matches[0])
            elif url_year:
                found_year = int(url_year[0])
            if found_year and found_year < latest_year:
                continue
        filtered_pdfs.append(p)

    all_areas = []
    warnings = []
    pdfs_tried = 0
    max_pdfs = 20  # Allow processing all area calendars

    # todo can we parallelize this?
    for pdf_info in filtered_pdfs[:max_pdfs]:
        url = pdf_info["url"]
        text = pdf_info["text"]
        logger.info("  Trying PDF: %s (%s)", text[:40], url[-40:])

        pdf_data = _download_pdf(url)
        if not pdf_data:
            continue

        pdfs_tried += 1
        prompt = PDF_SCHEDULE_PROMPT.format(city_name=city_name)
        result = _call_gemini_with_pdf(client, pdf_data, prompt)

        if isinstance(result, list) and len(result) > 0:
            areas = _expand_compact_areas(result)
            if areas:
                logger.info("  PDF extracted %d areas", len(areas))
                all_areas.extend(areas)

    if not all_areas and pdfs_tried > 0:
        warnings.append(f"Tried {pdfs_tried} PDFs but extracted no areas")

    # Post-process: deduplicate and validate
    all_areas = _deduplicate_areas(all_areas)
    all_areas = _validate_and_fix_areas(all_areas, warnings)

    waste_types_found = set()
    for a in all_areas:
        for s in a.get("schedules", []):
            waste_types_found.add(s.get("waste_type", "unknown"))

    return {
        "city_id": city_id,
        "city_name": city_name,
        "source_format": "pdf",
        "areas": all_areas,
        "warnings": warnings,
        "stats": {
            "total_areas": len(all_areas),
            "waste_types_found": sorted(waste_types_found),
            "pdfs_tried": pdfs_tried,
        },
    }


# --- Main extraction ---

def extract_city_schedule(
    client: genai.Client,
    city_id: str,
    city_name: str,
    html_content: str,
    markdown_content: str,
) -> dict:
    """Extract structured schedule data from a city's waste page."""
    source_format = classify_source(html_content, markdown_content)

    if source_format == "insufficient":
        return {
            "city_id": city_id,
            "city_name": city_name,
            "source_format": "insufficient",
            "areas": [],
            "warnings": ["Insufficient content for extraction"],
        }

    if source_format == "html_table":
        content = extract_schedule_tables(html_content)
        format_note = "HTML表形式です。rowspan/colspan属性に注意して正確に抽出してください。"
    else:
        # Text-based fallback (markdown)
        content = markdown_content
        format_note = "テキスト形式です。"

    prompt = EXTRACTION_PROMPT.format(
        city_name=city_name,
        city_id=city_id,
        content=content,
        format_note=format_note,
    )

    result = _call_gemini(client, prompt)

    areas = []
    warnings = []

    if result is None:
        warnings.append("Gemini returned no result")
    elif isinstance(result, list):
        areas = _expand_compact_areas(result)
    elif isinstance(result, dict) and "areas" in result:
        areas = _expand_compact_areas(result["areas"])
    else:
        warnings.append(f"Unexpected result format: {type(result)}")

    # Post-process: deduplicate and validate
    areas = _deduplicate_areas(areas)
    areas = _validate_and_fix_areas(areas, warnings)

    # Basic validation
    if areas:
        burnable_count = sum(
            1 for a in areas
            if any(s.get("waste_type") == "burnable" for s in a.get("schedules", []))
        )
        if burnable_count == 0:
            warnings.append("No burnable waste schedules found")
        elif burnable_count < len(areas) * 0.5:
            warnings.append(f"Only {burnable_count}/{len(areas)} areas have burnable waste")

    waste_types_found = set()
    for a in areas:
        for s in a.get("schedules", []):
            waste_types_found.add(s.get("waste_type", "unknown"))

    return {
        "city_id": city_id,
        "city_name": city_name,
        "source_format": source_format,
        "areas": areas,
        "warnings": warnings,
        "stats": {
            "total_areas": len(areas),
            "waste_types_found": sorted(waste_types_found),
        },
    }


# --- Pipeline ---

def extract_all(
    prefecture: str = "chiba",
    limit: int | None = None,
    city_filter: str | None = None,
    skip_existing: bool = True,
) -> dict:
    """Extract schedules for all cities in a prefecture."""
    cities_file = CITIES_DIR / f"{prefecture}.json"
    with open(cities_file, "r", encoding="utf-8") as f:
        cities = json.load(f)

    raw_dir = RAW_DIR / prefecture
    out_dir = SCHEDULES_DIR / prefecture
    out_dir.mkdir(parents=True, exist_ok=True)

    if city_filter:
        targets = [c for c in cities if c["city_id"] == city_filter]
    else:
        targets = cities[:limit] if limit else cities

    stats = {
        "total": len(targets),
        "extracted": 0,
        "skipped_cached": 0,
        "skipped_no_data": 0,
        "skipped_pdf_only": 0,
        "failed": [],
    }

    client = _init_gemini()

    for i, city in enumerate(targets):
        city_id = city["city_id"]
        city_name = city["city_name"]
        out_file = out_dir / f"{city_id}.json"

        print(f"[{i+1}/{len(targets)}] {city_name}...", end=" ", flush=True)

        if skip_existing and out_file.exists():
            stats["skipped_cached"] += 1
            print("CACHED")
            continue

        # Read source files
        html_file = raw_dir / city_id / "waste_page.html"
        md_file = raw_dir / city_id / "waste_page.md"

        html_content = ""
        md_content = ""

        if html_file.exists() and html_file.stat().st_size > 100:
            html_content = html_file.read_text(encoding="utf-8")
        if md_file.exists() and md_file.stat().st_size > 100:
            md_content = md_file.read_text(encoding="utf-8")

        waste_page_url = city.get("waste_page_url", "")

        # Handle direct PDF URLs (waste_page_url ends with .pdf)
        if waste_page_url.lower().endswith(".pdf"):
            logger.info("  Direct PDF URL detected")
            areas: list[dict] = []
            direct_warnings: list[str] = []
            try:
                pdf_data = _download_pdf(waste_page_url)
                if pdf_data:
                    prompt = PDF_SCHEDULE_PROMPT.format(city_name=city_name)
                    gemini_result = _call_gemini_with_pdf(client, pdf_data, prompt)
                    if isinstance(gemini_result, list) and gemini_result:
                        areas = _expand_compact_areas(gemini_result)
                    else:
                        direct_warnings.append("No data from direct PDF")
                else:
                    direct_warnings.append("Direct PDF download failed")

                # Fallback: if direct PDF gave a thin result, scan cached HTML
                # in raw/<city>/ for additional zone/calendar PDFs.
                waste_types = {
                    s.get("waste_type")
                    for a in areas for s in a.get("schedules", [])
                }
                if len(waste_types) < 3 or len(areas) < 2:
                    extra_pdfs = _gather_pdfs_from_raw_dir(prefecture, city_id)
                    extra_pdfs = [
                        p for p in extra_pdfs
                        if p["url"].lower() != waste_page_url.lower()
                    ]
                    if extra_pdfs:
                        logger.info(
                            "  Direct PDF yielded thin result (%d areas, %d types); "
                            "scanning %d additional cached-page PDFs",
                            len(areas), len(waste_types), len(extra_pdfs),
                        )
                        # Build a minimal HTML doc embedding the discovered PDF
                        # links so extract_from_pdfs can filter + prioritise them.
                        synthetic_html = "<html><body>" + "".join(
                            f'<a href="{p["url"]}">{p["text"]}</a>'
                            for p in extra_pdfs
                        ) + "</body></html>"
                        extra_result = extract_from_pdfs(
                            client, city_id, city_name, synthetic_html, waste_page_url,
                        )
                        for a in extra_result.get("areas", []):
                            areas.append(a)
                        direct_warnings.extend(extra_result.get("warnings", []) or [])

                areas = _deduplicate_areas(areas)
                areas = _validate_and_fix_areas(areas, direct_warnings)
                waste_types = sorted({
                    s.get("waste_type")
                    for a in areas for s in a.get("schedules", [])
                    if s.get("waste_type")
                })
                result = {
                    "city_id": city_id, "city_name": city_name,
                    "source_format": "direct_pdf", "areas": areas,
                    "warnings": direct_warnings,
                    "stats": {"total_areas": len(areas), "waste_types_found": waste_types},
                }
            except QuotaExhaustedError:
                raise
            except Exception as e:
                result = {"city_id": city_id, "city_name": city_name,
                          "source_format": "direct_pdf", "areas": [], "warnings": [str(e)]}

            result["source_url"] = waste_page_url
            result["extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            result["extraction_model"] = GEMINI_MODEL
            out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            n_areas = len(result.get("areas", []))
            if n_areas > 0:
                stats["extracted"] += 1
                print(f"OK ({n_areas} areas, direct PDF)")
            else:
                stats["failed"].append({"city_id": city_id, "city_name": city_name})
                print(f"EMPTY (direct PDF)")
            continue

        if not html_content and not md_content:
            stats["skipped_no_data"] += 1
            print("NO DATA")
            continue

        # Classify
        fmt = classify_source(html_content, md_content)
        if fmt == "insufficient":
            stats["skipped_no_data"] += 1
            print(f"INSUFFICIENT")
            continue

        # Extract
        try:
            if fmt == "pdf_links":
                result = extract_from_pdfs(
                    client, city_id, city_name, html_content, waste_page_url,
                )
            else:
                result = extract_city_schedule(client, city_id, city_name, html_content, md_content)
                # Fallback: if HTML table extraction got 0 areas, try PDF extraction
                if result.get("stats", {}).get("total_areas", 0) == 0 and html_content:
                    logger.info("  HTML extraction empty, trying PDF fallback...")
                    pdf_result = extract_from_pdfs(
                        client, city_id, city_name, html_content, waste_page_url,
                    )
                    if pdf_result.get("stats", {}).get("total_areas", 0) > 0:
                        result = pdf_result
        except QuotaExhaustedError:
            print(f"\n⚠ Gemini daily quota exhausted. Stopping.")
            print(f"  Completed {stats['extracted']}/{len(targets)} cities.")
            break

        # Add metadata
        result["source_url"] = city.get("waste_page_url", "")
        result["extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        result["extraction_model"] = GEMINI_MODEL

        # Save
        out_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        n_areas = result.get("stats", {}).get("total_areas", 0)
        warns = result.get("warnings", [])
        if n_areas > 0:
            stats["extracted"] += 1
            print(f"OK ({n_areas} areas, {len(result['stats']['waste_types_found'])} types)")
            if warns:
                print(f"    ⚠ {'; '.join(warns)}")
        else:
            stats["failed"].append({"city_id": city_id, "city_name": city_name, "warnings": warns})
            print(f"EMPTY — {'; '.join(warns)}")

    # Summary
    print(f"\n--- Extraction Summary ---")
    print(f"Total: {stats['total']}")
    print(f"Extracted: {stats['extracted']}")
    print(f"Cached: {stats['skipped_cached']}")
    print(f"No data: {stats['skipped_no_data']}")
    print(f"PDF only: {stats['skipped_pdf_only']}")
    print(f"Failed: {len(stats['failed'])}")

    summary_file = out_dir / "extraction_summary.json"
    summary_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    return stats


def run(limit: int | None = None, city: str | None = None, force: bool = False):
    """Synchronous entry point."""
    return extract_all(limit=limit, city_filter=city, skip_existing=not force)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    city = None
    limit = None
    force = False
    for arg in sys.argv[1:]:
        if arg.startswith("--city="):
            city = arg.split("=")[1]
        elif arg == "--force":
            force = True
        elif arg.isdigit():
            limit = int(arg)

    run(limit=limit, city=city, force=force)
