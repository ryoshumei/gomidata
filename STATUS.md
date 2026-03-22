# Project Status

## Current Phase: Phase 3 — Deep Crawl & Schedule Page Discovery (Near Complete)

### MVP Pipeline Progress (Chiba Prefecture)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | City Database — collect Chiba municipalities | Done (60 cities) |
| 2 | Waste Page Discovery — find schedule URLs | Done (60/60 found) |
| 3 | Deep Crawl & Schedule Page Discovery | 60/60 done (3 null) |
| 4 | Data Extraction — Gemini Pro extraction | 48/60 cities (80%) |
| 5 | Validation — verify against Funabashi | Not started |

### Completed

- Initial project scaffolding (repo, venv, .gitignore)
- MVP strategy document (`docs/MVP_STRATEGY.md`)
- Playwright installed in venv for headless browser crawling
- CLAUDE.md created with project overview, architecture, and data schemas
- STATUS.md created for project progress tracking
- Stop hook + PostToolUse hook for STATUS.md update reminders
- Node.js installed (needed for Playwright browsers and Context7 MCP)
- `.env` setup with MLIT API key (gitignored)
- MLIT Data Platform API docs crawled and saved to `docs/mlit_*.txt`
- `src/collectors/mlit_client.py` — GraphQL client for MLIT API
- `src/collectors/city_list.py` — Phase 1 collector
- **Phase 1 complete**: 60 Chiba municipalities saved to `data/cities/chiba.json`
- Project directory structure created (`src/collectors/`, `src/utils/`, `data/`)
- `src/collectors/page_finder.py` — Phase 2 discovery using Wikidata + Playwright
- **Phase 2 complete**: 60/60 homepages found (Wikidata), 60/60 waste pages found (Playwright + 2-level crawl)
- Improved `find_waste_page`: networkidle wait, text normalization, 2-level crawl via くらし links
- Dependencies added: `duckduckgo-search`, `beautifulsoup4`, `googlesearch-python` (tested but unused — Wikidata was better)
- Removed unused Google CSE config from `.env.example`
- Added `requirements.txt` with direct dependencies
- Removed PyCharm boilerplate `main.py`
- Repo made public on GitHub
- Migrated venv from Python 3.9 to Python 3.12 (Homebrew)
- Installed Crawl4AI v0.8.0 for Phase 3 deep crawling
- `src/collectors/downloader.py` — Phase 3 simple downloader using Crawl4AI (60/60 success)
- `src/collectors/deep_crawler.py` — LLM-guided deep crawler using Crawl4AI + Gemini 3.1 Pro
- **Phase 3 deep crawl**: 60/60 cities crawled, 57 schedule pages found, 3 null results
- Early stopping optimization: Gemini identifies schedule pages during navigation, stops crawling immediately
- Snippet extraction: strips nav boilerplate from page content for better LLM evaluation
- Quota-aware abort: detects Gemini daily limit (250 RPD) and stops gracefully
- Relative URL resolution: fixes crawlers that return relative paths instead of absolute URLs
- Flexible domain matching: handles `.chiba.jp` vs `.lg.jp` redirects (八千代市 fix)
- JS SPA delay: `delay_before_return_html=2.0` for dynamic content rendering

### In Progress

- Phase 3: 3 null results remaining: 市原市 (JS SPA), 匝瑳市 (boilerplate snippets), 鋸南町 (no web schedule)
- Consider Google search fallback for SPA sites that don't expose article URLs in static HTML
- `src/extractors/gemini_extractor.py` — Phase 4 extractor using HTML tables + PDF multimodal
- **Phase 4 Funabashi validation**: 306 areas, 100% match rate against PostgreSQL DB (0 mismatches)
- HTML table approach: preserves rowspan/colspan structure, eliminates markdown conversion errors
- PDF multimodal extraction: sends PDFs directly to Gemini via `Part.from_bytes`
- Compact JSON output format: reduces token usage, allows full extraction in 1 API call
- **Phase 4 batch run**: 48/60 cities extracted (80% coverage), 12 remaining (404 PDFs, SPA, insufficient)

### In Progress

- Phase 4: 12 cities remaining — 5 no data (SPA/missing), 7 empty (404 PDF links, insufficient content)

### Blocked / Open Questions

- Gemini 3.1 Pro Preview daily quota: 250 requests/day
- 5 cities with no source data: 市原市 (SPA), 匝瑳市, 佐倉市, 鴨川市, 鋸南町
- 7 cities with empty results: PDFs returning 404 or content not parseable

### Last Updated

2026-03-22 — Phase 4: 47/60 extracted; PDF fallback, improved PDF sorting, fixing remaining 13 cities