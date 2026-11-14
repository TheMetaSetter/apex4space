#!/usr/bin/env python3
"""Validate generated FIRMS web artifacts and their internal reconciliations."""

from __future__ import annotations

import json
import math
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "data"
REPORTS = ROOT / "reports"


def read_json(path: Path):
    if not path.is_file():
        raise AssertionError(f"Missing expected artifact: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate() -> dict:
    monthly = read_json(DATA / "event_calendar_monthly.json")
    event_manifest = read_json(DATA / "event_harmonization_manifest.json")
    sensor_monthly = read_json(DATA / "calendar_monthly_by_sensor.json")
    data_manifest = read_json(DATA / "data_manifest.json")
    cell_geo = read_json(DATA / "hotspot_cell_days_2023-07-12.geojson")
    point_geo = read_json(DATA / "hotspots_2023-07-12.geojson")

    check(isinstance(monthly, list) and monthly, "Monthly cell-day output must be a non-empty list")
    months = [row.get("month") for row in monthly]
    check(months == sorted(months), "Monthly cell-day rows are not sorted")
    check(len(months) == len(set(months)), "Duplicate month in cell-day calendar")

    type_groups = (
        "vegetation_type_only_cell_days",
        "other_known_type_only_cell_days",
        "unknown_type_only_cell_days",
        "mixed_or_partly_unknown_type_cell_days",
    )
    observation_sum = 0
    cell_day_sum = 0
    for row in monthly:
        check(isinstance(row.get("month"), str) and len(row["month"]) == 7, "Invalid month key")
        observation_sum += row["observations"]
        cell_day_sum += row["hotspot_cell_days"]
        check(sum(row[k] for k in type_groups) == row["hotspot_cell_days"],
              f"Fire-type cell-day groups do not reconcile in {row['month']}")
        check(row["terra_backbone_cell_days"] <= row["hotspot_cell_days"],
              f"Terra baseline exceeds union in {row['month']}")
        check(row["terra_only_cell_days"] <= row["terra_backbone_cell_days"],
              f"Terra-only exceeds Terra baseline in {row['month']}")
        check(row["multi_sensor_cell_days"] <= row["hotspot_cell_days"],
              f"Multi-sensor exceeds union in {row['month']}")
        check(sum(row["detections_by_satellite"].values()) == row["observations"],
              f"Satellite detections do not reconcile in {row['month']}")
        check(sum(row["cell_days_by_satellite"].values()) >= row["hotspot_cell_days"],
              f"Sensor-specific cell-day sum should be at least the union in {row['month']}")
        type_obs = sum(row["fire_type_observations_by_code"].values())
        check(type_obs == row["observations"],
              f"Fire-type observation counts do not reconcile in {row['month']}")
        check(row["unknown_fire_type_observations"] == row["fire_type_observations_by_code"].get("unknown", 0),
              f"Unknown fire-type count does not reconcile in {row['month']}")
        for value in row["frp_max_by_satellite"].values():
            check(math.isfinite(value) and value >= 0, f"Invalid FRP summary in {row['month']}")

    check(observation_sum == event_manifest["observations_read"],
          "Monthly observations do not match event manifest input count")
    check(observation_sum == event_manifest["detections_by_month_sum"],
          "Monthly observations do not match manifest monthly sum")
    check(event_manifest["observations_skipped_invalid"] == 0,
          "Event build skipped invalid source rows; inspect manifest")
    check(cell_day_sum == event_manifest["hotspot_cell_days"],
          "Monthly cell-days do not match event manifest total")
    check(len(monthly) == event_manifest["monthly_rows"],
          "Monthly row count does not match event manifest")

    sensor_observations = sum(row["detections"] for row in sensor_monthly)
    check(sensor_observations == observation_sum,
          "Sensor-native calendar total does not match cell-day calendar observations")
    check(data_manifest["rows_read"] == data_manifest["rows_included"] + data_manifest["rows_skipped_invalid"],
          "Point calendar manifest row accounting does not reconcile")
    check(data_manifest["rows_included"] == observation_sum,
          "Point calendar included rows do not match cell-day observations")

    for geo, label in ((cell_geo, "cell-day"), (point_geo, "point")):
        check(geo.get("type") == "FeatureCollection", f"{label} GeoJSON is not a FeatureCollection")
        ids = []
        for feature in geo.get("features", []):
            check(feature.get("type") == "Feature", f"Invalid {label} GeoJSON feature")
            coordinates = feature.get("geometry", {}).get("coordinates", [])
            check(len(coordinates) == 2, f"Invalid {label} coordinate pair")
            lon, lat = coordinates
            check(math.isfinite(lon) and -180 <= lon <= 180, f"Invalid {label} longitude")
            check(math.isfinite(lat) and -90 <= lat <= 90, f"Invalid {label} latitude")
            ids.append(feature.get("id"))
        check(len(ids) == len(set(ids)), f"Duplicate {label} feature IDs")

    cell_features = cell_geo["features"]
    point_features = point_geo["features"]
    check(len(cell_features) == event_manifest["map_date_cell_days"],
          "Cell-day GeoJSON feature count does not match manifest")
    check(len(point_features) == data_manifest["map_date_features"],
          "Point GeoJSON feature count does not match manifest")
    for feature in cell_features:
        props = feature["properties"]
        check(props.get("activity_unit") == "1km_equal_area_cell_day", "Unexpected map activity unit")
        check(sum(props["satellite_counts"].values()) == props["detections"],
              "Cell-day feature satellite counts do not reconcile")
        check(sum(props["fire_type_counts"].values()) == props["detections"],
              "Cell-day feature fire-type counts do not reconcile")
        check(props["source_record_count"] == props["detections"],
              "Cell-day feature source count does not reconcile")

    zip_path = ROOT / "web" / "handoff" / "nasa_firms_web_data.zip"
    with zipfile.ZipFile(zip_path) as archive:
        check(archive.testzip() is None, "Handoff ZIP integrity check failed")

    return {
        "status": "PASS",
        "scope": "generated web artifacts and internal reconciliations; not a fresh full scan of all source rows",
        "months": len(monthly),
        "observations": observation_sum,
        "hotspot_cell_days": cell_day_sum,
        "map_date": event_manifest["map_date"],
        "cell_day_geojson_features": len(cell_features),
        "point_geojson_features": len(point_features),
        "handoff_zip": "PASS",
    }


def main() -> None:
    result = validate()
    REPORTS.mkdir(exist_ok=True)
    report_path = REPORTS / "web_data_validation.json"
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Report written to {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
