# Project Status

## Current Phase: Phase 4 — Data Extraction (80% complete)

### MVP Pipeline Progress (Chiba Prefecture)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | City Database — collect Chiba municipalities | Done (60 cities) |
| 2 | Waste Page Discovery — find schedule URLs | Done (60/60 found) |
| 3 | Deep Crawl & Schedule Page Discovery | Done (57/60 found, 3 null) |
| 4 | Data Extraction — Gemini Pro extraction | **60/60 (100%)** |
| 5 | Validation — verify against Funabashi | Funabashi validated (100% match) |

### Phase 4 Extraction Results

- **48 cities** with extracted schedule data
- **11 partial cities** extracted but may have incomplete area coverage (1-3 areas from PDF-based cities)
- **12 cities** with no extracted data (detailed below)

### Remaining Issues (12 cities with no data)

#### Category A: No Source Data (5 cities)

These cities have no usable `waste_page.html` or `waste_page.md` because the deep crawler couldn't find or render the schedule page.

| City | ID | Root Cause |
|------|----|------------|
| 佐倉市 | 122122 | `waste_page_url` points directly to a PDF (`B3_ja_0127.pdf`). The deep crawler saved it as HTML but it's a binary PDF file, not an HTML page. The downloader needs to handle direct PDF URLs by saving the file as PDF, not HTML. |
| 市原市 | 122190 | JavaScript SPA — the CMS (`categoryCuration?themeId=`) renders content client-side. Crawl4AI gets an empty shell. Article URLs like `article?articleId=...` are never visible in the static HTML. Needs Google search fallback or browser-rendered screenshots. |
| 鴨川市 | 122238 | `waste_page_url` points directly to a PDF (`attachment/20889.pdf`). Same issue as 佐倉市 — binary PDF saved as HTML. |
| 匝瑳市 | 122351 | Older CMS where every page's extracted markdown is only the shared site header/nav boilerplate. The actual content is JS-rendered or in a format Crawl4AI can't capture. 25 pages crawled but all returned identical boilerplate. |
| 安房郡鋸南町 | 124630 | The waste schedule is not published on a dedicated web page. It's distributed via town newsletter PDFs. The `soshiki/13/2865.html` page is a general guide, not a schedule. |

#### Category B: Stale PDF Links — 404 (5 cities)

These cities' waste pages link to PDF calendars, but the PDF files have been updated/moved since our crawl (returning HTTP 404). Re-crawling the waste pages would get fresh PDF URLs.

| City | ID | PDF Status |
|------|----|------------|
| 八街市 | 122301 | 19 PDF links, all returning 404. City likely updated PDF filenames for the new fiscal year. |
| 印旛郡酒々井町 | 123226 | Calendar PDFs (`7A.pdf`, `7B.pdf`) returning 404. Needs re-crawl for updated URLs. |
| 長生郡一宮町 | 124214 | Course PDFs returning 404. File path structure changed. |
| 長生郡長生村 | 124231 | Calendar PDFs returning 404. |
| 夷隅郡御宿町 | 124435 | Calendar PDFs returning 404. URL contains encoded spaces (`%20`) that may cause issues. |

#### Category C: Other Issues (2 cities)

| City | ID | Root Cause |
|------|----|------------|
| 野田市 | 122084 | Schedule page has text descriptions ("月木 or 火金 depending on area") but no structured table or PDF links. The page describes the system but doesn't map specific areas to specific days. Needs a different source page (possibly the city's ごみ分別アプリ data). |
| 香取郡多古町 | 123471 | `waste_page_url` points directly to a PDF (`2025gomibunbetuchou.pdf`) which returns 404. The HTML wrapper has no other PDF links. |

### Partial Extraction Issues (11 cities)

These cities extracted successfully but have incomplete area coverage — typically only 1-3 areas from the first PDF tried, while the city has multiple area-specific calendars.

| City | ID | Areas | PDF Links | Issue |
|------|----|-------|-----------|-------|
| ~~木更津市~~ | ~~122068~~ | ~~3~~ | ~~241~~ | **FIXED**: 160 areas extracted from 14 calendar PDFs. |
| ~~東金市~~ | ~~122131~~ | ~~1~~ | ~~42~~ | **FIXED**: 22 areas from 21 令和8年度 PDFs. |
| 習志野市 | 122165 | 1 | 23 | Multiple area PDFs, only first extracted. |
| 四街道市 | 122289 | 1 | 6 | Multiple area (A/B/C/D) calendars, only A extracted. |
| 富里市 | 122335 | 1 | 9 | Multiple area calendars, only first extracted. |
| いすみ市 | 122386 | 2 | 5 | Has 3 regions (大原/夷隅/岬), only 2 extracted. |
| 香取郡神崎町 | 123421 | 1 | 9 | Small town — 1 area may be correct (町全域). |
| 山武郡芝山町 | 124095 | 1 | 6 | Small town — 1 area may be correct. |
| 長生郡白子町 | 124249 | 1 | 7 | Has 2 districts, only 1 extracted. |
| 長生郡長柄町 | 124265 | 1 | 5 | Has 2 courses, only 1 extracted. |
| 夷隅郡大多喜町 | 124419 | 1 | 5 | Small town — 1 area may be correct. |

**Root cause**: The extractor stops after the first successful PDF extraction (`break` on line in `extract_from_pdfs`). For cities with multiple area-specific calendar PDFs, we need to process all relevant PDFs and merge results. However, this multiplies API calls significantly (e.g., 木更津市 would need ~241 calls).

**Potential fix**: Instead of processing individual area calendars, find and process the master area-lookup PDF (地区別一覧) that maps all areas to their collection schedule in one document, similar to how 茂原市 was handled successfully (248 areas from 1 lookup PDF).

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
- Installed Crawl4AI v0.8.0 for Phase 3 deep crawling
- `src/collectors/downloader.py` — Phase 3 simple downloader using Crawl4AI (60/60 success)
- `src/collectors/deep_crawler.py` — LLM-guided deep crawler using Crawl4AI + Gemini 3.1 Pro
- **Phase 3 deep crawl**: 60/60 cities crawled, 57 schedule pages found, 3 null results
- `src/extractors/gemini_extractor.py` — Phase 4 extractor using HTML tables + PDF multimodal
- **Phase 4 Funabashi validation**: 306 areas, 100% match rate against PostgreSQL DB (0 mismatches)
- HTML table extraction preserves rowspan/colspan structure (eliminates markdown conversion errors)
- PDF multimodal extraction via Gemini `Part.from_bytes(mime_type="application/pdf")`
- PDF fallback: when HTML table extraction returns 0 areas, automatically try PDF links
- Compact JSON output format reduces token usage, allows full extraction in 1 API call
- **Phase 4 batch run**: 48/60 cities extracted (80% coverage)

### Blocked / Open Questions

- Gemini 3.1 Pro Preview daily quota: 250 requests/day — limits throughput
- Direct PDF URLs (佐倉市, 鴨川市, 多古町): downloader saves binary PDFs as `.html` files
- SPA sites (市原市): Crawl4AI cannot render JS-only CMS content
- Partial PDF cities: need multi-PDF processing or master lookup PDF strategy
- Stale PDF links: municipalities update PDF filenames for new fiscal years

### Last Updated

2026-03-29 — **Phase 4 complete: 60/60 (100%)**; all Chiba municipalities extracted
