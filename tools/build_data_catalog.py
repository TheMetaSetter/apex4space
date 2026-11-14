#!/usr/bin/env python3
"""Build a bounded metadata catalog for local NASA FIRMS CSV files.

The script streams files and writes aggregate metadata only. It never rewrites
the input CSVs and does not apply geographic filtering.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "Data"
REPORT_ROOT = ROOT / "reports"


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def profile_csv(path: Path) -> dict:
    row_count = 0
    malformed_rows = 0
    date_min = None
    date_max = None
    satellites: Counter[str] = Counter()
    instruments: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    confidences: Counter[str] = Counter()
    daynight: Counter[str] = Counter()
    fire_types: Counter[str] = Counter()
    lat_min = lat_max = lon_min = lon_max = None

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        required = {"latitude", "longitude", "acq_date", "acq_time"}
        missing_required = sorted(required - set(columns))

        for row in reader:
            row_count += 1
            if None in row:
                malformed_rows += 1
                continue

            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                date_value = parse_date(row["acq_date"])
            except (KeyError, TypeError, ValueError):
                malformed_rows += 1
                continue

            date_min = date_value if date_min is None else min(date_min, date_value)
            date_max = date_value if date_max is None else max(date_max, date_value)
            lat_min = lat if lat_min is None else min(lat_min, lat)
            lat_max = lat if lat_max is None else max(lat_max, lat)
            lon_min = lon if lon_min is None else min(lon_min, lon)
            lon_max = lon if lon_max is None else max(lon_max, lon)

            for field, counter in (
                ("satellite", satellites),
                ("instrument", instruments),
                ("version", versions),
                ("confidence", confidences),
                ("daynight", daynight),
                ("type", fire_types),
            ):
                if field in row:
                    counter[row[field]] += 1

    relative = path.relative_to(ROOT).as_posix()
    product_type = (
        "near_real_time" if "_near_real_time_" in path.name or "fire_nrt" in path.name
        else "archive" if "_archive_" in path.name or "fire_archive" in path.name
        else "sample_or_unknown"
    )
    return {
        "file": relative,
        "size_bytes": path.stat().st_size,
        "rows": row_count,
        "columns": columns,
        "missing_required_columns": missing_required,
        "malformed_rows": malformed_rows,
        "date_min": date_min.strftime("%Y-%m-%d") if date_min else None,
        "date_max": date_max.strftime("%Y-%m-%d") if date_max else None,
        "latitude_range": [lat_min, lat_max],
        "longitude_range": [lon_min, lon_max],
        "satellite_counts": dict(satellites),
        "instrument_counts": dict(instruments),
        "version_counts": dict(versions),
        "confidence_counts": dict(confidences),
        "daynight_counts": dict(daynight),
        "type_counts": dict(fire_types),
        "product_type": product_type,
    }


def main() -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_ROOT.rglob("*.csv"))
    catalog = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "root": "Data",
        "scope": "metadata catalog; no geographic filtering applied",
        "files": [profile_csv(path) for path in files],
    }
    output = REPORT_ROOT / "data_catalog.json"
    output.write_text(json.dumps(catalog, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)} for {len(files)} CSV files")


if __name__ == "__main__":
    main()
