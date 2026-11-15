"""Read-only queries for the focused Viet Nam and South America catalog."""

import base64
from datetime import date, timedelta
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from fastapi import Request
from pydantic import BaseModel, ConfigDict, StrictInt, Field, field_validator, model_validator
from shapely import intersects_xy

from app.areas import AreaError, resolve_area_name
from app.models import ApiError

_GRID_VERSIONS = {"firms-ease-global-10km-v2", "firms-ease-north-10km-v2", "firms-ease-south-10km-v2"}


class _Query(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    release_id: str
    area_name: str

    @model_validator(mode='after')
    def cloud_page_limit(self):
        if os.environ.get('FRISM_CLOUD') == '1' and getattr(self, 'page_size', 1) > 1000:
            raise ValueError('Cloud map pages contain at most 1000 cells.')
        return self

    @field_validator("release_id")
    @classmethod
    def valid_release(cls, value):
        if not re.fullmatch(r"[0-9a-f]{64}", value): raise ValueError("release_id must be lowercase SHA-256")
        return value

    @field_validator("area_name")
    @classmethod
    def valid_area(cls, value):
        if not value.strip() or len(value) > 200: raise ValueError("area_name is invalid")
        return value


class HotspotQuery(_Query):
    date: date
    page_size: StrictInt = 1000
    cursor: str | None = None

    @field_validator("page_size")
    @classmethod
    def valid_page(cls, value):
        if not 1 <= value <= 10000: raise ValueError("page_size must be 1..10000")
        return value

    @field_validator("cursor")
    @classmethod
    def valid_cursor_size(cls, value):
        if value is not None and len(value) > 2048: raise ValueError("cursor is too long")
        return value


class SummaryQuery(_Query):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date >= self.end_date or (self.end_date - self.start_date).days > 366:
            raise ValueError("date range must be 1..366 days, with exclusive end_date")
        return self


class CellFeature(BaseModel):
    type: str = "Feature"
    id: str
    properties: dict[str, str]
    geometry: dict


class GridProvenance(BaseModel):
    source_projection: str | None = None
    cell_size_m: int | None = None
    membership_rule: str | None = None
    equal_area: bool | None = None
    metric: str | None = None
    source_dates: list[str] = Field(default_factory=list)
    grid_version: str | None = None
    geometry_rule: str | None = None


class HotspotResponse(GridProvenance):
    release_id: str
    area_id: str
    area_name: str
    catalog_version: str
    date: date
    grid_versions: list[str]
    active_cell_count: int
    status: str
    warnings: list[str]
    type: str = "FeatureCollection"
    features: list[CellFeature]
    returned_count: int
    has_more: bool
    next_cursor: str | None


class DailySummary(BaseModel):
    date: date
    active_cell_count: int
    status: str
    input_state: str


class SummaryResponse(GridProvenance):
    release_id: str
    area_id: str
    area_name: str
    catalog_version: str
    start_date: date
    end_date: date
    days: list[DailySummary]


def _check_deadline(started):
    if time.monotonic() - started > 5:
        raise ApiError(503, "QUERY_TIMEOUT", "Area query timed out.")


def _database(settings, release_id, seconds=5):
    directory = settings.storage.global_release_path
    if directory is None or settings.storage.world_areas_path is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The focused database is not configured.")
    try:
        manifest = json.loads((directory / "manifest.json").read_bytes())
        if manifest.get("schema_version") != 2: raise ApiError(409, "UNSUPPORTED_SCHEMA", "Schema 2 is required.")
        if manifest.get("release_id") != release_id: raise ApiError(409, "UNSUPPORTED_SCHEMA", "The requested release is not selected.")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("logical_sha256", "")):
            raise ValueError("release logical hash is invalid")
        if manifest.get("grid_policy_version") != "firms-ease-10km-v2" or set(manifest.get("memberships_by_grid", {})) - _GRID_VERSIONS:
            raise ApiError(409, "UNSUPPORTED_SCHEMA", "The release grid is not supported.")
        connection = sqlite3.connect((directory / "database.sqlite3").as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        started = time.monotonic()
        connection.set_progress_handler(lambda: int(time.monotonic() - started > seconds), 10000)
        return connection, manifest
    except ApiError: raise
    except Exception as error:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The focused database is unavailable.") from error


def _cursor(secret, manifest, area, catalog, query, last=None):
    value = {"v": 2, "release_id": manifest["release_id"], "snapshot_sha256": manifest.get("snapshot_sha256") or manifest["logical_sha256"],
        "area_id": area["id"], "catalog_version": catalog["version"], "date": query.date.isoformat(),
        "grid_versions": sorted(manifest.get("memberships_by_grid", {})),
        "page_size": query.page_size, "last": last}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(secret, raw, hashlib.sha256).digest()).decode().rstrip("=")
    return token + "." + sig


