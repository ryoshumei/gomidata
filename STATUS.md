# Project Status

## Current Phase: Phase 3 — Deep Crawl & Schedule Page Discovery (Near Complete)

### MVP Pipeline Progress (Chiba Prefecture)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | City Database — collect Chiba municipalities | Done (60 cities) |
| 2 | Waste Page Discovery — find schedule URLs | Done (60/60 found) |
| 3 | Deep Crawl & Schedule Page Discovery | 59/60 done (5 null) |
| 4 | Data Extraction — Gemini Pro extraction | Not started |
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
- **Phase 3 deep crawl**: 59/60 cities crawled, 54 schedule pages found, 5 null results
- Early stopping optimization: Gemini identifies schedule pages during navigation, stops crawling immediately
- Snippet extraction: strips nav boilerplate from page content for better LLM evaluation
- Quota-aware abort: detects Gemini daily limit (250 RPD) and stops gracefully

### In Progress

- Phase 3: 1 remaining city (鋸南町) — quota limited, will complete on next run
- 5 null results to investigate: 市原市, 八千代市, 匝瑳市, 酒々井町, 長柄町

### Blocked / Open Questions

- Gemini 3.1 Pro Preview daily quota: 250 requests/day — limits ~30-40 cities per session

### Last Updated

2026-03-14 — Phase 3 deep crawl near complete (59/60); LLM-guided crawler with early stopping