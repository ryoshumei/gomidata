"""九十九里町 (124036) calendar-PDF extractor.

The town's FY calendar PDF (R8karenda.pdf) is a vector document with NO text
layer, so the digits can't be pulled with pdfplumber/pdfium. It carries far
more than the burnable + pet_bottles our generic extractor managed:

- 燃えるごみ (burnable): 3 weekday groups (月木 / 火金 / 水土) — already in the
  existing 50-area record, reused here.
- ペットボトル (pet_bottles): all districts, every Wednesday — reused.
- カン・ビン類・金属類 (cans / bottles / metals): 8 zones, each with a
  per-MONTH collection day that drifts across weekdays — NOT a weekday pattern,
  so represented as explicit `collection_dates` (ISO, FY-specific).
- 電池類・蛍光灯類 (batteries / fluorescent → hazardous): all districts, twice
  a year on fixed dates — also `collection_dates` (frequency "scheduled").

Gemini multimodal reads the dense numeric tables (perception); this script does
all date logic and area assembly (deterministic). The cans/bottles/metals
numbers are spot-checked against a known fixture before writing.

Usage:
    python3 src/extractors/kujukuri_extractor.py [--dry-run]
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.request
from pathlib import Path
from time import strftime

# Reuse the shared Gemini client + PDF call helper.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemini_extractor import _init_gemini, _call_gemini_with_pdf  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "raw" / "chiba" / "124036"
SCHED_DIR = REPO / "data" / "schedules" / "chiba"
PDF_PATH = RAW_DIR / "R8karenda.pdf"
RAW_CACHE = RAW_DIR / "gemini_karenda_raw.json"

CITY_ID = "124036"
CITY_NAME = "山武郡九十九里町"
SOURCE_PAGE = "https://www.town.kujukuri.chiba.jp/0000008915.html"
PDF_URL = "https://www.town.kujukuri.chiba.jp/cmsfiles/contents/0000008/8915/R8karenda.pdf"

# 令和8年度 = fiscal year April 2026 .. March 2027.
FISCAL_YEAR = 2026
MONTH_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]

# Spot-check fixture (read from the town's published calendar) — Zone 1.
# Guards against multimodal digit misreads before we trust the full table.
ZONE1_FIXTURE = {
    "cans":    [2, 1, 1, 2, 3, 1, 1, 2, 1, 4, 1, 1],
    "bottles": [16, 19, 15, 16, 18, 15, 16, 17, 15, 19, 16, 15],
    "metals":  [4, 2, 6, 4, 1, 5, 3, 7, 5, 9, 6, 6],
}

PROMPT = """このPDFは千葉県九十九里町の令和8年度（2026年4月〜2027年3月）ごみ収集カレンダーです。

「カン・ビン類・金属類」の収集日の表を読み取ってください。この表は地区が1〜8の
ゾーンに分かれ、各ゾーンに「カン」「ビン類」「金属類」の行があり、4月から翌3月まで
12ヶ月分の収集日（その月の日にち、1〜31の整数）が並んでいます。

さらにページ下部の固定収集日も読み取ってください：
- 「電池類」の収集日（全地区、年2回。例 "6/8" "12/7"）
- 「蛍光灯類」の収集日（全地区、年2回）
- 「ペットボトル」で収集を行わない除外日（年末・祝日と重複する日）

次のJSONのみを出力してください（コメントや説明文は不要）：
{
  "zones": [
    {
      "zone": 1,
      "districts": ["地区名", "..."],
      "cans":    [4月の日, 5月, 6月, 7月, 8月, 9月, 10月, 11月, 12月, 1月, 2月, 3月],
      "bottles": [12個の整数],
      "metals":  [12個の整数]
    }
  ],
  "battery_dates": ["6/8", "12/7"],
  "fluorescent_dates": ["6/22", "12/21"],
  "pet_excluded_dates": ["4/29", "5/6", "9/23", "12/30"]
}

