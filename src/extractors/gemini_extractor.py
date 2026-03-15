"""Phase 4: Extract structured waste schedules from crawled pages using Gemini.

For each city's waste_page.md, sends the content to Gemini 3.1 Pro with a
structured extraction prompt. Gemini returns per-area schedules with
standardized waste types, frequencies, and collection days.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

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


# --- Gemini client (reuse pattern from deep_crawler) ---

class QuotaExhaustedError(Exception):
    pass


def _init_gemini() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=api_key)


def _call_gemini(client: genai.Client, prompt: str, retries: int = 2) -> dict | list | None:
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
                    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
                ),
            )

            text = ""
            for part in response.candidates[0].content.parts:
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


# --- Content cleaning ---

def clean_markdown_for_extraction(raw_markdown: str) -> str:
    """Strip nav boilerplate, images, and footer from markdown for extraction."""
    import re

    lines = raw_markdown.split("\n")
    cleaned = []
    in_content = False

    nav_keywords = [
        "文字サイズ", "配色", "よみがな", "Language", "メニュー",
        "音声読み上げ", "English", "中文", "한국어", "Español",
        "transer.com", "javascript:", "share/imgs", "検索",
    ]
    footer_keywords = [
        "このページについてのご意見", "お問い合わせ", "Copyright",
        "サイトポリシー", "個人情報保護", "アクセシビリティ",
        "このページを見ている人は", "関連リンク",
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip nav boilerplate before content starts
        if not in_content:
            if any(kw in stripped for kw in nav_keywords):
                continue
            # Content starts at a heading, breadcrumb with ごみ, or table separator
            if (stripped.startswith("#")
                    or "---|" in stripped
                    or ("ごみ" in stripped and len(stripped) > 5)
                    or "収集日" in stripped
                    or "カレンダー" in stripped
                    or "現在の場所" in stripped):
                in_content = True

        if not in_content:
            continue

        # Stop at footer
        if any(kw in stripped for kw in footer_keywords):
            break

        # Remove image references
        if stripped.startswith("![") or stripped.startswith("_!["):
            continue

        # Strip URLs from links but keep text
        stripped = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', stripped)

        cleaned.append(stripped)

    result = "\n".join(cleaned)
    if len(result) < 200:
        # Fallback: skip first 1000 chars of nav boilerplate
        result = raw_markdown[1000:]
    return result


def classify_page_format(markdown: str) -> str:
    """Classify page content format.

    Returns: "table", "pdf_links", or "insufficient"
    """
    if len(markdown) < 200:
        return "insufficient"

    has_table = "---|" in markdown
    has_waste_keywords = any(kw in markdown for kw in ["可燃", "不燃", "ごみ", "収集"])
    has_pdf = ".pdf" in markdown.lower()

    if has_table and has_waste_keywords:
        return "table"
    if has_pdf and has_waste_keywords:
        return "pdf_links"
    if has_waste_keywords and len(markdown) > 1000:
        return "table"  # text-based schedule, treat as extractable
    return "insufficient"


# --- Extraction prompt ---

EXTRACTION_PROMPT = """あなたは日本の自治体のごみ収集スケジュールデータを構造化JSONに変換するエキスパートです。

以下は「{city_name}」（city_id: {city_id}）のごみ収集スケジュールページの内容です。

---
{content}
---

タスク：
上記の内容から、地区別のごみ収集スケジュールを以下のJSON形式で抽出してください。

出力形式（JSON配列）：
[
  {{
    "area_name": "町名＋丁目",
    "address_detail": "番地詳細（あれば）",
    "schedules": [
      {{
        "waste_type": "burnable",
        "waste_type_ja": "可燃ごみ",
        "frequency": "weekly",
        "day_of_week": ["月", "木"],
        "week_of_month": null,
        "collection_time": null
      }}
    ]
  }}
]

waste_type の標準化マッピング：
- burnable: 可燃ごみ, 燃えるごみ, 燃やすごみ, 普通ごみ
- non_burnable: 不燃ごみ, 燃えないごみ
- plastic: プラスチック, 容器包装プラスチック
- recyclable: 資源ごみ, 資源物
- cans: 缶, 空き缶, カン
- bottles: びん, 空きびん, ビン
- pet_bottles: ペットボトル, ペット
- paper: 古紙, 紙類, 雑紙
- cardboard: 段ボール
- clothing: 衣類, 布類, 古着
- metals: 金属, 金属類
- hazardous: 有害ごみ
- valuables: 有価物
- branches: 木の枝, 刈り草, 木の枝・刈り草・葉
- large_waste: 粗大ごみ (on_demand)

