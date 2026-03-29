# Phase 5: Validation Handover

## What to validate

For each city, compare the extracted schedule data in `data/schedules/chiba/{city_id}.json` against the original source page/PDF.

## How to validate

1. Open the source URL (from `chiba.json` or `source_url` in the schedule file)
2. Pick all areas from the extracted data
3. Confirm: waste types, collection days, frequency, and area names match

## Validation checklist

Check these fields per area:
- `area_name` — matches the source town/district name
- `waste_type` — all types present (burnable, non_burnable, etc.)
- `day_of_week` — correct days
- `week_of_month` — correct week numbers for monthly items
- `frequency` — weekly vs monthly vs on_demand
- `collection_time` — daytime/nighttime (Funabashi only)

## Known validated

- **船橋市 (122041)**: 306 areas, 100% match against PostgreSQL DB (248/274 exact match, 26 address formatting diffs)

## Extraction formats

| Format | Cities | Method |
|--------|:---:|--------|
| `html_table` | 17 | Raw HTML `<table>` sent to Gemini |
| `pdf` | 39 | PDF sent to Gemini via `Part.from_bytes` |
| `web_app` | 1 | Playwright scraped さんあーる app (野田市) |
| `direct_pdf` | 2 | `waste_page_url` was a PDF, downloaded directly |
| `text` | 1 | Markdown text sent to Gemini |

## Cities to pay extra attention to

### Low area count (may be incomplete)
| City | ID | Areas | Why |
|------|----|:---:|-----|
| 佐倉市 | 122122 | 1 | Single PDF, may have more areas |
| 浦安市 | 122271 | 1 | HTML table had no area names |
| 大網白里市 | 122394 | 1 | Only "区分1" extracted |
| 印旛郡栄町 | 123293 | 1 | May have multiple areas |
| 山武郡芝山町 | 124095 | 1 | Small town — may be correct |
| 夷隅郡御宿町 | 124435 | 1 | Small town — may be correct |

### High area count (may have duplicates)
| City | ID | Areas | Why |
|------|----|:---:|-----|
| 八街市 | 122301 | 576 | Processed many PDFs including translations |
| 木更津市 | 122068 | 160 | 14 calendar PDFs, some duplicates possible |

### Chiba wards (all share same data)
Cities 121002-121061 (千葉市 + 6 wards) all have identical 261-area data from the same source page. This is correct — wards share the city-level schedule page.

### 鴨川市 (122238) — only burnable
Only `burnable` waste type extracted (17 areas). The PDF likely has more types that Gemini missed.

### 野田市 (122084) — web app source
Extracted via Playwright from さんあーる app, not from the city's own website. Schedule format is `可：火金 不：月 資：1水` parsed directly (no Gemini).

## Key files

- `data/cities/chiba.json` — city metadata with `waste_page_url`
- `data/schedules/chiba/{city_id}.json` — extracted schedule data
- `data/raw/chiba/{city_id}/waste_page.html` — source HTML (if available)
- `src/extractors/gemini_extractor.py` — extraction code

## Re-extraction

To re-extract a single city:
```bash
rm data/schedules/chiba/{city_id}.json
python -u -c "
from src.extractors.gemini_extractor import run
run(city='{city_id}')
"
```

## Gemini quota
- Model: `gemini-3.1-pro-preview`
- Daily limit: 250 requests
- Each city uses 1-20 API calls depending on number of PDFs
