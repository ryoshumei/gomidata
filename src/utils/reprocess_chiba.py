"""Re-run extractor post-processing on existing Chiba schedule JSON files.

This applies `_deduplicate_areas` + `_validate_and_fix_areas` to each city's
existing JSON. Useful when extractor post-processing logic improves and we
want to apply the fixes to data extracted before the update — without
spending Gemini API quota on re-extraction.

Idempotent: re-running yields identical output.

Usage:
    python3 src/utils/reprocess_chiba.py            # reprocess all
    python3 src/utils/reprocess_chiba.py 122068     # reprocess one
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from extractors.gemini_extractor import _deduplicate_areas, _validate_and_fix_areas

SCHEDULES_DIR = REPO / "data" / "schedules" / "chiba"


def reprocess_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    areas = data.get("areas", []) or []
    if not areas:
        return {"path": path.name, "changed": False, "reason": "no areas"}

    before_count = len(areas)
    before_dup_days = _count_duplicate_days(areas)
    before_serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)

    # Run post-processing
    warnings = list(data.get("warnings", []) or [])
    new_areas = _deduplicate_areas(areas)
    new_areas = _validate_and_fix_areas(new_areas, warnings)

    data["areas"] = new_areas
    data["warnings"] = warnings

    # Update stats
    waste_types = set()
    for a in new_areas:
        for s in a.get("schedules", []):
            wt = s.get("waste_type")
            if wt:
                waste_types.add(wt)
    stats = data.get("stats") or {}
    stats["total_areas"] = len(new_areas)
    stats["waste_types_found"] = sorted(waste_types)
    data["stats"] = stats

    after_serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if before_serialized == after_serialized:
        return {"path": path.name, "changed": False, "reason": "no diff"}

    after_dup_days = _count_duplicate_days(new_areas)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "path": path.name,
        "changed": True,
        "areas_before": before_count,
        "areas_after": len(new_areas),
        "dup_days_before": before_dup_days,
        "dup_days_after": after_dup_days,
    }


def _count_duplicate_days(areas: list[dict]) -> int:
    n = 0
    for a in areas:
        for s in a.get("schedules", []) or []:
            d = s.get("day_of_week") or []
            if isinstance(d, list) and len(d) != len(set(d)):
                n += 1
    return n


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        targets = [SCHEDULES_DIR / f"{arg}.json"]
    else:
        targets = sorted(p for p in SCHEDULES_DIR.glob("*.json") if p.stem != "extraction_summary")

    changed = 0
    for path in targets:
        if not path.exists():
            print(f"  {path.name}: MISSING")
            continue
        r = reprocess_file(path)
        if r.get("changed"):
            changed += 1
            extras = []
            if r.get("areas_before") != r.get("areas_after"):
                extras.append(f"areas {r['areas_before']}→{r['areas_after']}")
            if r.get("dup_days_before") != r.get("dup_days_after"):
                extras.append(
                    f"dup_days {r['dup_days_before']}→{r['dup_days_after']}"
                )
            print(f"  ✓ {path.name}: " + ", ".join(extras))
        else:
            print(f"  - {path.name}: unchanged")

    print(f"\n{changed}/{len(targets)} files changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
