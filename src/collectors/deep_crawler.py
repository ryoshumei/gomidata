"""Phase 3: LLM-guided deep crawl to find waste schedule pages.

Strategy (per city):
1. Crawl waste_page_url (from Phase 2), extract all internal links
2. Send links to Gemini: "which links lead to waste schedule data?"
3. Crawl those Gemini-selected links, extract their links
4. Repeat for up to MAX_ROUNDS rounds
5. Final Gemini call: pick the best schedule page from all crawled pages

This avoids BFS's problem of wasting budget on irrelevant sibling pages.
Gemini guides the crawl at every step, going deep into waste-related pages only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin

from google import genai
from google.genai import types
from dotenv import load_dotenv

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CITIES_DIR = DATA_DIR / "cities"
RAW_DIR = DATA_DIR / "raw"

load_dotenv(DATA_DIR.parent / ".env")

CRAWL_DELAY = 1.0
MAX_ROUNDS = 3  # max crawl-then-ask rounds
MAX_LINKS_PER_ROUND = 5  # max links Gemini can pick per round

GEMINI_MODEL = "gemini-3.1-pro-preview"

# --- Gemini prompts ---

NAVIGATE_PROMPT = """あなたは日本の自治体のごみ収集スケジュールデータを収集するアシスタントです。

「{city_name}」のごみ関連ページをクロール中です。
現在のページ: {current_url}

現在のページの内容（冒頭）：
{page_snippet}

このページから見つかった内部リンク一覧：
{link_list}

タスク：
1. まず、現在のページ自体がごみ収集日程ページ（地区別の収集曜日が表や一覧で記載されている）かどうか判断してください。
2. もしそうなら、"found": true を返してください。これ以上クロールする必要はありません。
3. そうでなければ、次にクロールすべきリンクを最大{max_links}個選んでください。

選ぶ基準：
- 「収集日」「曜日」「カレンダー」「地区別」「分別」「出し方」に関連するリンクを優先
- カテゴリページでも、その先にスケジュール情報がありそうなら選んでOK
- 関係ないリンク（防災、子育て、税金など）は無視

以下のJSON形式のみで回答してください：
{{
  "found": true/false,
  "urls": ["選んだURL1", "選んだURL2"],
  "reason": "理由（簡潔に）"
}}"""

SELECTION_PROMPT = """あなたは日本の自治体のごみ収集スケジュールデータを収集するアシスタントです。

以下は「{city_name}」のごみ関連ページをLLMガイドでクロールして集めた全ページです。
各ページのURL、内容の冒頭を示します。

{page_list}

タスク：
1. この中から、ごみ収集日程（曜日・地区別スケジュール）が実際に記載されているページを選んでください。
2. 優先順位：
   - 最優先：収集日カレンダー・地区別収集曜日の一覧表があるページ
   - 次点：ごみの分け方・出し方の詳細ページ
   - 避ける：カテゴリ一覧ページ（リンク集だけのページ）
3. 重要：該当するページが見つからない場合は、best_urlをnullにしてください。