def _decode_cursor(token, secret, manifest, area, catalog, query):
    try:
        encoded, signed = token.split("."); raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        signature = base64.urlsafe_b64decode(signed + "=" * (-len(signed) % 4))
        expected = hmac.new(secret, raw, hashlib.sha256).digest()
        value = json.loads(raw)
        expected_payload = {"v": 2, "release_id": manifest["release_id"], "snapshot_sha256": manifest.get("snapshot_sha256") or manifest["logical_sha256"],
            "area_id": area["id"], "catalog_version": catalog["version"], "date": query.date.isoformat(),
            "grid_versions": sorted(manifest.get("memberships_by_grid", {})), "page_size": query.page_size}
        if (set(value) != {*expected_payload, "last"} or not hmac.compare_digest(signature, expected)
                or any(value.get(key) != val for key, val in expected_payload.items())
                or not isinstance(value.get("last"), list) or len(value["last"]) != 2
                or not all(isinstance(part, str) and part for part in value["last"])):
            raise ValueError
        return value["last"]
    except Exception:
        raise ApiError(422, "INVALID_CURSOR", "The cursor is invalid for this request.") from None


def _area(catalog, query):
    try: return resolve_area_name(catalog, query.area_name)
    except AreaError as error:
        raise ApiError(error.status, error.code, str(error), details={"candidates": list(error.candidates)}) from None


def _select_area_cells(connection, area):
    geometry = area["geometry"]; west, south, east, north = geometry.bounds
    connection.execute("CREATE TEMP TABLE selected_area_cells(grid_version TEXT,cell_id TEXT,PRIMARY KEY(grid_version,cell_id)) WITHOUT ROWID")
    candidates = connection.execute("SELECT grid_version,cell_id,center_longitude,center_latitude FROM hotspot_cell WHERE center_longitude BETWEEN ? AND ? AND center_latitude BETWEEN ? AND ?", (west,east,south,north))
    rows = list(candidates)
    matches = intersects_xy(geometry, [row[2] for row in rows], [row[3] for row in rows])
    selected = [(row[0], row[1]) for row, match in zip(rows, matches) if match]
    connection.executemany("INSERT INTO selected_area_cells VALUES(?,?)", selected)
    return len(selected)


def _rows(connection, area, release_id, start, end=None, after=None):
    selected_count = _select_area_cells(connection, area)
    # Small areas use cell lookups; continents let SQLite use the date range.
    join = "CROSS JOIN" if selected_count < 1000 else "JOIN"
    index = "INDEXED BY hotspot_cell_day_cell_date" if selected_count < 1000 else ""
    sql = f"SELECT c.grid_version,c.cell_id,c.center_longitude,c.center_latitude,c.geometry_json,d.date FROM selected_area_cells s {join} hotspot_cell c USING(grid_version,cell_id) {join} hotspot_cell_day d {index} ON d.grid_version=c.grid_version AND d.cell_id=c.cell_id WHERE d.release_id=? AND d.date>=?"
    args = [release_id, start.isoformat()]
    if end is None: sql += " AND d.date=?"; args.append(start.isoformat())
    else: sql += " AND d.date<?"; args.append(end.isoformat())
    if after is not None: sql += " AND (c.grid_version,c.cell_id)>(?,?)"; args.extend(after)
    sql += " ORDER BY " + ("d.date," if end is not None else "") + "c.grid_version,c.cell_id"
    try:
        yield from connection.execute(sql, args)
    finally:
        connection.execute("DROP TABLE selected_area_cells")


def _daily_counts(connection, area, release_id, start, end):
    selected_count = _select_area_cells(connection, area)
    # Small areas use cell lookups; continents let SQLite use the date range.
    join = "CROSS JOIN" if selected_count < 1000 else "JOIN"
    index = "INDEXED BY hotspot_cell_day_cell_date" if selected_count < 1000 else ""
    try:
        rows = connection.execute(f"SELECT d.date,count(*) FROM selected_area_cells s {join} hotspot_cell_day d {index} ON d.grid_version=s.grid_version AND d.cell_id=s.cell_id WHERE d.release_id=? AND d.date>=? AND d.date<? GROUP BY d.date", (release_id, start.isoformat(), end.isoformat()))
        return dict(rows)
    finally:
        connection.execute("DROP TABLE selected_area_cells")


