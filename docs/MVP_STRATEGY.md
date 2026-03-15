# Gomidata MVP Strategy

## Project Overview

Collect waste collection schedules from all municipalities in Japan and provide structured data for calendar integration.

### Goals
- Collect waste schedules from all 1,741 municipalities in Japan
- Address precision: Postal code level (〒274-0072)
- Update frequency: Once or twice per year
- Use case: Allow users to add waste collection schedules to Google Calendar

---
### Data Sources
- https://data-platform.mlit.go.jp/api_docs/sources/api_caller.html

## Data Schema

### City Metadata (`cities.json`)

```json
{
  "city_id": "12204",
  "prefecture": "千葉県",
  "city_name": "船橋市",
  "homepage_url": "https://www.city.funabashi.lg.jp/",
  "waste_page_url": "https://...",
  "source_format": "html",
  "last_updated": "2025-04-01"
}
```

| Field | Description |
|-------|-------------|
| `city_id` | 全国地方公共団体コード (6-digit municipal code) |
| `prefecture` | Prefecture name |
| `city_name` | City/town/village name |
| `homepage_url` | Official city homepage |
| `waste_page_url` | Direct URL to waste schedule page |
| `source_format` | `html` / `pdf` / `calendar_pdf` / `web_app` |
| `last_updated` | Last data update date |

### Schedule Data (`schedules.json`)

```json
{
  "city_id": "12204",
  "area_name": "宮本・湊町地区",
  "postal_codes": ["2740072", "2740073"],
  "schedules": [
    {
      "waste_type": "burnable",
      "waste_type_ja": "可燃ごみ",
      "frequency": "weekly",
      "day_of_week": ["月", "木"]
    },
    {
      "waste_type": "non_burnable",
      "waste_type_ja": "不燃ごみ",
      "frequency": "monthly",
      "week_of_month": [4],
      "day_of_week": ["水"]
    }
  ]
}
```

### Waste Type Standardization

| Standard Key | Japanese Variants |
|--------------|-------------------|
| `burnable` | 可燃ごみ, 燃えるごみ, 燃やすごみ |
| `non_burnable` | 不燃ごみ, 燃えないごみ |
| `plastic` | プラスチック, 容器包装プラスチック |
| `cans` | 缶, 空き缶 |
| `bottles` | びん, 空きびん |
| `pet_bottles` | ペットボトル |
| `paper` | 古紙, 紙類, 雑紙 |
| `cardboard` | 段ボール |
| `large_waste` | 粗大ごみ (usually on-demand) |

### Frequency Types

| Frequency | Description | Example |
|-----------|-------------|---------|
| `weekly` | Every week on specific day(s) | 毎週月・木 |
| `biweekly` | Every other week | 隔週火曜 |
| `monthly` | Specific week(s) of month | 第2・4週 水 |
| `on_demand` | By reservation | 粗大ごみ (予約制) |

---

## MVP Scope: Chiba Prefecture (千葉県)

**Why Chiba?**
- 54 municipalities (manageable size)
- Developer is in Funabashi for validation
- Mix of urban and rural areas

### Pipeline Steps

```
Phase 1: City Database
├── Get all 54 Chiba municipalities
├── Collect official homepage URLs
└── Output: data/cities/chiba.json

Phase 2: Waste Page Discovery
├── For each city, find waste schedule page URL
├── Method: LLM-assisted crawling or Google site search
├── Categorize source format (html/pdf/calendar_pdf/web_app)
└── Output: Updated chiba.json with waste_page_url

Phase 3: Download Sources
├── Download HTML pages or PDF files
└── Output: data/raw/chiba/{city_id}/

Phase 4: Data Extraction
├── Use Gemini Pro for multimodal extraction
├── Apply appropriate prompt template per format
└── Output: data/schedules/chiba/{city_id}.json

Phase 5: Validation
├── Validate Funabashi output against known schedule
├── Spot check 5-10 other cities
└── Refine extraction prompts as needed
```

---

## Project Structure

```
gomidata/
├── docs/
│   └── MVP_STRATEGY.md          # This file
├── data/
│   ├── raw/                     # Downloaded HTML/PDFs
│   │   └── chiba/
│   │       └── {city_id}/
│   ├── cities/                  # City metadata
│   │   └── chiba.json
│   └── schedules/               # Extracted schedules
│       └── chiba/
│           └── {city_id}.json
├── src/
│   ├── collectors/
│   │   ├── city_list.py         # Get municipality list
│   │   ├── page_finder.py       # Find waste page URLs
│   │   └── downloader.py        # Download HTML/PDF
│   ├── extractors/
│   │   ├── gemini_extractor.py  # LLM extraction
│   │   └── prompts/             # Prompt templates
│   │       ├── html_prompt.txt
│   │       ├── pdf_prompt.txt
│   │       └── calendar_prompt.txt
│   └── utils/
│       ├── waste_types.py       # Standardized categories
│       └── validators.py        # Data validation
├── config.py
├── main.py
└── requirements.txt
```

---

## Technical Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| LLM | Gemini Pro (multimodal for PDF/images) |
| HTTP Client | httpx / requests |
| PDF Processing | Gemini (direct) or PyMuPDF for pre-processing |
| Data Storage | JSON files (MVP), PostgreSQL (future) |
| Crawling | LLM-assisted link discovery |

---

## Validation Criteria

### Funabashi Test Case

```
City ID: 122041
Address: 船橋市宮本 2丁目
Postal Code: 273-0003

Expected Output (宮本2丁目):
- 可燃ごみ: 毎週 水・土 (夜間収集)
- 不燃ごみ: 第3週 火
- 資源ごみ/ペットボトル: 毎週 月
- 有価物: 毎週 月
```

### Success Metrics for MVP

- [ ] 54/54 Chiba cities have waste_page_url identified
- [ ] 50+ cities successfully extracted (90%+ coverage)
- [ ] Funabashi schedule matches actual data
- [ ] 5 random cities spot-checked and validated

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Cities with web apps requiring address input | Flag for manual handling or browser automation |
| Complex PDF calendars | Use Gemini vision capabilities |
| Area-to-postal-code mapping not provided | May need manual mapping or user area selection |
| Rate limiting on city websites | Polite crawling with delays |
| Schedule format variations | Build flexible extraction prompts |

---

## Next Steps

1. [ ] Define complete waste type mapping (標準化)
2. [ ] Get Chiba city list with homepage URLs
3. [ ] Manually analyze 5 cities to understand format variations
4. [ ] Build first extractor starting with Funabashi
5. [ ] Iterate and expand to full Chiba coverage

---

## Future Expansion (Post-MVP)

- Scale to all 47 prefectures
- Build Google Calendar integration API
- Create user-facing web app for schedule lookup
- Implement yearly update automation
- Add notification service (LINE, push notifications)
