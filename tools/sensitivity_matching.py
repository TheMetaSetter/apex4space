#!/usr/bin/env python3
"""Run matching sensitivity analysis on one bounded date range."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "processed/quality_controlled"
REPORT_ROOT = ROOT / "reports"
MODIS_FILE = INPUT_ROOT / "MODIS_south_america_all_available.csv"
VIIRS_FILES = sorted(INPUT_ROOT.glob("VIIRS_*_south_america_all_available.csv"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    return parser.parse_args()


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def distance_km(a: dict, b: dict) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(float(a["latitude"])), math.radians(float(b["latitude"]))
    dp = math.radians(float(b["latitude"]) - float(a["latitude"]))
    dl = math.radians(float(b["longitude"]) - float(a["longitude"]))
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def load(path: Path, start: datetime, end: datetime) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            dt = parse_dt(row["acq_datetime_utc"])
            if start <= dt < end:
                row["_dt"] = dt
                row["_matched"] = False
                records.append(row)
    return records


def match_count(modis: list[dict], viirs: list[dict], max_distance: float, max_minutes: float) -> dict:
    matched = 0
    for v in viirs:
        best = None
        for m in modis:
            if m["_matched"]:
                continue
            delta = abs((m["_dt"] - v["_dt"]).total_seconds()) / 60
            if delta > max_minutes:
                continue
            distance = distance_km(m, v)
            if distance <= max_distance and (best is None or (distance, delta) < best[0]):
                best = ((distance, delta), m)
        if best:
            best[1]["_matched"] = True
            matched += 1
    return {
        "both_detected": matched,
        "MODIS_only": len(modis) - matched,
        "VIIRS_only": len(viirs) - matched,
        "total_events": len(modis) + len(viirs) - matched,
    }


def main() -> None:
    args = parse_args()
    start = datetime.strptime(args.start_date, "%Y-%m-%d")
    end = datetime.strptime(args.end_date, "%Y-%m-%d") + timedelta(days=1)
    modis = load(MODIS_FILE, start, end)
    viirs = []
    for path in VIIRS_FILES:
        viirs.extend(load(path, start, end))

    configurations = [(0.5, 15), (1, 30), (2, 60), (5, 120)]
    results = []
    for max_distance, max_minutes in configurations:
        result = match_count(
            [dict(row) for row in modis],
            [dict(row) for row in viirs],
            max_distance,
            max_minutes,
        )
        result.update({"distance_km": max_distance, "time_minutes": max_minutes})
        results.append(result)

    report = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "modis_records": len(modis),
        "viirs_records": len(viirs),
        "configurations": results,
        "warning": "Greedy one-to-one sensitivity analysis; not a calibrated probability or fire perimeter.",
    }
    REPORT_ROOT.mkdir(exist_ok=True)
    output = REPORT_ROOT / f"sensitivity_{args.start_date}_{args.end_date}.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