frequency の判定ルール：
- 「毎週月・木」「月木」「火・金」→ frequency: "weekly", day_of_week: ["月", "木"]
- 「第2・4水」「2・4水」→ frequency: "monthly", week_of_month: [2, 4], day_of_week: ["水"]
- 「2木」「第2木曜」→ frequency: "monthly", week_of_month: [2], day_of_week: ["木"]
- 「予約制」「電話申し込み制」→ frequency: "on_demand", day_of_week: null

注意事項：
- 同じ町名でも番地によって収集日が異なる場合は、別のエントリに分ける
- 「資源/ペット」が1列で同じ曜日なら、recyclable と pet_bottles を別のscheduleエントリに分ける
- 「びん・缶・ペットボトル」が1列なら、bottles, cans, pet_bottles の3つに分ける（同じ曜日）
- 「(昼)」→ collection_time: "daytime"、「(夜)」→ collection_time: "nighttime"
- ページにスケジュールデータがない場合は空配列 [] を返す
- すべての地区を漏れなく抽出すること

JSON配列のみを出力してください。"""


def extract_city_schedule(
    client: genai.Client,
    city_id: str,
    city_name: str,
    markdown_content: str,
) -> dict:
    """Extract structured schedule data from a city's waste page markdown."""
    cleaned = clean_markdown_for_extraction(markdown_content)
    page_format = classify_page_format(cleaned)

    if page_format == "insufficient":
        return {
            "city_id": city_id,
            "city_name": city_name,
            "source_format": "insufficient",
            "areas": [],
            "warnings": ["Insufficient content for extraction"],
        }

    prompt = EXTRACTION_PROMPT.format(
        city_name=city_name,
        city_id=city_id,
        content=cleaned,
    )

    result = _call_gemini(client, prompt)

    areas = []
    warnings = []

    if result is None:
        warnings.append("Gemini returned no result")
    elif isinstance(result, list):
        areas = result
    elif isinstance(result, dict) and "areas" in result:
        areas = result["areas"]
    else:
        warnings.append(f"Unexpected result format: {type(result)}")

    # Basic validation
    if areas:
        burnable_count = sum(
            1 for a in areas
            if any(s.get("waste_type") == "burnable" for s in a.get("schedules", []))
        )
        if burnable_count == 0:
            warnings.append("No burnable waste schedules found")
        if burnable_count < len(areas) * 0.5:
            warnings.append(f"Only {burnable_count}/{len(areas)} areas have burnable waste")

    waste_types_found = set()
    for a in areas:
        for s in a.get("schedules", []):
            waste_types_found.add(s.get("waste_type", "unknown"))

    return {
        "city_id": city_id,
        "city_name": city_name,
        "source_format": page_format,
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

        # Skip if already extracted
        if skip_existing and out_file.exists():
            stats["skipped_cached"] += 1
            print("CACHED")
            continue

        # Read source markdown
        md_file = raw_dir / city_id / "waste_page.md"
        if not md_file.exists() or md_file.stat().st_size < 100:
            stats["skipped_no_data"] += 1
            print("NO DATA")
            continue

        markdown = md_file.read_text(encoding="utf-8")

        # Classify format
        fmt = classify_page_format(markdown)
        if fmt == "insufficient":
            stats["skipped_no_data"] += 1
            print(f"INSUFFICIENT ({len(markdown)} chars)")
            continue
        if fmt == "pdf_links":
            stats["skipped_pdf_only"] += 1
            print("PDF LINKS ONLY")
            continue

        # Extract
        try:
            result = extract_city_schedule(client, city_id, city_name, markdown)
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


def run(limit: int | None = None, city: str | None = None):
    """Synchronous entry point."""
    import asyncio
    return extract_all(limit=limit, city_filter=city)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    city = None
    limit = None
    for arg in sys.argv[1:]:
        if arg.startswith("--city="):
            city = arg.split("=")[1]
        elif arg.isdigit():
            limit = int(arg)

    run(limit=limit, city=city)