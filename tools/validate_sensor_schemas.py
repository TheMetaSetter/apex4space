#!/usr/bin/env python3
"""Validate FIRMS CSV schemas and sensor-specific normalization assumptions."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "Data"
REPORT_ROOT = ROOT / "reports"

COMMON = {
    "latitude", "longitude", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "frp", "daynight",
}
MODIS_REQUIRED = COMMON | {"brightness", "bright_t31"}
VIIRS_REQUIRED = COMMON | {"brightness", "bright_t31"}


def expected_sensor(path: Path, columns: list[str]) -> str:
    if path.name.startswith("sample_"):
        return "SAMPLE"
    if "MODIS" in path.name or "01_MODIS" in path.parts:
        return "MODIS"
    if "VIIRS" in path.name or any("VIIRS" in part for part in path.parts):
        return "VIIRS"
    return "UNKNOWN"


def validate(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        sensor = expected_sensor(path, columns)
        if sensor == "SAMPLE":
            required = {
                "latitude", "longitude", "scan", "track", "acq_date", "acq_time",
                "satellite", "instrument", "confidence", "version",
                "bright_ti4", "bright_ti5", "frp", "daynight",
            }
        else:
            required = MODIS_REQUIRED if sensor == "MODIS" else VIIRS_REQUIRED
        missing_columns = sorted(required - set(columns))
        invalid_rows = Counter()
        null_counts = Counter()
        confidence_values = Counter()
        row_count = 0

        for row in reader:
            row_count += 1
            for field in required:
                if not (row.get(field) or "").strip():
                    null_counts[field] += 1
            confidence = (row.get("confidence") or "").strip()
            confidence_values[confidence] += 1
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                if not -90 <= lat <= 90:
                    invalid_rows["latitude_out_of_range"] += 1
                if not -180 <= lon <= 180:
                    invalid_rows["longitude_out_of_range"] += 1
            except (KeyError, TypeError, ValueError):
                invalid_rows["invalid_coordinates"] += 1
            try:
                date = row["acq_date"]
                datetime.strptime(date, "%Y-%m-%d")
            except (KeyError, TypeError, ValueError):
                invalid_rows["invalid_date"] += 1
            try:
                time_value = str(row["acq_time"]).zfill(4)
                hour, minute = int(time_value[:2]), int(time_value[2:])
                if hour > 23 or minute > 59:
                    invalid_rows["invalid_time"] += 1
            except (TypeError, ValueError):
                invalid_rows["invalid_time"] += 1
            try:
                if float(row["frp"]) < 0:
                    invalid_rows["negative_frp"] += 1
            except (KeyError, TypeError, ValueError):
                invalid_rows["invalid_frp"] += 1

    return {
        "file": path.relative_to(ROOT).as_posix(),
        "sensor": sensor,
        "rows": row_count,
        "columns": columns,
        "missing_required_columns": missing_columns,
        "null_counts_required_fields": dict(null_counts),
        "invalid_row_counts": dict(invalid_rows),
        "confidence_distinct_values": sorted(confidence_values),
        "confidence_counts": dict(confidence_values),
        "archive_has_type_column": "type" in columns,
        "ready_for_normalization": (
            sensor != "SAMPLE"
            and not missing_columns
            and not invalid_rows
            and not null_counts
        ),
    }


def main() -> None:
    REPORT_ROOT.mkdir(exist_ok=True)
    files = sorted(DATA_ROOT.rglob("*.csv"))
    report = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "scope": "schema and value validation; no rows were rewritten",
        "files": [validate(path) for path in files],
    }
    output = REPORT_ROOT / "sensor_schema_validation.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)} for {len(files)} CSV files")


if __name__ == "__main__":
    main()
