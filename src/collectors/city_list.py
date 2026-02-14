"""Phase 1: Collect municipality list for a prefecture from the MLIT API."""

import json
from pathlib import Path

from src.collectors.mlit_client import post_query

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "cities"

# Chiba prefecture code
CHIBA_PREF_CODE = "12"


def fetch_municipalities(pref_code: str) -> list[dict]:
    """Fetch all municipalities for a given prefecture code."""
    query = f"""
    query {{
      municipalities(prefCodes:["{pref_code}"]) {{
        code
        prefecture_code
        name
      }}
    }}
    """
    return post_query(query, "municipalities")


def build_city_list(pref_code: str, prefecture_name: str) -> list[dict]:
    """Fetch municipalities and transform into our city schema."""
    raw = fetch_municipalities(pref_code)

    cities = []
    for m in raw:
        code = str(m["code"])
        # Pad to 6 digits (MLIT returns integers)
        city_id = code.zfill(6)

        cities.append({
            "city_id": city_id,
            "prefecture": prefecture_name,
            "city_name": m["name"],
            "homepage_url": None,
            "waste_page_url": None,
            "source_format": None,
            "last_updated": None,
        })

    return cities


def save_city_list(cities: list[dict], filename: str) -> Path:
    """Save city list to JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=2)

    return output_path


def collect_chiba() -> Path:
    """Main entry point: collect Chiba prefecture city list."""
    print("Fetching Chiba municipalities from MLIT API...")
    cities = build_city_list(CHIBA_PREF_CODE, "千葉県")
    print(f"  Found {len(cities)} municipalities")

    output = save_city_list(cities, "chiba.json")
    print(f"  Saved to {output}")
    return output


if __name__ == "__main__":
    collect_chiba()