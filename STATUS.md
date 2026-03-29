# Project Status

## Current Phase: Phase 5 — Validation

### MVP Pipeline Progress (Chiba Prefecture)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | City Database — collect Chiba municipalities | Done (60 cities) |
| 2 | Waste Page Discovery — find schedule URLs | Done (60/60 found) |
| 3 | Deep Crawl & Schedule Page Discovery | Done (60/60 crawled) |
| 4 | Data Extraction — Gemini Pro extraction | **Done (60/60, 100%)** |
| 5 | Validation — verify all 60 cities | In progress |

### Phase 4 Summary

All 60 Chiba municipalities have structured waste schedule data in `data/schedules/chiba/`.

| Extraction Method | Cities | Description |
|-------------------|:---:|-------------|
| HTML table | 17 | Raw `<table>` with rowspan/colspan sent to Gemini |
| PDF multimodal | 39 | PDF sent to Gemini via `Part.from_bytes` |
| Web app (Playwright) | 1 | 野田市 — scraped さんあーる app directly |
| Direct PDF | 2 | waste_page_url was a PDF, downloaded and sent to Gemini |
| Text | 1 | Markdown text sent to Gemini |

### Validation Status

- **船橋市 (122041)**: Fully validated — 306 areas, 100% match against PostgreSQL DB
- **Other 59 cities**: Pending validation (see `docs/VALIDATION_HANDOVER.md`)

### Key Capabilities Built

- `src/collectors/deep_crawler.py` — LLM-guided crawler with Gemini (early stopping, domain redirect handling, SPA delay)
- `src/extractors/gemini_extractor.py` — Multi-format extractor:
  - HTML tables with rowspan/colspan preservation
  - PDF multimodal extraction (calendar pattern recognition)
  - Playwright fallback for SPA sites (403 bypass)
  - Direct PDF URL handling
  - Fiscal year filtering (latest year only)
  - Foreign language PDF filtering
  - PDF fallback when HTML extraction returns empty

### Completed

- **Phase 1**: 60 Chiba municipalities in `data/cities/chiba.json`
- **Phase 2**: 60/60 waste page URLs discovered
- **Phase 3**: 60/60 schedule pages crawled and downloaded
- **Phase 4**: 60/60 cities extracted with structured schedule data
- Funabashi validation: 100% match rate against PostgreSQL DB

### Blocked / Open Questions

- Gemini 3.1 Pro Preview daily quota: 250 requests/day
- Some cities have low area counts (1-3) that may indicate incomplete extraction
- 鴨川市 only has `burnable` waste type — likely incomplete
- 八街市 has 576 areas (may include duplicates from translated PDFs)

### Last Updated

2026-03-29 — Phase 4 complete (60/60, 100%); Phase 5 validation starting
