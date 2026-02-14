# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gomidata collects waste collection schedules (ごみ収集日程) from all municipalities in Japan and produces structured JSON data for calendar integration (e.g., Google Calendar). MVP targets Chiba Prefecture (54 municipalities). See `docs/MVP_STRATEGY.md` for full strategy and data schemas.

## Environment Setup

- Python 3.9 virtualenv at `.venv/`
- Activate: `source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt` (not yet created)
- Playwright is installed for web crawling; browsers may need: `playwright install`

## Architecture

The project follows a 5-phase data pipeline:

1. **City Database** — Get municipality list with homepage URLs → `data/cities/{prefecture}.json`
2. **Waste Page Discovery** — Find waste schedule page URLs via LLM-assisted crawling → updates city JSON with `waste_page_url`
3. **Download Sources** — Download HTML/PDF from waste pages → `data/raw/{prefecture}/{city_id}/`
4. **Data Extraction** — Use Gemini Pro (multimodal) to extract structured schedules → `data/schedules/{prefecture}/{city_id}.json`
5. **Validation** — Verify output against known schedules (Funabashi is the primary test case)

### Planned Module Layout

- `src/collectors/` — City list retrieval, waste page URL discovery, HTML/PDF downloading
- `src/extractors/` — Gemini-based LLM extraction with prompt templates (`prompts/`)
- `src/utils/` — Waste type standardization, data validators

### Key Data Schemas

- **City metadata**: keyed by `city_id` (6-digit 全国地方公共団体コード), contains `waste_page_url`, `source_format` (html/pdf/calendar_pdf/web_app)
- **Schedule data**: per-area schedules with `waste_type` (standardized English key), `frequency` (weekly/biweekly/monthly/on_demand), `day_of_week`, optional `week_of_month`
- **Waste type mapping**: standardized keys like `burnable`, `non_burnable`, `plastic`, `pet_bottles`, etc. mapped to Japanese variants (see MVP_STRATEGY.md for full table)

## Validation Reference

Funabashi (city_id: 12204, postal: 274-0072) is the primary validation target. Expected: 可燃ごみ 毎週月・木, 不燃ごみ 第4週水.

## Status Tracking

`STATUS.md` tracks current project progress. A Stop hook (`.claude/hooks/check-status-update.sh`) will remind you to update it before ending each session. Update the phase table, move items between sections, and set the date.

## Data Source

Municipality data API: https://data-platform.mlit.go.jp/api_docs/sources/api_caller.html