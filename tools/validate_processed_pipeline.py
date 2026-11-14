#!/usr/bin/env python3
"""Audit retained quality-controlled FIRMS outputs before web export."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "processed" / "quality_controlled"
REPORTS = ROOT / "reports"
EXPECTED_COLUMNS = [
    "source_file", "source_row_number", "sensor", "satellite", "instrument",
    "product_type", "version", "latitude", "longitude", "scan", "track",
    "acq_date", "acq_time", "acq_datetime_utc", "brightness_ti4",
    "background_brightness", "frp", "confidence_original", "confidence_score",
    "daynight", "fire_type",
]


def audit_file(path: Path) -> dict:
    rows = 0
    invalid = Counter()
    date_min = date_max = None
    header = None
    sensors = Counter()
    products = Counter()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        for row in reader:
            rows += 1
            if not row.get("source_file") or not row.get("source_row_number"):
                invalid["missing_lineage"] += 1
            try:
                int(row.get("source_row_number", ""))
            except (TypeError, ValueError):
                invalid["invalid_source_row_number"] += 1
            sensors[row.get("sensor", "")] += 1
            products[row.get("product_type", "")] += 1
            try:
                dt = datetime.strptime(row["acq_datetime_utc"], "%Y-%m-%dT%H:%M:%SZ")
                date_value = dt.strftime("%Y-%m-%d")
                date_min = date_value if date_min is None else min(date_min, date_value)
                date_max = date_value if date_max is None else max(date_max, date_value)
                if row["acq_time"] != dt.strftime("%H%M"):
                    invalid["datetime_time_mismatch"] += 1
            except (KeyError, TypeError, ValueError):
                invalid["invalid_datetime"] += 1
            try:
                if float(row["frp"]) < 0:
                    invalid["negative_frp"] += 1
                score = float(row["confidence_score"])
                if not 0 <= score <= 1:
                    invalid["confidence_score_out_of_range"] += 1
            except (KeyError, TypeError, ValueError):
                invalid["invalid_numeric"] += 1
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
                if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    invalid["coordinates_out_of_range"] += 1
            except (KeyError, TypeError, ValueError):
                invalid["invalid_coordinates"] += 1
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "rows": rows,
        "columns_match": header == EXPECTED_COLUMNS,
        "rows_with_any_invalid": sum(invalid.values()),
        "invalid_counts": dict(invalid),
        "date_min": date_min,
        "date_max": date_max,
        "sensor_counts": dict(sensors),
        "product_counts": dict(products),
    }


def main() -> None:
    files = sorted(PROCESSED.glob("*.csv"))
    results = [audit_file(path) for path in files]
    invalid_keys = {
        key
        for item in results
        for key in item["invalid_counts"]
    }
    report = {
        "scope": "retained quality-controlled archive+NRT sensor outputs",
        "files": results,
        "all_headers_valid": all(item["columns_match"] for item in results),
        "total_invalid_counts": {
            key: sum(item["invalid_counts"].get(key, 0) for item in results)
            for key in sorted(invalid_keys)
        },
    }
    REPORTS.mkdir(exist_ok=True)
    output = REPORTS / "processed_pipeline_validation.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
