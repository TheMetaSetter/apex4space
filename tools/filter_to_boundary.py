#!/usr/bin/env python3
"""Stream FIRMS CSV files through a GeoJSON polygon boundary."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "Data"
BOUNDARY = DATA_ROOT / "boundaries" / "south_america.geojson"
OUTPUT_ROOT = ROOT / "processed" / "south_america"
REPORT_ROOT = ROOT / "reports"


def load_boundary() -> list[tuple[dict, tuple[float, float, float, float]]]:
    boundary = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    if boundary.get("type") != "FeatureCollection":
        raise ValueError("Boundary must be a GeoJSON FeatureCollection")
    features = boundary.get("features", [])
    if not features:
        raise ValueError("Boundary has no features")
    return prep(unary_union([shape(feature["geometry"]) for feature in features]))


def filter_file(source: Path, boundary) -> dict:
    relative = source.relative_to(DATA_ROOT)
    destination = OUTPUT_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows_in = rows_out = invalid_coordinates = 0

    with source.open("r", encoding="utf-8-sig", newline="") as input_handle, destination.open(
        "w", encoding="utf-8", newline=""
    ) as output_handle:
        reader = csv.DictReader(input_handle)
        if not reader.fieldnames or not {"latitude", "longitude"} <= set(reader.fieldnames):
            raise ValueError(f"Missing coordinate columns: {source}")
        writer = csv.DictWriter(output_handle, fieldnames=reader.fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in reader:
            rows_in += 1
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (TypeError, ValueError):
                invalid_coordinates += 1
                continue
            if boundary.covers(Point(longitude, latitude)):
                writer.writerow(row)
                rows_out += 1

    return {
        "source_file": source.relative_to(ROOT).as_posix(),
        "output_file": destination.relative_to(ROOT).as_posix(),
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_outside_boundary": rows_in - invalid_coordinates - rows_out,
        "invalid_coordinates": invalid_coordinates,
        "size_bytes": destination.stat().st_size,
    }


def main() -> None:
    boundary = load_boundary()
    files = sorted(
        path for path in DATA_ROOT.rglob("*.csv")
        if "boundaries" not in path.parts and not path.name.startswith("sample_")
    )
    results = [filter_file(path, boundary) for path in files]
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "boundary": BOUNDARY.relative_to(ROOT).as_posix(),
        "boundary_feature_count": len(json.loads(BOUNDARY.read_text(encoding="utf-8"))["features"]),
        "scope": "point-in-polygon filter; source CSVs unchanged",
        "files": results,
    }
    output = REPORT_ROOT / "south_america_filter_manifest.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)} for {len(results)} files")


if __name__ == "__main__":
    main()