以下のJSON形式のみで回答してください：
{{
  "best_url": "最も適切なページのURL（見つからない場合はnull）",
  "reason": "選んだ理由、または見つからなかった理由（日本語で簡潔に）",
  "alternative_urls": ["他に関連するページのURL（最大3つ）"]
}}"""


def _extract_body_snippet(markdown: str, max_chars: int = 1500) -> str:
    """Extract meaningful content from markdown, skipping nav/header boilerplate.

    Municipal pages have ~500-1000 chars of nav boilerplate (logo, font size toggles,
    language links, search bar, breadcrumbs). We skip lines that look like nav elements
    and extract actual page content for LLM evaluation.
    """
    lines = markdown.split("\n")
    content_lines = []
    in_content = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip common nav elements
        if any(kw in stripped for kw in [
            "文字サイズ", "配色", "よみがな", "Language", "検索", "メニュー",
            "拡大", "標準", "白黒", "通常", "音声読み上げ", "logo",
            "English", "中文", "한국어", "Español", "Tiếng",
            "transer.com", "javascript:", "share/imgs",
        ]):
            continue
        # Breadcrumb-like lines (short with arrows)
        if ">" in stripped and len(stripped) < 100 and stripped.count(">") >= 2:
            in_content = True
            continue
        # Start collecting after we've seen breadcrumbs or a heading
        if stripped.startswith("#") or in_content:
            in_content = True
            content_lines.append(stripped)

    body = "\n".join(content_lines)
    if not body:
        # Fallback: skip first 500 chars (approximate nav size)
        body = markdown[500:]
    return body[:max_chars]


def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc


def _init_gemini() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=api_key)


class QuotaExhaustedError(Exception):
    """Raised when Gemini daily quota is hit."""
    pass


def _call_gemini(client: genai.Client, prompt: str, retries: int = 2) -> dict | None:
    """Call Gemini and parse JSON response, with retries.

    Raises QuotaExhaustedError on daily quota limits so caller can abort early.
    """
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


def ask_gemini_navigate(
    client: genai.Client, city_name: str, current_url: str,
    page_snippet: str, links: list[dict],
) -> tuple[bool, list[str]]:
    """Ask Gemini which links to follow next.

    Returns (found, urls) where found=True means current page IS the schedule page.
    """
    lines = []
    for i, link in enumerate(links, 1):
        text = link.get("text", "").strip()[:80]
        url = link.get("href", "")
        lines.append(f"{i}. {text} -> {url}")

    link_list = "\n".join(lines)
    prompt = NAVIGATE_PROMPT.format(
        city_name=city_name,
        current_url=current_url,
        page_snippet=page_snippet[:1500],
        link_list=link_list,
        max_links=MAX_LINKS_PER_ROUND,
    )

    result = _call_gemini(client, prompt)
    if result:
        if result.get("found"):
            logger.info("  FOUND schedule page: %s — %s", current_url, result.get("reason", ""))
            return True, []
        if result.get("urls"):
            logger.info("  Navigate: %s", result.get("reason", ""))
            return False, result["urls"][:MAX_LINKS_PER_ROUND]
    return False, []


def ask_gemini_select(client: genai.Client, city_name: str, pages: list[dict]) -> dict | None:
    """Ask Gemini to pick the best waste schedule page from all crawled pages."""
    lines = []
    for i, p in enumerate(pages, 1):
        snippet = p.get("snippet", "")[:1000]
        lines.append(f"{i}. URL: {p['url']}\n   内容: {snippet}")

    page_list = "\n".join(lines)
    prompt = SELECTION_PROMPT.format(city_name=city_name, page_list=page_list)
    return _call_gemini(client, prompt)


async def crawl_single_page(crawler: AsyncWebCrawler, url: str) -> dict | None:
    """Crawl a single page, return its content and links."""
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=10,
        page_timeout=30000,
        wait_until="networkidle",
    )

    try:
        result = await crawler.arun(url=url, config=config)
    except Exception as e:
        logger.warning("Crawl error for %s: %s", url, e)
        return None

    if not result.success:
        return None

    markdown = ""
    if result.markdown:
        markdown = result.markdown.raw_markdown or ""

    internal_links = result.links.get("internal", []) if result.links else []

    return {
        "url": result.url,
        "snippet": _extract_body_snippet(markdown),
        "markdown_chars": len(markdown),
        "internal_links": internal_links,
        "_full_markdown": markdown,
        "_full_html": result.html or "",
    }


async def deep_crawl_city(
    crawler: AsyncWebCrawler,
    city: dict,
    output_dir: Path,
    client: genai.Client,
) -> dict:
    """LLM-guided deep crawl: Gemini decides which links to follow at each step."""
    city_id = city["city_id"]
    city_name = city["city_name"]
    start_url = city.get("waste_page_url") or city.get("homepage_url")

    if not start_url:
        return {"city_id": city_id, "city_name": city_name, "success": False, "reason": "no_url"}

    city_dir = output_dir / city_id
    city_dir.mkdir(parents=True, exist_ok=True)

    # Skip if already deep-crawled
    results_file = city_dir / "deep_crawl_results.json"
    if results_file.exists():
        with open(results_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        return {
            "city_id": city_id,
            "city_name": city_name,
            "success": True,
            "reason": "cached",
            "best_url": cached.get("best_waste_url"),
        }

    domain = _domain_from_url(start_url)
    visited = set()
    all_pages = []  # all crawled pages with content

    # --- Round-based LLM-guided crawl with early stopping ---
    urls_to_crawl = [start_url]
    found_url = None  # set when Gemini identifies the schedule page

    for round_num in range(MAX_ROUNDS + 1):  # +1 for initial page
        if not urls_to_crawl or found_url:
            break

        next_round_urls = []

        for url in urls_to_crawl:
            if url in visited or found_url:
                continue
            visited.add(url)

            page = await crawl_single_page(crawler, url)
            if not page:
                continue

            all_pages.append(page)
            await asyncio.sleep(CRAWL_DELAY)

            # Filter internal links to same domain, not yet visited
            fresh_links = []
            for link in page["internal_links"]:
                href = link.get("href", "")
                if not href or href in visited:
                    continue
                if _domain_from_url(href) != domain:
                    continue
                fresh_links.append(link)

            if not fresh_links:
                continue

            # Ask Gemini: is this the page, or which links to follow?
            found, selected = ask_gemini_navigate(
                client, city_name, url, page["snippet"], fresh_links,
            )
            if found:
                found_url = url
                break
            next_round_urls.extend(selected)

        urls_to_crawl = [u for u in next_round_urls if u not in visited]

    if not all_pages:
        return {"city_id": city_id, "city_name": city_name, "success": False, "reason": "no_pages_crawled"}

    # --- Final selection ---
    if found_url:
        # Gemini already identified the page during crawl — skip selection call
        gemini_result = {"best_url": found_url, "reason": "LLMナビゲーション中に特定", "alternative_urls": []}
    else:
        # Ask Gemini to pick from all crawled pages
        gemini_result = ask_gemini_select(client, city_name, all_pages)

    best_url = None
    alternative_urls = []
    reason = ""

    if gemini_result:
        best_url = gemini_result.get("best_url")
        alternative_urls = gemini_result.get("alternative_urls", [])
        reason = gemini_result.get("reason", "")

    # --- Save results ---
    page_lookup = {p["url"]: p for p in all_pages}

    urls_to_save = [best_url] + alternative_urls if best_url else []
    for url in urls_to_save:
        if url not in page_lookup:
            continue
        p = page_lookup[url]
        safe_name = url.replace("://", "_").replace("/", "_").replace("?", "_")[:100]
        (city_dir / f"{safe_name}.md").write_text(p["_full_markdown"], encoding="utf-8")
        (city_dir / f"{safe_name}.html").write_text(p["_full_html"], encoding="utf-8")

    if best_url and best_url in page_lookup:
        best_page = page_lookup[best_url]
        (city_dir / "waste_page.md").write_text(best_page["_full_markdown"], encoding="utf-8")
        (city_dir / "waste_page.html").write_text(best_page["_full_html"], encoding="utf-8")

    crawl_data = {
        "city_id": city_id,
        "city_name": city_name,
        "start_url": start_url,
        "best_waste_url": best_url,
        "gemini_reason": reason,
        "alternative_urls": alternative_urls,
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pages_crawled": len(all_pages),
        "all_pages": [{"url": p["url"], "chars": p["markdown_chars"]} for p in all_pages],
    }
    results_file.write_text(json.dumps(crawl_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "city_id": city_id,
        "city_name": city_name,
        "success": True,
        "pages": len(all_pages),
        "best_url": best_url,
        "reason": reason,
    }


async def deep_crawl_all(
    prefecture: str = "chiba",
    limit: int | None = None,
) -> dict:
    """Deep crawl all cities in a prefecture.

    Returns summary dict.
    """
    cities_file = CITIES_DIR / f"{prefecture}.json"
    with open(cities_file, "r", encoding="utf-8") as f:
        cities = json.load(f)

    output_dir = RAW_DIR / prefecture
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = cities[:limit] if limit else cities
    stats = {"total": len(targets), "success": 0, "cached": 0, "failed": [], "updated_urls": []}

    client = _init_gemini()
    browser_config = BrowserConfig(headless=True, verbose=False)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for i, city in enumerate(targets):
            print(f"[{i+1}/{len(targets)}] {city['city_name']}...", end=" ", flush=True)

            try:
                result = await deep_crawl_city(crawler, city, output_dir, client)
            except QuotaExhaustedError:
                print(f"\n⚠ Gemini daily quota exhausted. Stopping crawl.")
                print(f"  Completed {stats['success'] + stats['cached']}/{len(targets)} cities.")
                print(f"  Re-run later to continue (cached results will be reused).")
                break

            if result["success"]:
                if result.get("reason") == "cached":
                    stats["cached"] += 1
                    print(f"CACHED -> {result.get('best_url', 'N/A')}")
                else:
                    stats["success"] += 1
                    print(f"OK ({result.get('pages', 0)} pages) -> {result.get('best_url', 'N/A')}")
                    if result.get("reason"):
                        print(f"    Gemini: {result['reason']}")

                best = result.get("best_url")
                if best and best != city.get("waste_page_url"):
                    old_url = city.get("waste_page_url")
                    city["waste_page_url"] = best
                    city["last_updated"] = time.strftime("%Y-%m-%d")
                    stats["updated_urls"].append({
                        "city_name": city["city_name"],
                        "old": old_url,
                        "new": best,
                    })
            else:
                stats["failed"].append(result)
                print(f"FAILED: {result.get('reason', 'unknown')}")

    # Save updated cities JSON
    with open(cities_file, "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=2)

    print(f"\n--- Deep Crawl Summary ---")
    print(f"Total: {stats['total']}")
    print(f"Crawled: {stats['success']}")
    print(f"Cached: {stats['cached']}")
    print(f"Failed: {len(stats['failed'])}")
    if stats["updated_urls"]:
        print(f"\nUpdated waste_page_url ({len(stats['updated_urls'])}):")
        for u in stats["updated_urls"]:
            print(f"  {u['city_name']}: {u['old']} -> {u['new']}")

    summary_file = output_dir / "deep_crawl_summary.json"
    summary_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    return stats


def run(limit: int | None = None):
    """Synchronous entry point."""
    return asyncio.run(deep_crawl_all(limit=limit))


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=limit)