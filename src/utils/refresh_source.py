"""Refresh a city's raw source via Playwright when the cached HTML is stale.

Many municipal sites change their page URLs at fiscal-year rollovers. When
the deep-crawl cache is months old, the URLs it captured may 404 even
though the city still publishes the schedule (just at a new path).

This helper re-fetches the live page via Playwright (handling Imperva +
SPA-style sites that block direct HTTP) and rewrites
`data/raw/chiba/<city_id>/waste_page.html` so the next extractor run
sees fresh links.

Usage:
    python3 src/utils/refresh_source.py <city_id> [<override_url>]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CITIES_FILE = REPO / "data" / "cities" / "chiba.json"
RAW_DIR = REPO / "data" / "raw" / "chiba"


async def fetch_via_playwright(url: str) -> str | None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        try:
            page = await b.new_page()
            r = await page.goto(url, timeout=30000, wait_until="networkidle")
            if r is None or r.status >= 400:
                print(f"  HTTP {r.status if r else '?'} — page unreachable")
                return None
            html = await page.content()
            return html
        except Exception as e:
            print(f"  Playwright error: {e}")
            return None
        finally:
            await b.close()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    city_id = sys.argv[1]
    override_url = sys.argv[2] if len(sys.argv) > 2 else None

    with open(CITIES_FILE, encoding="utf-8") as f:
        cities = json.load(f)
    city = next((c for c in cities if c["city_id"] == city_id), None)
    if not city:
        print(f"city_id {city_id} not in cities file")
        return 1

    target_url = override_url or city.get("waste_page_url")
    if not target_url:
        print(f"No waste_page_url for {city_id}")
        return 1

    print(f"Refreshing {city_id} {city['city_name']}: {target_url}")
    html = asyncio.run(fetch_via_playwright(target_url))
    if not html:
        print("  failed to fetch")
        return 1

    raw_city = RAW_DIR / city_id
    raw_city.mkdir(parents=True, exist_ok=True)
    out_path = raw_city / "waste_page.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  wrote {len(html)} bytes → {out_path.relative_to(REPO)}")

    if override_url and override_url != city.get("waste_page_url"):
        city["waste_page_url"] = override_url
        CITIES_FILE.write_text(
            json.dumps(cities, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  updated cities/chiba.json waste_page_url")

    return 0


if __name__ == "__main__":
    sys.exit(main())
