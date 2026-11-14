#!/usr/bin/env python3
"""Create canonical South America FIRMS records from filtered CSVs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed" / "south_america"
OUTPUT_ROOT = ROOT / "processed" / "normalized"
REPORT_ROOT = ROOT / "reports"

OUTPUT_COLUMNS = [
    "source_file",
    "source_row_number",
    "sensor",
    "satellite",
    "instrument",
    "product_type",
    "version",
    "latitude",
    "longitude",
    "scan",
    "track",
    "acq_date",
    "acq_time",
    "acq_datetime_utc",
    "brightness_ti4",
    "background_brightness",
    "frp",
    "confidence_original",
    "confidence_score",
    "daynight",
    "fire_type",
]


def detect_sensor(path: Path) -> str:
    return "MODIS" if "MODIS" in path.name else "VIIRS"


def product_type(path: Path) -> str:
    return "near_real_time" if "near_real_time" in path.name else "archive"


def confidence_score(sensor: str, value: str) -> str:
    if sensor == "MODIS":
        score = max(0.0, min(100.0, float(value))) / 100.0
    else:
        score = {"l": 0.2, "n": 0.6, "h": 1.0}[value.lower()]
    return f"{score:.3f}"


def normalize_file(source: Path) -> dict:
    relative_source = source.relative_to(ROOT).as_posix()
    destination = OUTPUT_ROOT / source.relative_to(INPUT_ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sensor = detect_sensor(source)
    product = product_type(source)
    rows_in = rows_out = 0
    invalid = Counter()

    with source.open("r", encoding="utf-8-sig", newline="") as input_handle, destination.open(
        "w", encoding="utf-8", newline=""
    ) as output_handle:
        reader = csv.DictReader(input_handle)
        writer = csv.DictWriter(output_handle, fieldnames=OUTPUT_COLUMNS, extrasaction="raise")
        writer.writeheader()
        for row_number, row in enumerate(reader, start=2):
            rows_in += 1
            try:
                date_value = row["acq_date"]
                time_value = str(row["acq_time"]).zfill(4)
                parsed = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H%M")
                score = confidence_score(sensor, row["confidence"])
                float(row["latitude"])
                float(row["longitude"])
                float(row["frp"])
            except (KeyError, TypeError, ValueError):
                invalid["invalid_required_value"] += 1
                continue
            writer.writerow(
                {
                    "source_file": relative_source,
                    "source_row_number": row_number,
                    "sensor": sensor,
                    "satellite": row["satellite"],
                    "instrument": row["instrument"],
                    "product_type": product,
                    "version": row["version"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "scan": row["scan"],
                    "track": row["track"],
                    "acq_date": date_value,
                    "acq_time": time_value,
                    "acq_datetime_utc": parsed.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "brightness_ti4": row["brightness"],
                    "background_brightness": row["bright_t31"],
                    "frp": row["frp"],
                    "confidence_original": row["confidence"],
                    "confidence_score": score,
                    "daynight": row["daynight"],
                    "fire_type": row.get("type", ""),
                }
            )
            rows_out += 1

    return {
        "source_file": relative_source,
        "output_file": destination.relative_to(ROOT).as_posix(),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "invalid_rows": dict(invalid),
        "columns": OUTPUT_COLUMNS,
        "size_bytes": destination.stat().st_size,
    }


def main() -> None:
    files = sorted(INPUT_ROOT.rglob("*.csv"))
    report = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "scope": "South America polygon-filtered files only",
        "confidence_score_rule": {
            "MODIS": "numeric confidence / 100",
            "VIIRS": "l=0.2, n=0.6, h=1.0; heuristic comparison score, not probability",
        },
        "files": [normalize_file(path) for path in files],
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    output = REPORT_ROOT / "sensor_normalization_manifest.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)} for {len(files)} files")


if __name__ == "__main__":
    main()
