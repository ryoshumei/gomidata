# Project Status

## Current Phase: Phase 5 — Validation & Re-extraction

### MVP Pipeline Progress (Chiba Prefecture)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | City Database — collect Chiba municipalities | Done (60 cities) |
| 2 | Waste Page Discovery — find schedule URLs | Done (60/60 found) |
| 3 | Deep Crawl & Schedule Page Discovery | Done (60/60 crawled) |
| 4 | Data Extraction — Gemini Pro extraction | **Done (60/60, 100%)** |
| 5 | Validation — verify all 60 cities | **In progress — re-extraction round 1 complete** |

### Phase 5 Progress

#### Validation (complete)
All 60 cities checked against live source pages/PDFs. Found 30 cities with issues.

#### Extractor Code Fixes (complete)
Three bugs fixed in `gemini_extractor.py`:
- `_parse_schedule_value`: handles `第N`, `曜日` suffix, `1火3火` split format, deduplicates days
- `_deduplicate_areas`: merges same-name areas, keeps unique schedules
- `_validate_and_fix_areas`: converts duplicate-day weekly→monthly, strips invalid week_of_month

#### Re-extraction Round 1 (complete — 38 cities attempted)
Deleted and re-extracted 38 cities with fixed code. Results: 25 extracted, 1 skipped (no data), 12 failed.

**Significantly improved:**
| City | Before | After |
|------|--------|-------|
| 館山市 (122050) | 8 areas, missing types | 64 areas, 10 types |
| 柏市 (122173) | 5 areas | 110 areas, 13 types |
| 我孫子市 (122220) | 9 areas (Zone 1 only) | 59 areas, 13 types |
| 大網白里市 (122394) | 1 area | 5 areas, 5 types |
| 君津市 (122254) | 14 areas | 44 areas, 9 types |
| 白子町 (124249) | area name wrong | 3 areas, 8 types |
| 山武市 (122378) | missing types | 45 areas, 7 types |

**12 cities with empty extraction (0 areas) — need retry:**
| City | ID | Reason |
|------|----|--------|
| 千葉市稲毛区 | 121037 | Gemini returned no result (huge table timeout) |
| 千葉市若葉区 | 121045 | Gemini returned no result |
| 千葉市緑区 | 121053 | Gemini returned no result |
| 千葉市美浜区 | 121061 | Gemini returned no result |
| 市川市 | 122033 | Gemini returned no result |
| 野田市 | 122084 | No data (web app — needs Playwright) |
| 流山市 | 122203 | No data (PDF extraction failed) |
| 八街市 | 122301 | No data (PDF extraction failed) |
| 印旛郡酒々井町 | 123226 | Tried 1 PDF, extracted 0 areas |
| 香取郡多古町 | 123471 | PDF 404 — source unavailable |
| 山武郡九十九里町 | 124036 | No data (PDF extraction failed) |
| 夷隅郡御宿町 | 124435 | No data (PDF extraction failed) |

**Still low area counts (need investigation):**
| City | ID | Areas | Issue |
|------|----|:---:|-------|
| 佐倉市 | 122122 | 1 | Single PDF, city has multiple zones |
| 浦安市 | 122271 | 1 | Should have 4 zones |
| 富里市 | 122335 | 1 | Should have multiple districts |
| 印旛郡栄町 | 123293 | 1 | Should have 2 areas (A/B地区) |
| 夷隅郡大多喜町 | 124419 | 1 | May be correct (small town) |
| 鴨川市 | 122238 | 17 | Only burnable waste type |

### Key Capabilities Built

- `src/collectors/deep_crawler.py` — LLM-guided crawler with Gemini
- `src/extractors/gemini_extractor.py` — Multi-format extractor:
  - HTML tables with rowspan/colspan preservation
  - PDF multimodal extraction (calendar pattern recognition)
  - Playwright fallback for SPA sites (403 bypass)
  - Direct PDF URL handling
  - Fiscal year filtering, foreign language PDF filtering
  - Post-processing: area deduplication, schedule validation, day/frequency fixes

### Completed

- **Phase 1**: 60 Chiba municipalities in `data/cities/chiba.json`
- **Phase 2**: 60/60 waste page URLs discovered
- **Phase 3**: 60/60 schedule pages crawled and downloaded
- **Phase 4**: 60/60 cities extracted with structured schedule data
- **Phase 5 validation**: All 60 cities checked against live sources
- **Extractor code fixes**: 3 systematic bugs fixed
- **Re-extraction round 1**: 25/38 cities improved, 12 need retry

### Blocked / Open Questions

- Gemini 3.1 Pro Preview daily quota: 250 requests/day — limits retry throughput
- 12 cities need re-extraction retry (empty results from round 1)
- 6 cities have persistent low area counts — may need different extraction strategy
- 千葉市 wards (4 of 7) timeout on huge 261-area table — may need chunking

### Last Updated

2026-04-25 — Re-extraction round 1 complete; 25 improved, 12 empty (need retry), 6 low area counts
