#!/usr/bin/env python3
"""Create quality-controlled sensor files without changing processed inputs."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed" / "by_sensor"
OUTPUT_ROOT = ROOT / "processed" / "quality_controlled"
REPORTS = ROOT / "reports"


def main() -> None:
    results = []
    exclusions = []
    for source in sorted(INPUT_ROOT.glob("*.csv")):
        destination = OUTPUT_ROOT / source.name
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        kept = excluded = 0
        with source.open("r", encoding="utf-8", newline="") as input_handle, destination.open(
            "w", encoding="utf-8", newline=""
        ) as output_handle:
            reader = csv.DictReader(input_handle)
            writer = csv.DictWriter(output_handle, fieldnames=reader.fieldnames or [])
            writer.writeheader()
            for row_number, row in enumerate(reader, start=2):
                try:
                    frp = float(row["frp"])
                except (KeyError, TypeError, ValueError):
                    excluded += 1
                    exclusions.append({
                        "source_file": source.relative_to(ROOT).as_posix(),
                        "source_row_number": row_number,
                        "reason": "invalid_frp",
                    })
                    continue
                if frp < 0:
                    excluded += 1
                    exclusions.append({
                        "source_file": source.relative_to(ROOT).as_posix(),
                        "source_row_number": row_number,
                        "reason": "negative_frp",
                        "frp": row["frp"],
                    })
                    continue
                writer.writerow(row)
                kept += 1
        results.append({
            "source_file": source.relative_to(ROOT).as_posix(),
            "output_file": destination.relative_to(ROOT).as_posix(),
            "rows_in": kept + excluded,
            "rows_kept": kept,
            "rows_excluded": excluded,
        })

    report = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "rule": "Exclude rows with invalid or negative FRP; raw and pre-QC processed files unchanged.",
        "files": results,
        "exclusions": exclusions,
    }
    REPORTS.mkdir(exist_ok=True)
    output = REPORTS / "quality_control_manifest.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
