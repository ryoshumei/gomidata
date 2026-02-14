# Project Status

## Current Phase: Phase 2 — Waste Page Discovery (Complete) → Phase 3 — Download Sources

### MVP Pipeline Progress (Chiba Prefecture)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | City Database — collect Chiba municipalities | Done (60 cities) |
| 2 | Waste Page Discovery — find schedule URLs | Done (51/60 found) |
| 3 | Download Sources — fetch HTML/PDFs | Not started |
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
- **Phase 2 complete**: 60/60 homepages found (Wikidata), 51/60 waste pages found (Playwright)
- Dependencies added: `duckduckgo-search`, `beautifulsoup4`, `googlesearch-python` (tested but unused — Wikidata was better)

### In Progress

- Phase 3: Download Sources — fetch HTML/PDFs from discovered waste pages

### Blocked / Open Questions

- No `requirements.txt` or `pyproject.toml` yet — need to decide on dependency management
- Gemini Pro API key not yet configured — needed for Phase 4 extraction
- `main.py` is still PyCharm placeholder — no real entry point yet
- 9 cities missing waste page URLs (homepage links not found by Playwright — likely JS-rendered navigation):
  佐倉市, 旭市, 市原市, 四街道市, 匝瑳市, いすみ市, 酒々井町, 多古町, 長南町

### Last Updated

2026-02-15 — Phase 2 complete, 51/60 waste pages discovered