def query_hotspots(query: HotspotQuery, request: Request):
    if request.app.state.settings.storage.data_format == "parquet":
        from app.parquet_data import daily
        return daily(query, request)
    settings = request.app.state.settings; catalog = request.app.state.world_areas
    if catalog is None: raise ApiError(503, "DATABASE_UNAVAILABLE", "The area catalog is unavailable.")
    area = _area(catalog, query); connection, manifest = _database(settings, query.release_id)
    try:
        if query.date.isoformat() < manifest["date_start"] or query.date.isoformat() > manifest["date_end"]:
            raise ApiError(422, "DATE_UNAVAILABLE", "The date is outside the imported range.", details={"start": manifest["date_start"], "end": manifest["date_end"]})
        after = _decode_cursor(query.cursor, request.app.state.cursor_secret, manifest, area, catalog, query) if query.cursor else None
        count = 0; features = []; last = None; more = False; started = time.monotonic()
        for row in _rows(connection, area, query.release_id, query.date):
            count += 1; key = [row["grid_version"], row["cell_id"]]
            if (after is None or key > after) and len(features) < query.page_size + 1:
                features.append((key, row))
            _check_deadline(started)
        features.sort(key=lambda item: item[0]); more = len(features) > query.page_size
        if more: features.pop()
        last = features[-1][0] if more and features else None
        grid_versions = sorted({item[0][0] for item in features})
        warnings = ["Coverage is unknown; zero does not mean no fire."]
        if any(version.endswith(("north-10km-v2", "south-10km-v2")) for version in grid_versions):
            warnings.append("Polar cells are outside the EPSG:6933 map area.")
        return {"release_id": query.release_id, "area_id": area["id"], "area_name": area["name"],
            "catalog_version": catalog["version"], "date": query.date.isoformat(),
            "grid_versions": grid_versions, "active_cell_count": count,
            "status": "coverage_unknown", "warnings": warnings,
            "type": "FeatureCollection", "features": [{"type": "Feature", "id": f"{key[0]}:{key[1]}",
                "properties": {"grid_version": key[0], "cell_id": key[1]}, "geometry": json.loads(row["geometry_json"])} for key, row in features],
            "returned_count": len(features), "has_more": more,
            "next_cursor": _cursor(request.app.state.cursor_secret, manifest, area, catalog, query, last) if last else None}
    except sqlite3.OperationalError as error:
        if "interrupt" in str(error).lower():
            raise ApiError(503, "QUERY_TIMEOUT", "Area query timed out.") from None
        raise
    finally: connection.close()


def query_summaries(query: SummaryQuery, request: Request):
    if request.app.state.settings.storage.data_format == "parquet":
        from app.parquet_data import summaries
        return summaries(query, request)
    settings = request.app.state.settings; catalog = request.app.state.world_areas
    if catalog is None: raise ApiError(503, "DATABASE_UNAVAILABLE", "The area catalog is unavailable.")
    area = _area(catalog, query); connection, manifest = _database(settings, query.release_id)
    try:
        if query.start_date.isoformat() < manifest["date_start"] or (query.end_date - timedelta(days=1)).isoformat() > manifest["date_end"]:
            raise ApiError(422, "DATE_UNAVAILABLE", "The date range is outside the imported range.", details={"start": manifest["date_start"], "end": manifest["date_end"]})
        started = time.monotonic()
        counts = _daily_counts(connection, area, query.release_id, query.start_date, query.end_date)
        _check_deadline(started)
        days = []
        day = query.start_date
        while day < query.end_date:
            _check_deadline(started)
            text = day.isoformat()
            state = connection.execute("SELECT input_state FROM daily_hotspot_summary WHERE release_id=? AND date=?", (query.release_id, text)).fetchone()
            days.append({"date": text, "active_cell_count": counts.get(text, 0), "status": "coverage_unknown",
                "input_state": state[0] if state else "no_records"})
            day += timedelta(days=1)
        return {"release_id": query.release_id, "area_id": area["id"], "area_name": area["name"],
            "catalog_version": catalog["version"], "start_date": query.start_date.isoformat(),
            "end_date": query.end_date.isoformat(), "days": days}
    except sqlite3.OperationalError as error:
        if "interrupt" in str(error).lower():
            raise ApiError(503, "QUERY_TIMEOUT", "Area query timed out.") from None
        raise
    finally: connection.close()
