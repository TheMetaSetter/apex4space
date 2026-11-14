#!/usr/bin/env python3
"""Build web-ready GeoJSON and summary outputs from a pilot match CSV."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "processed/harmonized/pilot_2023-07-12_2023-07-12_modis_viirs_matches.csv"
OUTPUT = ROOT / "processed/harmonized"


def point(latitude: str, longitude: str) -> dict:
    return {"type": "Point", "coordinates": [float(longitude), float(latitude)]}


def main() -> None:
    features = []
    counts = Counter()
    distances = []
    times = []
    with INPUT.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            event_class = row["event_class"]
            counts[event_class] += 1
            if row["distance_km"]:
                distances.append(float(row["distance_km"]))
                times.append(float(row["time_difference_minutes"]))

            if event_class == "both_detected":
                latitude = (float(row["modis_latitude"]) + float(row["viirs_latitude"])) / 2
                longitude = (float(row["modis_longitude"]) + float(row["viirs_longitude"])) / 2
                properties = {
                    "event_id": row["event_id"],
                    "event_class": event_class,
                    "distance_km": float(row["distance_km"]),
                    "time_difference_minutes": float(row["time_difference_minutes"]),
                    "modis_frp": float(row["modis_frp"]),
                    "viirs_frp": float(row["viirs_frp"]),
                    "modis_confidence": row["modis_confidence_original"],
                    "viirs_confidence": row["viirs_confidence_original"],
                }
            elif event_class == "MODIS_only":
                latitude, longitude = row["modis_latitude"], row["modis_longitude"]
                properties = {
                    "event_id": row["event_id"],
                    "event_class": event_class,
                    "frp": float(row["modis_frp"]),
                    "confidence": row["modis_confidence_original"],
                    "sensor": "MODIS",
                }
            else:
                latitude, longitude = row["viirs_latitude"], row["viirs_longitude"]
                properties = {
                    "event_id": row["event_id"],
                    "event_class": event_class,
                    "frp": float(row["viirs_frp"]),
                    "confidence": row["viirs_confidence_original"],
                    "sensor": "VIIRS",
                }
            features.append({
                "type": "Feature",
                "geometry": point(latitude, longitude),
                "properties": properties,
            })

    geojson = {
        "type": "FeatureCollection",
        "name": "south_america_modis_viirs_pilot_2023-07-12",
        "features": features,
    }
    (OUTPUT / "pilot_2023-07-12_hotspot_events.geojson").write_text(
        json.dumps(geojson, ensure_ascii=True), encoding="utf-8"
    )
    summary = {
        "date": "2023-07-12",
        "matching_rule": {"distance_km": 2, "time_minutes": 60},
        "event_counts": dict(counts),
        "total_events": len(features),
        "matched_distance_median_km": sorted(distances)[len(distances) // 2] if distances else None,
        "matched_time_difference_median_minutes": sorted(times)[len(times) // 2] if times else None,
        "geojson_file": "processed/harmonized/pilot_2023-07-12_hotspot_events.geojson",
        "warning": "Pilot exploratory output; matching is not a calibrated probability or fire perimeter.",
    }
    (OUTPUT / "pilot_2023-07-12_dashboard_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
