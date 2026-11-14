#!/usr/bin/env python3
"""Pilot MODIS–VIIRS spatiotemporal matching.

This is a deterministic, one-to-one greedy matcher for a bounded date range.
It is not a fire-perimeter reconstruction or a probability model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed" / "quality_controlled"
OUTPUT_ROOT = ROOT / "processed" / "harmonized"
REPORT_ROOT = ROOT / "reports"

MODIS_FILE = INPUT_ROOT / "MODIS_south_america_all_available.csv"
VIIRS_FILES = sorted(INPUT_ROOT.glob("VIIRS_*_south_america_all_available.csv"))

FIELDNAMES = [
    "event_id",
    "event_class",
    "modis_source_file",
    "modis_source_row_number",
    "viirs_source_file",
    "viirs_source_row_number",
    "modis_satellite",
    "viirs_satellite",
    "modis_latitude",
    "modis_longitude",
    "viirs_latitude",
    "viirs_longitude",
    "distance_km",
    "time_difference_minutes",
    "modis_frp",
    "viirs_frp",
    "modis_confidence_original",
    "viirs_confidence_original",
    "modis_confidence_score",
    "viirs_confidence_score",
    "matching_distance_km",
    "matching_time_minutes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, help="UTC date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="UTC date YYYY-MM-DD, inclusive")
    parser.add_argument("--distance-km", type=float, default=2.0)
    parser.add_argument("--time-minutes", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def in_range(value: str, start: datetime, end: datetime) -> bool:
    parsed = parse_datetime(value)
    return start <= parsed < end


def event_id(prefix: str, source: str, row_number: str) -> str:
    digest = hashlib.sha1(f"{source}:{row_number}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def grid_key(lat: float, lon: float, cell_size: float = 0.02) -> tuple[int, int]:
    return math.floor(lat / cell_size), math.floor(lon / cell_size)


def time_bucket(value: datetime, minutes: int = 30) -> int:
    return int(value.timestamp() // (minutes * 60))


def load_modis(start: datetime, end: datetime) -> list[dict]:
    records = []
    with MODIS_FILE.open("r", encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            if not in_range(row["acq_datetime_utc"], start, end):
                continue
            row["_row_number"] = str(row_number)
            row["_datetime"] = parse_datetime(row["acq_datetime_utc"])
            row["_matched"] = False
            row["_grid"] = grid_key(float(row["latitude"]), float(row["longitude"]))
            row["_time_bucket"] = time_bucket(row["_datetime"])
            records.append(row)
    return records


def load_viirs(start: datetime, end: datetime) -> list[dict]:
    records = []
    for path in VIIRS_FILES:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                if not in_range(row["acq_datetime_utc"], start, end):
                    continue
                row["_source_file"] = row["source_file"]
                row["_row_number"] = str(row_number)
                row["_datetime"] = parse_datetime(row["acq_datetime_utc"])
                row["_grid"] = grid_key(float(row["latitude"]), float(row["longitude"]))
                row["_time_bucket"] = time_bucket(row["_datetime"])
                records.append(row)
    return records


def output_row(event: dict, modis: Optional[dict], viirs: Optional[dict], distance: Optional[float], delta: Optional[float], distance_limit: float, time_limit: float) -> dict:
    return {
        "event_id": event,
        "event_class": "both_detected" if modis and viirs else "MODIS_only" if modis else "VIIRS_only",
        "modis_source_file": modis.get("source_file", "") if modis else "",
        "modis_source_row_number": modis.get("_row_number", "") if modis else "",
        "viirs_source_file": viirs.get("source_file", "") if viirs else "",
        "viirs_source_row_number": viirs.get("_row_number", "") if viirs else "",
        "modis_satellite": modis.get("satellite", "") if modis else "",
        "viirs_satellite": viirs.get("satellite", "") if viirs else "",
        "modis_latitude": modis.get("latitude", "") if modis else "",
        "modis_longitude": modis.get("longitude", "") if modis else "",
        "viirs_latitude": viirs.get("latitude", "") if viirs else "",
        "viirs_longitude": viirs.get("longitude", "") if viirs else "",
        "distance_km": f"{distance:.4f}" if distance is not None else "",
        "time_difference_minutes": f"{delta:.2f}" if delta is not None else "",
        "modis_frp": modis.get("frp", "") if modis else "",
        "viirs_frp": viirs.get("frp", "") if viirs else "",
        "modis_confidence_original": modis.get("confidence_original", "") if modis else "",
        "viirs_confidence_original": viirs.get("confidence_original", "") if viirs else "",
        "modis_confidence_score": modis.get("confidence_score", "") if modis else "",
        "viirs_confidence_score": viirs.get("confidence_score", "") if viirs else "",
        "matching_distance_km": distance_limit,
        "matching_time_minutes": time_limit,
    }


def main() -> None:
    args = parse_args()
    start = datetime.strptime(args.start_date, "%Y-%m-%d")
    end = datetime.strptime(args.end_date, "%Y-%m-%d") + timedelta(days=1)
    if end <= start:
        raise SystemExit("end-date must be on or after start-date")

    modis = load_modis(start, end)
    viirs = load_viirs(start, end)
    index: defaultdict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index_number, row in enumerate(modis):
        index[(row["_grid"][0], row["_grid"][1], row["_time_bucket"])].append(index_number)

    matches: list[dict] = []
    for viirs_row in viirs:
        candidates = []
        gx, gy = viirs_row["_grid"]
        bucket = viirs_row["_time_bucket"]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dt in (-2, -1, 0, 1, 2):
                    candidates.extend(index.get((gx + dx, gy + dy, bucket + dt), []))
        best = None
        for candidate_index in set(candidates):
            modis_row = modis[candidate_index]
            if modis_row["_matched"]:
                continue
            distance = haversine_km(
                float(modis_row["latitude"]), float(modis_row["longitude"]),
                float(viirs_row["latitude"]), float(viirs_row["longitude"]),
            )
            delta = abs((modis_row["_datetime"] - viirs_row["_datetime"]).total_seconds()) / 60
            if distance <= args.distance_km and delta <= args.time_minutes:
                rank = (distance, delta)
                if best is None or rank < best[0]:
                    best = (rank, candidate_index, distance, delta)
        if best:
            _, candidate_index, distance, delta = best
            modis[candidate_index]["_matched"] = True
            matches.append(output_row(
                event_id("B", viirs_row["source_file"], viirs_row["_row_number"]),
                modis[candidate_index], viirs_row, distance, delta, args.distance_km, args.time_minutes,
            ))
        else:
            matches.append(output_row(
                event_id("V", viirs_row["source_file"], viirs_row["_row_number"]),
                None, viirs_row, None, None, args.distance_km, args.time_minutes,
            ))

    for row in modis:
        if not row["_matched"]:
            matches.append(output_row(
                event_id("M", row["source_file"], row["_row_number"]),
                row, None, None, None, args.distance_km, args.time_minutes,
            ))

    output = args.output or OUTPUT_ROOT / f"pilot_{args.start_date}_{args.end_date}_modis_viirs_matches.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(matches)

    counts = defaultdict(int)
    distances = []
    deltas = []
    for row in matches:
        counts[row["event_class"]] += 1
        if row["distance_km"]:
            distances.append(float(row["distance_km"]))
            deltas.append(float(row["time_difference_minutes"]))
    report = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "distance_km": args.distance_km,
        "time_minutes": args.time_minutes,
        "modis_records": len(modis),
        "viirs_records": len(viirs),
        "event_counts": dict(counts),
        "matched_distance_median_km": sorted(distances)[len(distances) // 2] if distances else None,
        "matched_time_difference_median_minutes": sorted(deltas)[len(deltas) // 2] if deltas else None,
        "output_file": output.relative_to(ROOT).as_posix(),
        "warning": "Greedy one-to-one pilot matching; not a calibrated probability or fire perimeter.",
    }
    REPORT_ROOT.mkdir(exist_ok=True)
    report_path = REPORT_ROOT / f"pilot_{args.start_date}_{args.end_date}_matching.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
