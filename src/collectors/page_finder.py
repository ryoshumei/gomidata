"""Phase 2: Discover homepage URLs and waste collection page URLs for municipalities."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests as http_requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "cities"

WASTE_KEYWORDS = ["ごみ", "ゴミ", "分別", "収集", "廃棄物"]

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

CRAWL_DELAY = 2.0


def fetch_homepages_from_wikidata(prefecture_qid: str = "Q80011") -> dict[str, str]:
    """Fetch official homepage URLs for all municipalities in a prefecture from Wikidata.

    Returns dict mapping city_name -> homepage_url.
    """
    # Query 1: Cities (市) and designated cities
    sparql_cities = f'''
    SELECT DISTINCT ?itemLabel (SAMPLE(?officialSite) AS ?site) WHERE {{
      VALUES ?type {{ wd:Q494721 wd:Q1749269 wd:Q209824 }}
      ?item wdt:P31 ?type .
      ?item wdt:P131 wd:{prefecture_qid} .
      ?item wdt:P856 ?officialSite .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja" . }}
    }}
    GROUP BY ?itemLabel
    ORDER BY ?itemLabel
    '''

    # Query 2: Towns (町), villages (村) — use .town./.vill. URL filter
    # These are nested under districts, so we use P131+ (transitive)
    sparql_towns = f'''
    SELECT DISTINCT ?itemLabel (SAMPLE(?officialSite) AS ?site) WHERE {{
      ?item wdt:P131+ wd:{prefecture_qid} .
      ?item wdt:P856 ?officialSite .
      FILTER(
        CONTAINS(STR(?officialSite), ".town.") ||
        CONTAINS(STR(?officialSite), ".vill.")
      )
      FILTER NOT EXISTS {{
        ?item wdt:P31 wd:Q3914 .
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja" . }}
    }}
    GROUP BY ?itemLabel
    ORDER BY ?itemLabel
    '''

    headers = {"User-Agent": "gomidata/1.0 (waste collection data project)"}
    result = {}

    for label, sparql in [("cities", sparql_cities), ("towns/villages", sparql_towns)]:
        resp = http_requests.get(
            WIKIDATA_ENDPOINT,
            params={"query": sparql, "format": "json"},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json()["results"]["bindings"]
        for item in items:
            name = item["itemLabel"]["value"]
            site = item["site"]["value"]
            parsed = urlparse(site)
            if label == "cities":
                # Type-filtered query: always extract root domain
                root = f"{parsed.scheme}://{parsed.netloc}"
                result[name] = root
            else:
                # URL-filtered query: only keep root-level pages (not schools etc.)
                path = parsed.path.rstrip("/")
                if path in ("", "/index.html"):
                    root = f"{parsed.scheme}://{parsed.netloc}"
                    result[name] = root
        logger.info("Wikidata %s: found %d entries", label, len(items))

    return result


def _strip_district(city_name: str) -> str:
    """Strip district prefix (郡) from city names like '印旛郡酒々井町' -> '酒々井町'."""
    if "郡" in city_name:
        return city_name.split("郡", 1)[1]
    return city_name


def _match_homepage(city_name: str, wikidata: dict[str, str]) -> str | None:
    """Try to match a city name to a Wikidata homepage URL."""
    # Direct match
    if city_name in wikidata:
        return wikidata[city_name]
    # Strip district prefix for towns
    stripped = _strip_district(city_name)
    if stripped in wikidata:
        return wikidata[stripped]
    # For wards like "千葉市中央区", try parent city
    for suffix in ["区"]:
        if city_name.endswith(suffix):
            # Try to find parent city: "千葉市中央区" -> "千葉市"
            for city in wikidata:
                if city_name.startswith(city):
                    return wikidata[city]
    return None


LIFE_KEYWORDS = ["くらし", "暮らし", "生活"]


def _extract_links(page, base_url: str) -> tuple[list[dict], list[dict]]:
    """Extract waste links and life-category links from a page.

    Returns (waste_links, life_links).
    """
    links = page.query_selector_all("a[href]")
    waste_links = []
    life_links = []

    for link in links:
        try:
            href = link.get_attribute("href") or ""
            text = " ".join(link.inner_text().split())  # normalize whitespace
        except Exception:
            continue

        if not href or "@@" in href or href.startswith("#") or href.startswith("javascript:"):
            continue

        combined = text + " " + href
        full_url = urljoin(base_url, href)

        # Check waste keywords
        for kw in WASTE_KEYWORDS:
            if kw in combined:
                waste_links.append({"url": full_url, "text": text, "keyword": kw})
                break
        else:
            # Check life-category keywords (for 2-level crawl)
            for kw in LIFE_KEYWORDS:
                if kw in text:
                    life_links.append({"url": full_url, "text": text})
                    break

    return waste_links, life_links


def _pick_best_waste_link(waste_links: list[dict]) -> dict | None:
    """Pick the best waste link from a list, prioritized by keyword relevance."""
    if not waste_links:
        return None
    priority = {"ごみ": 0, "ゴミ": 0, "収集": 1, "分別": 1, "廃棄物": 2}
    waste_links.sort(key=lambda x: priority.get(x["keyword"], 3))
    best = waste_links[0]
    url = best["url"]
    source_format = "pdf" if url.lower().endswith(".pdf") else "html"
    return {"waste_page_url": url, "source_format": source_format}


def find_waste_page(homepage_url: str, city_name: str) -> dict | None:
    """Use Playwright to crawl a municipality homepage and find waste collection pages.

    Uses a 2-level strategy:
    1. Search homepage for direct waste links
    2. If none found, follow "くらし" (daily life) category links and search there

    Returns dict with 'waste_page_url' and 'source_format', or None if not found.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(homepage_url, timeout=30000, wait_until="networkidle")
        except PlaywrightTimeout:
            # Fallback to domcontentloaded if networkidle times out
            try:
                page.goto(homepage_url, timeout=15000, wait_until="domcontentloaded")
            except Exception:
                logger.warning("Failed to load %s", homepage_url)
                browser.close()
                return None
        except Exception as e:
            logger.warning("Error loading %s: %s", homepage_url, e)
            browser.close()
            return None

        # Level 1: Search homepage directly
        waste_links, life_links = _extract_links(page, homepage_url)

        if not waste_links and life_links:
            # Level 2: Follow the first life-category link and search there
            life_url = life_links[0]["url"]
            logger.info("No waste links on homepage, following '%s' -> %s",
                        life_links[0]["text"], life_url)
            try:
                page.goto(life_url, timeout=30000, wait_until="networkidle")
            except PlaywrightTimeout:
                try:
                    page.goto(life_url, timeout=15000, wait_until="domcontentloaded")
                except Exception:
                    pass
            except Exception:
                pass

            waste_links, _ = _extract_links(page, life_url)

        browser.close()

    if not waste_links:
        logger.warning("No waste links found for %s", city_name)
        return None

    result = _pick_best_waste_link(waste_links)
    if result:
        logger.info("Found waste page: %s", result["waste_page_url"])
    return result


