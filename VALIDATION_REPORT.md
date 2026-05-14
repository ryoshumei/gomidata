# Chiba Validation Report

Generated: 2026-05-15
Last updated: 2026-05-15 (Round 3 — after iterative code fixes 5e8e21a–986471d)

Run `python3 src/utils/validate_chiba.py` to regenerate `validation_report.json`.

## Current Status

| Status | Count |
|--------|------:|
| ✅ OK | **58** |
| ⚠️ warnings (limited source) | 2 |
| critical / empty / missing | 0 |

| City | ID | Outstanding issue |
|------|----|------|
| 匝瑳市 | 122351 | Source PDF expresses recyclable/hazardous as calendar dates (13日・27日 of month) — outside our day-of-week schema |
| 九十九里町 | 124036 | FY2026 calendar PDF only lists burnable + pet_bottles |

Both records are structurally valid and faithful to the source; the
warning is purely about coverage breadth.

## History (initial → final)

| Status | Initial | Final |
|--------|------:|------:|
| ✅ OK | 43 | 58 |
| ⚠️ CRITICAL | 4 | 0 |
| 🟡 EMPTY | 12 | 0 |
| 🔴 MISSING | 1 | 0 |

## Initial Issues (snapshot)

| Status | Count | Meaning |
|--------|------:|---------|
| ✅ OK (passes schema + heuristics) | 43 | No critical issues |
| ⚠️ CRITICAL (schema bugs) | 4 | Data has structural errors |
| 🟡 EMPTY (`areas=0`) | 12 | Re-extraction failed in round 1 |
| 🔴 MISSING (no file) | 1 | Schedule file does not exist |
| **Total** | **60** | |

**Confidence breakdown of OK 43:** 8 cities have suspicious low-area counts (`areas=1`) that
may be under-extracted — see "Suspect Low-Area" below.

## 🔴 MISSING (1)

| City | ID | Issue | Root cause |
|------|----|----|------|
| 匝瑳市 | 122351 | File deleted, source pages missing from `data/raw/` | Round 1 deleted the JSON expecting re-extraction; only `deep_crawl_results.json` survives. Crawl reported `best_waste_url=null` with PDF alternatives. |

## ⚠️ CRITICAL (4) — schema / quality bugs

| City | ID | Issue | Likely cause |
|------|----|----|------|
| 木更津市 | 122068 | 76 schedules with `day_of_week: ['火','火']` etc. (legacy bug) | Extracted 2026-03-22 BEFORE `_validate_and_fix_areas` was added. Source format `1火3火` was parsed as weekly `['火','火']` instead of monthly `[1,3]`. Re-extracting with current parser would fix. |
| 鴨川市 | 122238 | 17 areas but only `burnable` waste type | `direct_pdf` URL points to PDF containing only burnable schedule; other types are on a different PDF. |
| 四街道市 | 122289 | 2 true duplicates (`旭ケ丘` x2 same detail) | Multi-PDF extraction merged conflicting schedules into separate areas with same key. |
| いすみ市 | 122386 | 3 true duplicates (`大原・東海`, `岬地域`, `夷隅地域` each x2) | Same: multi-PDF area-name collision. |

## 🟡 EMPTY (12) — `areas=0`

| City | ID | Source format | Warning | Likely root cause |
|------|----|----|----|----|
| 千葉市稲毛区 | 121037 | html_table | "Gemini returned no result" | 261-area table — Gemini truncates or token budget exhausted. |
| 千葉市若葉区 | 121045 | html_table | "Gemini returned no result" | Same |
| 千葉市緑区 | 121053 | html_table | "Gemini returned no result" | Same |
| 千葉市美浜区 | 121061 | html_table | "Gemini returned no result" | Same |
| 市川市 | 122033 | html_table | "Gemini returned no result" | Same |
| 野田市 | 122084 | text | (none) | SPA — markdown content has no usable data; needs Playwright extraction. |
| 流山市 | 122203 | pdf | (none) | PDF download or parse failed silently. |
| 八街市 | 122301 | pdf | (none) | PDF download or parse failed silently. |
| 印旛郡酒々井町 | 123226 | pdf | "Tried 1 PDFs but extracted no areas" | Round 1 only tried 1 PDF, but city has 2 region PDFs (A区/B区). |
| 香取郡多古町 | 123471 | direct_pdf | "PDF download failed" | URL returns 404. Need fresh page discovery. |
| 山武郡九十九里町 | 124036 | pdf | (none) | PDF extraction failed silently. |
| 夷隅郡御宿町 | 124435 | pdf | (none) | PDF extraction failed silently. |

