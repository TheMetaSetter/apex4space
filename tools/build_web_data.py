#!/usr/bin/env python3
"""Build compact web data products from quality-controlled FIRMS observations.

The four input files are streamed; raw sensor observations are not collapsed
across platforms. The monthly summary is intended for calendar charts, while
the date-specific GeoJSON is a map integration sample.
"""

from __future__ import annotations

import csv
import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed" / "quality_controlled"
OUTPUT_ROOT = ROOT / "web" / "data"
DEFAULT_MAP_DATE = "2023-07-12"

TYPE_LABELS = {
    "0": "presumed_vegetation_fire",
    "1": "active_volcano",
    "2": "other_static_land_source",
    "3": "offshore_detection",
    "": "not_provided_by_source",
}

INPUT_FILES = [
    INPUT_ROOT / "MODIS_south_america_all_available.csv",
    INPUT_ROOT / "VIIRS_SNPP_south_america_all_available.csv",
    INPUT_ROOT / "VIIRS_NOAA20_south_america_all_available.csv",
    INPUT_ROOT / "VIIRS_NOAA21_south_america_all_available.csv",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-date", default=DEFAULT_MAP_DATE, help="UTC date for the point GeoJSON (YYYY-MM-DD)")
    map_date = parser.parse_args().map_date
    try:
        datetime.strptime(map_date, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit("--map-date must use YYYY-MM-DD") from exc

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    # month, sensor, platform, product, version, fire type
    groups: dict[tuple[str, ...], dict] = defaultdict(
        lambda: {"detections": 0, "frp_sum": 0.0, "frp_min": None, "frp_max": None}
    )
    date_map_features = []
    manifest = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "inputs": [],
        "rows_read": 0,
        "rows_included": 0,
        "rows_skipped_invalid": 0,
        "map_date": map_date,
        "map_date_features": 0,
        "scope": "South America point-filtered, quality-controlled FIRMS observations",
        "aggregation": "monthly totals and FRP summary by sensor/platform/product/version/fire_type; no cross-sensor deduplication or calibration",
    }

    for path in INPUT_FILES:
        if not path.exists():
            raise FileNotFoundError(path)
        file_rows = 0
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "latitude", "longitude", "frp", "acq_datetime_utc", "sensor",
                "satellite", "product_type", "version", "confidence_original",
                "confidence_score", "fire_type", "source_file", "source_row_number",
            }
            missing = sorted(required - set(reader.fieldnames or []))
            if missing:
                raise ValueError(f"{path.name}: missing columns {missing}")
            for row in reader:
                manifest["rows_read"] += 1
                file_rows += 1
                try:
                    frp = float(row["frp"])
                    timestamp = row["acq_datetime_utc"]
                    if (
                        len(timestamp) != 20
                        or timestamp[4] != "-"
                        or timestamp[7] != "-"
                        or timestamp[10] != "T"
                        or timestamp[13] != ":"
                        or timestamp[16] != ":"
                        or not timestamp.endswith("Z")
                    ):
                        raise ValueError("invalid UTC timestamp")
                    if not (math.isfinite(frp) and frp >= 0):
                        raise ValueError("FRP out of range")
                except (TypeError, ValueError):
                    manifest["rows_skipped_invalid"] += 1
                    continue

                fire_type = row.get("fire_type", "") or ""
                key = (
                    timestamp[:7], row["sensor"], row["satellite"],
                    row["product_type"], row["version"], fire_type,
                )
                agg = groups[key]
                agg["detections"] += 1
                agg["frp_sum"] += frp
                agg["frp_min"] = frp if agg["frp_min"] is None else min(agg["frp_min"], frp)
                agg["frp_max"] = frp if agg["frp_max"] is None else max(agg["frp_max"], frp)
                manifest["rows_included"] += 1

                if timestamp[:10] == map_date:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        manifest["rows_skipped_invalid"] += 1
                        manifest["rows_included"] -= 1
                        continue
                    record_id = f"{row['source_file']}:{row['source_row_number']}"
                    date_map_features.append({
                        "type": "Feature",
                        "id": record_id,
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            "record_id": record_id,
                            "latitude": lat,
                            "longitude": lon,
                            "frp": frp,
                            "datetime_utc": timestamp,
                            "sensor": row["sensor"],
                            "satellite": row["satellite"],
                            "confidence_original": row["confidence_original"],
                            "confidence_score_heuristic": float(row["confidence_score"]),
                            "fire_type": fire_type or None,
                            "fire_type_label": TYPE_LABELS.get(fire_type, "unknown_code"),
                            "product_type": row["product_type"],
                            "version": row["version"],
                        },
                    })

        manifest["inputs"].append({
            "file": path.relative_to(ROOT).as_posix(),
            "rows": file_rows,
        })

    calendar = []
    for key in sorted(groups):
        month, sensor, satellite, product_type, version, fire_type = key
        agg = groups[key]
        calendar.append({
            "month": month,
            "sensor": sensor,
            "satellite": satellite,
            "product_type": product_type,
            "version": version,
            "fire_type": fire_type or None,
            "fire_type_label": TYPE_LABELS.get(fire_type, "unknown_code"),
            "detections": agg["detections"],
            "frp_sum": round(agg["frp_sum"], 3),
            "frp_mean": round(agg["frp_sum"] / agg["detections"], 3),
            "frp_min": agg["frp_min"],
            "frp_max": agg["frp_max"],
        })

    (OUTPUT_ROOT / "calendar_monthly_by_sensor.json").write_text(
        json.dumps(calendar, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    geojson = {
        "type": "FeatureCollection",
        "name": f"firms_observations_{map_date}",
        "features": date_map_features,
    }
    (OUTPUT_ROOT / f"hotspots_{map_date}.geojson").write_text(
        json.dumps(geojson, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    manifest["map_date_features"] = len(date_map_features)
    manifest["calendar_monthly_rows"] = len(calendar)
    (OUTPUT_ROOT / "data_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: manifest[k] for k in (
        "rows_read", "rows_included", "rows_skipped_invalid", "map_date_features",
        "calendar_monthly_rows", "inputs",
    )}, indent=2))


if __name__ == "__main__":
    main()