注意：
- 配列は必ず4月始まり3月終わりの12要素。
- 数字は表のとおり正確に。読み取れない月があっても推測せず、見えた値を入れる。
- ゾーンは8つすべて出力。"""


def _iso_for_fiscal(month: int, day: int) -> str:
    year = FISCAL_YEAR if month >= 4 else FISCAL_YEAR + 1
    return datetime.date(year, month, day).isoformat()


def _monthly_to_dates(days_by_month: list[int]) -> list[str]:
    """[apr_day, may_day, ..., mar_day] → list of ISO dates (FY-aware)."""
    if len(days_by_month) != 12:
        raise ValueError(f"expected 12 monthly values, got {len(days_by_month)}")
    return [_iso_for_fiscal(m, int(d)) for m, d in zip(MONTH_ORDER, days_by_month)]


def _mmdd_to_iso(mmdd: str) -> str:
    m, d = mmdd.replace("／", "/").split("/")
    return _iso_for_fiscal(int(m), int(d))


def _norm(name: str) -> str:
    # Normalize for district matching: drop spaces; unify the katakana/kanji
    # look-alike used in 下タ谷 / 下夕谷.
    return (name or "").replace(" ", "").replace("　", "").replace("夕", "タ")


def _verify_fixture(zones: list[dict]) -> None:
    z1 = next((z for z in zones if z.get("zone") == 1), None)
    if not z1:
        raise SystemExit("ERROR: zone 1 missing from Gemini output — cannot verify")
    for key, expected in ZONE1_FIXTURE.items():
        got = [int(x) for x in z1.get(key, [])]
        if got != expected:
            raise SystemExit(
                f"ERROR: zone1 {key} mismatch vs fixture\n  expected {expected}\n  got      {got}\n"
                "Gemini likely misread digits — aborting before writing data."
            )
    print("Fixture spot-check (zone 1 cans/bottles/metals): OK")


def _sanity_checks(zones: list[dict]) -> None:
    if len(zones) != 8:
        raise SystemExit(f"ERROR: expected 8 zones, got {len(zones)}")
    for z in zones:
        for key in ("cans", "bottles", "metals"):
            vals = z.get(key, [])
            if len(vals) != 12:
                raise SystemExit(f"ERROR: zone {z.get('zone')} {key} has {len(vals)} values, need 12")
            # Will raise if any (month, day) is not a real calendar date.
            _monthly_to_dates(vals)


def _load_existing_areas() -> list[dict]:
    with open(SCHED_DIR / f"{CITY_ID}.json", encoding="utf-8") as f:
        return json.load(f)["areas"]


def _build_zone_lookup(zones: list[dict]) -> dict[str, dict]:
    """Map normalized district name → its zone record."""
    lookup: dict[str, dict] = {}
    for z in zones:
        for d in z.get("districts", []):
            lookup[_norm(d)] = z
    return lookup


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _match_zone(area: dict, lookup: dict[str, dict]) -> dict | None:
    name = area.get("area_name") or ""
    detail = area.get("address_detail") or ""
    cands = [_norm(name + detail), _norm(name)]
    for cand in cands:
        if cand in lookup:
            return lookup[cand]
    # Fuzzy fallback for single-glyph OCR ambiguity (e.g. モ↔毛, 夕↔タ).
    # Accept only an UNAMBIGUOUS distance-1 match to one zone.
    best_zone, best_dist, ties = None, 99, 0
    for cand in cands:
        for district, zone in lookup.items():
            d = _levenshtein(cand, district)
            if d < best_dist:
                best_zone, best_dist, ties = zone, d, 1
            elif d == best_dist and zone is not best_zone:
                ties += 1
    if best_dist <= 1 and ties == 1:
        return best_zone
    return None


def _recyclable_schedules(zone: dict) -> list[dict]:
    out = []
    for key, wt, ja in (
        ("cans", "cans", "カン"),
        ("bottles", "bottles", "ビン類"),
        ("metals", "metals", "金属類"),
    ):
        out.append({
            "waste_type": wt,
            "waste_type_ja": ja,
            "frequency": "monthly",
            "day_of_week": None,
            "week_of_month": None,
            "day_of_month": None,
            "collection_dates": _monthly_to_dates([int(x) for x in zone[key]]),
        })
    return out


def _hazardous_schedules(battery: list[str], fluorescent: list[str]) -> list[dict]:
    out = []
    for dates, ja in ((battery, "電池類"), (fluorescent, "蛍光灯類")):
        out.append({
            "waste_type": "hazardous",
            "waste_type_ja": ja,
            "frequency": "scheduled",
            "day_of_week": None,
            "week_of_month": None,
            "day_of_month": None,
            "collection_dates": [_mmdd_to_iso(x) for x in dates],
        })
    return out


def _ensure_pdf() -> Path:
    if PDF_PATH.exists() and PDF_PATH.stat().st_size > 10000:
        return PDF_PATH
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        PDF_PATH.write_bytes(r.read())
    return PDF_PATH


def _get_raw(refresh: bool) -> dict:
    """Return Gemini's structured output, caching it so matching logic can be
    iterated on without re-spending API quota. Pass refresh=True to re-call."""
    if RAW_CACHE.exists() and not refresh:
        print(f"Using cached Gemini output: {RAW_CACHE.name} (pass --refresh to re-call)")
        return json.loads(RAW_CACHE.read_text(encoding="utf-8"))
    _ensure_pdf()
    print(f"Calling Gemini on {PDF_PATH.name} ...")
    client = _init_gemini()
    raw = _call_gemini_with_pdf(client, PDF_PATH.read_bytes(), PROMPT)
    if not raw or "zones" not in raw:
        raise SystemExit(f"Gemini returned no usable data: {raw!r}")
    RAW_CACHE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw


def extract(dry_run: bool = False, refresh: bool = False) -> dict:
    raw = _get_raw(refresh)

    zones = raw["zones"]
    _sanity_checks(zones)
    _verify_fixture(zones)

    battery = raw.get("battery_dates", [])
    fluorescent = raw.get("fluorescent_dates", [])
    hazardous = _hazardous_schedules(battery, fluorescent)

    lookup = _build_zone_lookup(zones)
    existing = _load_existing_areas()

    unmatched = []
    areas = []
    for area in existing:
        zone = _match_zone(area, lookup)
        if zone is None:
            unmatched.append((area.get("area_name"), area.get("address_detail")))
            areas.append(area)  # keep burnable+pet as-is
            continue
        # Keep existing burnable + pet_bottles, append recyclables + hazardous.
        new_scheds = list(area["schedules"]) + _recyclable_schedules(zone) + hazardous
        areas.append({**area, "schedules": new_scheds})

    if unmatched:
        print(f"WARNING: {len(unmatched)} areas did not match any zone:")
        for nm, dt in unmatched:
            print(f"   - {nm} | {dt}")

    waste_types = sorted({s["waste_type"] for a in areas for s in a["schedules"]})
    result = {
        "city_id": CITY_ID,
        "city_name": CITY_NAME,
        "source_format": "pdf_calendar",
        "source_url": SOURCE_PAGE,
        "source_pdf_url": PDF_URL,
        "fiscal_year": FISCAL_YEAR,
        "areas": areas,
        "warnings": [],
        "stats": {
            "total_areas": len(areas),
            "waste_types_found": waste_types,
            "zones_matched": len(existing) - len(unmatched),
        },
        "extracted_at": strftime("%Y-%m-%dT%H:%M:%S"),
        "extraction_model": "gemini-multimodal+kujukuri-assembler",
    }

    if dry_run:
        print("[dry-run] not writing. Summary:")
        print(f"   areas={len(areas)} matched={result['stats']['zones_matched']} "
              f"waste_types={waste_types}")
        print(f"   battery→{[_mmdd_to_iso(x) for x in battery]} "
              f"fluorescent→{[_mmdd_to_iso(x) for x in fluorescent]}")
        return result

    out = SCHED_DIR / f"{CITY_ID}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out.relative_to(REPO)}: {len(areas)} areas, {len(waste_types)} waste types")
    return result


def main() -> int:
    args = sys.argv[1:]
    extract(dry_run="--dry-run" in args, refresh="--refresh" in args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