def discover_all(
    cities_file: Path | None = None,
    limit: int | None = None,
    skip_existing: bool = True,
) -> dict:
    """Orchestrate homepage search and waste page discovery for all cities.

    Args:
        cities_file: Path to the cities JSON file. Defaults to chiba.json.
        limit: Process only the first N cities (for testing).
        skip_existing: Skip cities that already have homepage_url set.

    Returns:
        Summary dict with counts of successes, failures, and skipped.
    """
    if cities_file is None:
        cities_file = DATA_DIR / "chiba.json"

    with open(cities_file, "r", encoding="utf-8") as f:
        cities = json.load(f)

    # Step 1: Fetch all homepages from Wikidata in one batch
    print("Fetching homepage URLs from Wikidata...")
    wikidata = fetch_homepages_from_wikidata()
    print(f"  Found {len(wikidata)} municipality homepages")

    today = time.strftime("%Y-%m-%d")
    stats = {"total": 0, "homepage_found": 0, "waste_page_found": 0, "skipped": 0, "failed": []}

    targets = cities[:limit] if limit else cities

    for i, city in enumerate(targets):
        city_name = city["city_name"]
        stats["total"] += 1

        if skip_existing and city.get("homepage_url"):
            logger.info("Skipping %s (already has homepage)", city_name)
            stats["skipped"] += 1
            continue

        print(f"[{i+1}/{len(targets)}] {city_name}...", end=" ")

        # Step 1: Match homepage from Wikidata
        homepage = _match_homepage(city_name, wikidata)

        if not homepage:
            print("NO HOMEPAGE")
            stats["failed"].append({"city_id": city["city_id"], "city_name": city_name, "reason": "no_homepage"})
            continue

        city["homepage_url"] = homepage
        stats["homepage_found"] += 1
        print(f"-> {homepage}", end=" ")

        # Step 2: Find waste page via Playwright
        waste_info = find_waste_page(homepage, city_name)
        time.sleep(CRAWL_DELAY)

        if waste_info:
            city["waste_page_url"] = waste_info["waste_page_url"]
            city["source_format"] = waste_info["source_format"]
            city["last_updated"] = today
            stats["waste_page_found"] += 1
            print(f"-> {waste_info['waste_page_url']}")
        else:
            city["last_updated"] = today
            stats["failed"].append({"city_id": city["city_id"], "city_name": city_name, "reason": "no_waste_page"})
            print("-> NO WASTE PAGE")

        # Save after each city (incremental progress)
        with open(cities_file, "w", encoding="utf-8") as f:
            json.dump(cities, f, ensure_ascii=False, indent=2)

    # Final summary
    print(f"\n--- Discovery Summary ---")
    print(f"Total processed: {stats['total']}")
    print(f"Homepages found: {stats['homepage_found']}")
    print(f"Waste pages found: {stats['waste_page_found']}")
    print(f"Skipped (existing): {stats['skipped']}")
    if stats["failed"]:
        print(f"Failed ({len(stats['failed'])}):")
        for fail in stats["failed"]:
            print(f"  {fail['city_name']} ({fail['city_id']}): {fail['reason']}")

    return stats


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    discover_all(limit=limit)
