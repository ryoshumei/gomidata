"""Phase 3: Download waste page sources using Crawl4AI.

For each municipality, crawl the waste_page_url and save:
- Cleaned markdown (for LLM extraction)
- Raw HTML (for reference)
- All internal links found (for deep crawl if needed)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CITIES_DIR = DATA_DIR / "cities"
RAW_DIR = DATA_DIR / "raw"

CRAWL_DELAY = 2.0  # seconds between requests


async def crawl_waste_page(
    crawler: AsyncWebCrawler,
    city: dict,
    output_dir: Path,
) -> dict:
    """Crawl a single city's waste page and save results.

    Returns a status dict with city_id, success, and details.
    """
    city_id = city["city_id"]
    city_name = city["city_name"]
    url = city.get("waste_page_url")

    if not url:
        return {"city_id": city_id, "city_name": city_name, "success": False, "reason": "no_url"}

    city_dir = output_dir / city_id
    city_dir.mkdir(parents=True, exist_ok=True)

    # Skip if already downloaded
    md_file = city_dir / "waste_page.md"
    if md_file.exists() and md_file.stat().st_size > 100:
        return {"city_id": city_id, "city_name": city_name, "success": True, "reason": "cached"}

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=10,
        page_timeout=30000,
        wait_until="networkidle",
    )

    try:
        result = await crawler.arun(url=url, config=config)
    except Exception as e:
        logger.warning("Crawl error for %s (%s): %s", city_name, url, e)
        return {"city_id": city_id, "city_name": city_name, "success": False, "reason": str(e)}

    if not result.success:
        logger.warning("Crawl failed for %s: %s", city_name, result.error_message)
        return {
            "city_id": city_id,
            "city_name": city_name,
            "success": False,
            "reason": result.error_message,
        }

    # Save markdown
    markdown = ""
    if result.markdown:
        markdown = result.markdown.raw_markdown or ""
    md_file.write_text(markdown, encoding="utf-8")

    # Save raw HTML
    html_file = city_dir / "waste_page.html"
    html_file.write_text(result.html or "", encoding="utf-8")

    # Save internal links for potential deep crawl
    internal_links = result.links.get("internal", []) if result.links else []
    if internal_links:
        links_file = city_dir / "links.json"
        links_file.write_text(
            json.dumps(internal_links, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Save metadata
    meta = {
        "city_id": city_id,
        "city_name": city_name,
        "url": url,
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "markdown_chars": len(markdown),
        "html_chars": len(result.html or ""),
        "internal_links_count": len(internal_links),
        "status_code": result.status_code,
    }
    meta_file = city_dir / "meta.json"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"city_id": city_id, "city_name": city_name, "success": True, "chars": len(markdown)}


async def download_all(
    prefecture: str = "chiba",
    limit: int | None = None,
    skip_existing: bool = True,
) -> dict:
    """Download waste pages for all cities in a prefecture.

    Args:
        prefecture: Prefecture name (directory under data/cities/).
        limit: Process only first N cities (for testing).
        skip_existing: Skip cities with existing downloads.

    Returns:
        Summary dict with counts.
    """
    cities_file = CITIES_DIR / f"{prefecture}.json"
    with open(cities_file, "r", encoding="utf-8") as f:
        cities = json.load(f)

    output_dir = RAW_DIR / prefecture
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = cities[:limit] if limit else cities
    stats = {"total": len(targets), "success": 0, "cached": 0, "failed": []}

    browser_config = BrowserConfig(headless=True, verbose=False)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for i, city in enumerate(targets):
            print(f"[{i+1}/{len(targets)}] {city['city_name']}...", end=" ", flush=True)

            result = await crawl_waste_page(
                crawler, city, output_dir,
            )

            if result["success"]:
                if result.get("reason") == "cached":
                    stats["cached"] += 1
                    print("CACHED")
                else:
                    stats["success"] += 1
                    print(f"OK ({result.get('chars', 0)} chars)")
            else:
                stats["failed"].append(result)
                print(f"FAILED: {result.get('reason', 'unknown')}")

            # Rate limit (skip delay for cached results)
            if result.get("reason") != "cached":
                await asyncio.sleep(CRAWL_DELAY)

    print(f"\n--- Download Summary ---")
    print(f"Total: {stats['total']}")
    print(f"Downloaded: {stats['success']}")
    print(f"Cached (skipped): {stats['cached']}")
    print(f"Failed: {len(stats['failed'])}")
    if stats["failed"]:
        for f in stats["failed"]:
            print(f"  {f['city_name']} ({f['city_id']}): {f.get('reason', 'unknown')}")

    # Save summary
    summary_file = output_dir / "download_summary.json"
    summary_file.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return stats


def run(limit: int | None = None, skip_existing: bool = True):
    """Synchronous entry point."""
    return asyncio.run(download_all(limit=limit, skip_existing=skip_existing))


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=limit)