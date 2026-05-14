"""Read-only validator for Chiba schedule files.

Checks each city against schema and quality heuristics. Produces a report.
Does NOT modify any data files.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CITIES_FILE = DATA_DIR / "cities" / "chiba.json"
SCHEDULES_DIR = DATA_DIR / "schedules" / "chiba"

VALID_DAYS = {"月", "火", "水", "木", "金", "土", "日"}
VALID_FREQ = {"weekly", "biweekly", "monthly", "on_demand"}
KNOWN_WASTE_TYPES = {
    "burnable", "non_burnable", "recyclable", "pet_bottles", "valuables",
    "bottles", "cans", "paper", "clothing", "plastic", "metals",
    "hazardous", "branches", "cardboard", "large_waste",
}


def issues_for_schedule(s: dict, area_name: str) -> list[str]:
    issues = []
    wt = s.get("waste_type")
    if not wt:
        issues.append(f"[{area_name}] schedule missing waste_type")
    elif wt not in KNOWN_WASTE_TYPES:
        issues.append(f"[{area_name}] unknown waste_type: {wt}")

    freq = s.get("frequency")
    if freq not in VALID_FREQ:
        issues.append(f"[{area_name}/{wt}] invalid frequency: {freq!r}")

    days = s.get("day_of_week")
    if freq == "on_demand":
        if days:
            issues.append(f"[{area_name}/{wt}] on_demand should have null day_of_week")
    else:
        if not days:
            issues.append(f"[{area_name}/{wt}] missing day_of_week for freq={freq}")
        else:
            if not isinstance(days, list):
                issues.append(f"[{area_name}/{wt}] day_of_week not a list: {days!r}")
            else:
                for d in days:
                    if d not in VALID_DAYS:
                        issues.append(f"[{area_name}/{wt}] invalid day char: {d!r}")
                if len(days) != len(set(days)):
                    issues.append(f"[{area_name}/{wt}] duplicate days: {days}")

    weeks = s.get("week_of_month")
    if freq == "monthly":
        if not weeks:
            issues.append(f"[{area_name}/{wt}] monthly but no week_of_month")
        elif isinstance(weeks, list):
            for w in weeks:
                if not isinstance(w, int) or not (1 <= w <= 5):
                    issues.append(f"[{area_name}/{wt}] invalid week_of_month: {w!r}")
    else:
        if weeks not in (None, []):
            issues.append(f"[{area_name}/{wt}] {freq} should not have week_of_month: {weeks}")

    return issues


def validate_city(city_id: str, city_name: str) -> dict:
    path = SCHEDULES_DIR / f"{city_id}.json"
    result = {
        "city_id": city_id,
        "city_name": city_name,
        "status": "ok",
        "issues": [],
        "stats": {},
    }

    if not path.exists():
        result["status"] = "missing"
        result["issues"].append("schedule file does not exist")
        return result

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        result["status"] = "corrupt"
        result["issues"].append(f"JSON parse error: {e}")
        return result

    areas = data.get("areas", []) or []
    result["stats"]["area_count"] = len(areas)
    result["stats"]["source_format"] = data.get("source_format")
    result["stats"]["source_url"] = data.get("source_url")
    result["stats"]["warnings"] = data.get("warnings", [])

    if not areas:
        result["status"] = "empty"
        warnings = data.get("warnings", [])
        if warnings:
            result["issues"].append(f"empty areas; warnings: {warnings}")
        else:
            result["issues"].append("empty areas, no warnings")
        return result

    # Schema-level issues
    waste_type_counts = Counter()
    burnable_areas = 0
    area_key_counter = Counter()
    duplicate_days_count = 0

    for area in areas:
        an = area.get("area_name", "<no name>")
        detail = area.get("address_detail") or ""
        area_key_counter[(an, detail)] += 1
        if not area.get("schedules"):
            result["issues"].append(f"[{an}] area has no schedules")
            continue
        has_burnable = False
        for s in area.get("schedules", []):
            result["issues"].extend(issues_for_schedule(s, an))
            wt = s.get("waste_type")
            if wt:
                waste_type_counts[wt] += 1
            if wt == "burnable":
                has_burnable = True
            days = s.get("day_of_week") or []
            if isinstance(days, list) and len(days) != len(set(days)):
                duplicate_days_count += 1
        if has_burnable:
            burnable_areas += 1

    result["stats"]["waste_types"] = dict(waste_type_counts)
    result["stats"]["burnable_areas"] = burnable_areas
    result["stats"]["duplicate_days_count"] = duplicate_days_count

    # True duplicate (same name + detail)
    true_dups = [(k, c) for k, c in area_key_counter.items() if c > 1]
    if true_dups:
        sample = [f"{c}x {k[0]}" for k, c in true_dups[:3]]
        result["issues"].append(f"{len(true_dups)} duplicate (name+detail) areas: {sample}")

    if duplicate_days_count > 0:
        result["issues"].append(
            f"{duplicate_days_count} schedules with duplicate day_of_week (legacy bug)"
        )

    # Heuristic flags
    if burnable_areas == 0:
        result["issues"].append("NO burnable waste collection found in any area")
    elif burnable_areas < len(areas) * 0.5:
        result["issues"].append(
            f"only {burnable_areas}/{len(areas)} areas have burnable waste (<50%)"
        )

    # Waste type diversity — most municipalities collect ≥3 categories
    n_types = len(waste_type_counts)
    if n_types < 3:
        result["issues"].append(
            f"only {n_types} waste type(s) extracted ({list(waste_type_counts)}); "
            f"municipalities typically collect ≥3"
        )

    # Categorize status
    if result["issues"]:
        critical_keywords = [
            "NO burnable", "JSON parse error", "schedule file does not exist",
            "duplicate day_of_week", "duplicate (name+detail)", "waste type(s) extracted",
        ]
        critical = any(
            kw in i for i in result["issues"] for kw in critical_keywords
        )
        result["status"] = "critical" if critical else "warnings"
    else:
        result["status"] = "ok"

    return result


def main() -> int:
    with open(CITIES_FILE, encoding="utf-8") as f:
        cities = json.load(f)

    all_results = []
    for c in cities:
        all_results.append(validate_city(c["city_id"], c["city_name"]))

    # Summary
    by_status = Counter(r["status"] for r in all_results)

    print("=" * 70)
    print(f"Chiba schedule validation — {len(all_results)} cities")
    print("=" * 70)
    print(f"Status breakdown: {dict(by_status)}")
    print()

    # Detail
    for status_order in ["missing", "corrupt", "empty", "critical", "warnings", "ok"]:
        rows = [r for r in all_results if r["status"] == status_order]
        if not rows:
            continue
        print(f"--- {status_order.upper()} ({len(rows)}) ---")
        for r in rows:
            stats = r.get("stats", {})
            n = stats.get("area_count", 0)
            wt_count = len(stats.get("waste_types", {}))
            fmt = stats.get("source_format", "?")
            print(f"  {r['city_id']} {r['city_name']:14s} [{fmt:12s}] areas={n:>4} wtypes={wt_count:>2}")
            for issue in r["issues"][:5]:
                print(f"      • {issue}")
            if len(r["issues"]) > 5:
                print(f"      ... +{len(r['issues']) - 5} more")
        print()

    # Output JSON
    output_path = DATA_DIR.parent / "validation_report.json"
    output_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"Full report → {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
