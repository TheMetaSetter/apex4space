#!/usr/bin/env python3
"""Build web-ready harmonized daily hotspot-cell activity products.

Operational unit: one 1 km equal-area grid cell on one UTC date. Detections
from all sensor platforms in a cell-day are grouped for calendar activity,
while platform-specific counts and FRP remain separate. A cell-day is not a
confirmed fire or incident.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from itertools import groupby
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed" / "quality_controlled"
OUTPUT_ROOT = ROOT / "web" / "data"
INPUTS = [
    INPUT_ROOT / "MODIS_south_america_all_available.csv",
    INPUT_ROOT / "VIIRS_SNPP_south_america_all_available.csv",
    INPUT_ROOT / "VIIRS_NOAA20_south_america_all_available.csv",
    INPUT_ROOT / "VIIRS_NOAA21_south_america_all_available.csv",
]
EARTH_RADIUS_KM = 6371.0088
CELL_KM = 1.0

TYPE_LABELS = {
    "0": "presumed_vegetation_fire",
    "1": "active_volcano",
    "2": "other_static_land_source",
    "3": "offshore_detection",
    "": "not_provided_by_source",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-date", default="2023-07-12", help="UTC date for map GeoJSON")
    return parser.parse_args()


def rows_by_day(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "latitude", "longitude", "frp", "acq_datetime_utc", "sensor", "satellite",
            "confidence_original", "fire_type", "product_type", "version",
            "source_file", "source_row_number",
        }
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        previous_day = ""
        for row in reader:
            day = row["acq_datetime_utc"][:10]
            if day < previous_day:
                raise ValueError(f"Input is not sorted by acquisition date: {path}")
            previous_day = day
            yield day, row


def equal_area_cell(latitude: float, longitude: float) -> tuple[int, int]:
    """Cylindrical equal-area 1 km indexing; common grid for every sensor."""
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)
    x_km = EARTH_RADIUS_KM * lon_rad
    y_km = EARTH_RADIUS_KM * math.sin(lat_rad)
    return math.floor(x_km / CELL_KM), math.floor(y_km / CELL_KM)


def cell_center_latlon(ix: int, iy: int) -> tuple[float, float]:
    x_km = (ix + 0.5) * CELL_KM
    y_km = (iy + 0.5) * CELL_KM
    longitude = math.degrees(x_km / EARTH_RADIUS_KM)
    latitude = math.degrees(math.asin(max(-1.0, min(1.0, y_km / EARTH_RADIUS_KM))))
    return latitude, longitude


def main() -> None:
    args = parse_args()
    try:
        datetime.strptime(args.map_date, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit("--map-date must use YYYY-MM-DD") from exc
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    merged = heapq.merge(*(rows_by_day(path) for path in INPUTS), key=lambda item: item[0])
    monthly: dict[str, dict] = defaultdict(lambda: {
        "observations": 0,
        "hotspot_cell_days": 0,
        "multi_sensor_cell_days": 0,
        "MODIS_only_cell_days": 0,
        "VIIRS_only_cell_days": 0,
        "terra_backbone_cell_days": 0,
        "terra_only_cell_days": 0,
        "vegetation_type_only_cell_days": 0,
        "other_known_type_only_cell_days": 0,
        "unknown_type_only_cell_days": 0,
        "mixed_or_partly_unknown_type_cell_days": 0,
        "fire_type_observations_by_code": Counter(),
        "detections_by_satellite": Counter(),
        "cell_days_by_satellite": Counter(),
        "frp_max_by_satellite": {},
        "unknown_fire_type_observations": 0,
    })
    map_features = []
    manifest = {
        "generated_at_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "inputs": [p.relative_to(ROOT).as_posix() for p in INPUTS],
        "operational_unit": "1 km equal-area cell x UTC day",
        "grid": "Cylindrical equal-area indexing: x=R*longitude_radians; y=R*sin(latitude_radians); R=6371.0088 km",
        "interpretation": "A harmonized activity unit, not a unique fire or incident. Multiple observations in one cell-day are summarized, and satellite-specific values remain separate.",
        "recommended_long_term_trend": "Use terra_backbone_cell_days as the consistent platform-specific baseline; show the all-sensor union and VIIRS contributions separately because sensor availability changes over time.",
        "fire_type_note": "Type 0 is presumed vegetation fire; known types 1-3 are other source classes; missing type remains unknown. Cell-day type categories are mutually exclusive, but a mixed/unknown cell-day must not be silently treated as type 0.",
        "map_date": args.map_date,
        "observations_read": 0,
        "observations_skipped_invalid": 0,
        "hotspot_cell_days": 0,
        "multi_sensor_cell_days": 0,
        "map_date_cell_days": 0,
        "source_order_checked_by_day": True,
    }

    # All source files are chronologically concatenated archive+NRT streams.
    # Merge by UTC date so memory is bounded to one day of observations.
    for day, day_iter in groupby(merged, key=lambda item: item[0]):
        cells: dict[tuple[int, int], dict] = {}
        for _, row in day_iter:
            manifest["observations_read"] += 1
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                frp = float(row["frp"])
                timestamp = row["acq_datetime_utc"]
                if not (-90 <= lat <= 90 and -180 <= lon <= 180 and math.isfinite(frp) and frp >= 0):
                    raise ValueError("coordinate or FRP out of range")
                if len(timestamp) != 20 or timestamp[10] != "T" or not timestamp.endswith("Z"):
                    raise ValueError("invalid UTC timestamp")
            except (TypeError, ValueError):
                manifest["observations_skipped_invalid"] += 1
                continue

            ix, iy = equal_area_cell(lat, lon)
            key = (ix, iy)
            cell = cells.setdefault(key, {
                "detections": 0,
                "sensor_counts": Counter(),
                "satellite_counts": Counter(),
                "frp_max_by_satellite": {},
                "fire_type_codes": Counter(),
                "confidence_counts_by_satellite": defaultdict(Counter),
                "product_types": Counter(),
                "versions": Counter(),
                "source_ids_sample": [],
                "source_id_count": 0,
            })
            cell["detections"] += 1
            cell["sensor_counts"][row["sensor"]] += 1
            satellite = row["satellite"]
            cell["satellite_counts"][satellite] += 1
            cell["frp_max_by_satellite"][satellite] = max(
                cell["frp_max_by_satellite"].get(satellite, -math.inf), frp
            )
            fire_type = row.get("fire_type", "") or ""
            cell["fire_type_codes"][fire_type if fire_type else "unknown"] += 1
            cell["confidence_counts_by_satellite"][satellite][row["confidence_original"]] += 1
            cell["product_types"][row["product_type"]] += 1
            cell["versions"][row["version"]] += 1
            cell["source_id_count"] += 1
            if len(cell["source_ids_sample"]) < 10:
                cell["source_ids_sample"].append(
                    f"{row['source_file']}:{row['source_row_number']}"
                )

        month = day[:7]
        agg = monthly[month]
        agg["observations"] += sum(cell["detections"] for cell in cells.values())
        agg["hotspot_cell_days"] += len(cells)
        for (ix, iy), cell in cells.items():
            sensors = cell["sensor_counts"]
            satellites = set(cell["satellite_counts"])
            is_multi = len(sensors) > 1
            agg["multi_sensor_cell_days"] += is_multi
            if is_multi:
                manifest["multi_sensor_cell_days"] += 1
            elif "MODIS" in sensors:
                agg["MODIS_only_cell_days"] += 1
            else:
                agg["VIIRS_only_cell_days"] += 1
            has_terra = "Terra" in satellites
            agg["terra_backbone_cell_days"] += has_terra
            agg["terra_only_cell_days"] += satellites == {"Terra"}
            codes = set(cell["fire_type_codes"])
            known_codes = codes - {"unknown"}
            has_unknown = "unknown" in codes
            has_vegetation = "0" in known_codes
            has_other = bool(known_codes & {"1", "2", "3"})
            if has_vegetation and not has_other and not has_unknown:
                agg["vegetation_type_only_cell_days"] += 1
            elif has_other and not has_vegetation and not has_unknown:
                agg["other_known_type_only_cell_days"] += 1
            elif not known_codes and has_unknown:
                agg["unknown_type_only_cell_days"] += 1
            else:
                agg["mixed_or_partly_unknown_type_cell_days"] += 1
            for code, count in cell["fire_type_codes"].items():
                agg["fire_type_observations_by_code"][code] += count
            for satellite, count in cell["satellite_counts"].items():
                agg["detections_by_satellite"][satellite] += count
                agg["cell_days_by_satellite"][satellite] += 1
                agg["frp_max_by_satellite"][satellite] = max(
                    agg["frp_max_by_satellite"].get(satellite, -math.inf),
                    cell["frp_max_by_satellite"][satellite],
                )
            agg["unknown_fire_type_observations"] += cell["fire_type_codes"].get("unknown", 0)

            if day == args.map_date:
                lat_center, lon_center = cell_center_latlon(ix, iy)
                map_features.append({
                    "type": "Feature",
                    "id": f"{day}-EA1K-{ix}-{iy}",
                    "geometry": {"type": "Point", "coordinates": [lon_center, lat_center]},
                    "properties": {
                        "activity_id": f"{day}-EA1K-{ix}-{iy}",
                        "activity_unit": "1km_equal_area_cell_day",
                        "date_utc": day,
                        "latitude": lat_center,
                        "longitude": lon_center,
                        "detections": cell["detections"],
                        "sensor_counts": dict(sorted(cell["sensor_counts"].items())),
                        "satellite_counts": dict(sorted(cell["satellite_counts"].items())),
                        "frp_max_by_satellite": dict(sorted(cell["frp_max_by_satellite"].items())),
                        "fire_type_counts": dict(sorted(cell["fire_type_codes"].items())),
                        "confidence_counts_by_satellite": {
                            sat: dict(sorted(counts.items()))
                            for sat, counts in sorted(cell["confidence_counts_by_satellite"].items())
                        },
                        "product_type_counts": dict(sorted(cell["product_types"].items())),
                        "version_counts": dict(sorted(cell["versions"].items())),
                        "source_record_count": cell["source_id_count"],
                        "source_ids_sample": cell["source_ids_sample"],
                        "source_ids_sample_truncated": cell["source_id_count"] > len(cell["source_ids_sample"]),
                    },
                })
        manifest["hotspot_cell_days"] += len(cells)
        if manifest["observations_read"] % 5_000_000 < sum(c["detections"] for c in cells.values()):
            print(f"Processed {manifest['observations_read']:,} observations through {day}", flush=True)

    calendar = []
    for month in sorted(monthly):
        agg = monthly[month]
        calendar.append({
            "month": month,
            "observations": agg["observations"],
            "hotspot_cell_days": agg["hotspot_cell_days"],
            "multi_sensor_cell_days": agg["multi_sensor_cell_days"],
            "MODIS_only_cell_days": agg["MODIS_only_cell_days"],
            "VIIRS_only_cell_days": agg["VIIRS_only_cell_days"],
            "terra_backbone_cell_days": agg["terra_backbone_cell_days"],
            "terra_only_cell_days": agg["terra_only_cell_days"],
            "vegetation_type_only_cell_days": agg["vegetation_type_only_cell_days"],
            "other_known_type_only_cell_days": agg["other_known_type_only_cell_days"],
            "unknown_type_only_cell_days": agg["unknown_type_only_cell_days"],
            "mixed_or_partly_unknown_type_cell_days": agg["mixed_or_partly_unknown_type_cell_days"],
            "fire_type_observations_by_code": dict(sorted(agg["fire_type_observations_by_code"].items())),
            "detections_by_satellite": dict(sorted(agg["detections_by_satellite"].items())),
            "cell_days_by_satellite": dict(sorted(agg["cell_days_by_satellite"].items())),
            "frp_max_by_satellite": {k: round(v, 3) for k, v in sorted(agg["frp_max_by_satellite"].items())},
            "unknown_fire_type_observations": agg["unknown_fire_type_observations"],
        })

    (OUTPUT_ROOT / "event_calendar_monthly.json").write_text(
        json.dumps(calendar, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    geojson = {
        "type": "FeatureCollection",
        "name": f"hotspot_cell_days_{args.map_date}",
        "features": map_features,
    }
    (OUTPUT_ROOT / f"hotspot_cell_days_{args.map_date}.geojson").write_text(
        json.dumps(geojson, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    manifest["monthly_rows"] = len(calendar)
    manifest["map_date_cell_days"] = len(map_features)
    manifest["detections_by_month_sum"] = sum(row["observations"] for row in calendar)
    (OUTPUT_ROOT / "event_harmonization_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