## 🟡 Suspect Low-Area within OK status (8)

These pass schema validation but `areas=1` is implausible for a municipality:

| City | ID | Areas | Format | Investigation |
|------|----|---|----|----|
| 佐倉市 | 122122 | 1 (`佐倉市全域`) | direct_pdf | Extractor pointed at a brochure PDF, not per-zone calendars. Multiple zones expected. |
| 浦安市 | 122271 | 1 (empty name) | html_table | Should have 4 zones (1区〜4区). HTML extractor missed per-zone tables. |
| 富里市 | 122335 | 1 (`日吉台地区`) | pdf | Only one subdivision extracted from multi-zone source. |
| 印旛郡栄町 | 123293 | 1 (empty name) | html_table | Should have 2 (A/B地区). |
| 山武郡芝山町 | 124095 | 1 (`芝山町`) | pdf | One PDF for the whole town — may be correct OR could be single summary. |
| 夷隅郡大多喜町 | 124419 | 1 (`大多喜町`) | pdf | May be correct (small town). |
| 安房郡鋸南町 | 124630 | 2 | pdf | 2-zone is plausible but worth verifying. |
| 長生郡長柄町 | 124265 | 2 | html_table | 2-zone is plausible. |

## ✅ OK — high confidence (notable)

The validator marks 43 cities as OK. Notable healthy extractions:

- 千葉市 + 中央区 + 花見川区 (121002 / 121011 / 121029): 261 areas, 9 waste types each
- 船橋市 (122041): 306 areas, 5 types (gold standard reference)
- 茂原市 (122106): 248 areas
- 松戸市 (122076): 179 areas
- 市原市 (122190): 145 areas
- 印西市 (122319): 112 areas
- 銚子市 (122025): 110 areas
- 柏市 (122173): 110 areas, 13 types

## Bug categorization for code fixes

| Bug | Severity | Affected | Fix approach |
|-----|----------|---|----|
| Legacy `["火","火"]` duplicate days | 4 (e.g., 木更津市) | High | Re-extract with current parser (no code change needed) |
| Missing file 122351 (匝瑳市) | 1 | Critical | Re-crawl + re-extract |
| html_table empty result (huge tables) | 5 (千葉市 wards + 市川) | High | Chunk the table or use PDF fallback |
| Multi-PDF area-name collision (true duplicates) | 2 (四街道, いすみ) | Med | Dedup logic should distinguish PDFs (merge schedules instead of keeping separate areas) |
| Single waste type only (鴨川) | 1 | Med | Either pull additional PDFs for the city or refine PDF prioritization |
| PDF extraction failed silently | 4 (流山, 八街, 九十九里, 御宿) | Med | Add diagnostics; fallback to manual zone PDF discovery |
| Direct PDF URL 404 | 1 (多古町) | Low | Re-crawl |
| 1-area cities | 6 | Variable | Per-city investigation; some may be correct |

## Fix plan (one commit per fix)

1. ✅ Snapshot validation tooling — `src/utils/validate_chiba.py` + this report
2. Restore 122351 (匝瑳市) — re-crawl + re-extract source
3. Re-extract 木更津市 (122068) to fix duplicate-days legacy data
4. Empty cities: investigate PDF download failures (流山市, 八街市, 九十九里町, 御宿町) — silent failure logging
5. Empty cities: 千葉市 wards (4) + 市川市 — chunk large HTML tables for Gemini
6. Empty city: 野田市 — Playwright extraction of SPA waste page
7. Empty city: 多古町 — re-crawl (URL 404)
8. Empty city: 酒々井町 — extract both A区/B区 PDFs
9. Critical: 鴨川市 — find additional waste-type PDFs
10. Critical: 四街道市 + いすみ市 — fix multi-PDF area-key collision dedup
11. Suspect: 浦安市, 佐倉市, 富里市, 栄町, 芝山町 — investigate each
