"""Stream checked CSV files from Google Drive into small cell sets."""

import csv
import hashlib
import io
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from shapely.geometry import Point, shape

from app.cells import AreaRecord, GridSettings, assign_cell
from app.models import SourceFileRecord
from app.sources import REQUIRED_COLUMNS, _band_fields, _parse_observation, _csv_reader

DRIVE_API = "https://www.googleapis.com/drive/v3"
CSV_MIME_TYPES = {"text/csv", "text/plain", "application/csv"}
CHUNK_BYTES = 64 * 1024
MAX_FIELD_BYTES = 64 * 1024
MAX_RECORD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str
    size: int
    modified_time: str
    version: str
    head_revision_id: str
    md5_checksum: str | None
    sha256_checksum: str | None
    source_id: str


@dataclass(frozen=True)
class ProcessedSource:
    source_id: str
    source_version: str
    sha256: str
    grid_version: str
    area_id: str
    start_date: date
    end_date: date
    daily_cell_sets: Mapping[date, frozenset[str]]
    rows_seen: int
    rows_used: int
    bytes_read: int
    checks: Mapping[str, object]


def load_drive_token() -> str:
    """Read the token from process settings or the local .env without logging it."""
    token = os.environ.get("GOOGLE_DRIVE_ACCESS_TOKEN", "").strip()
    if token:
        return token
    path = Path(__file__).resolve().parents[2] / ".env"
    if path.is_file() and not path.is_symlink():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "GOOGLE_DRIVE_ACCESS_TOKEN":
                token = value.strip().strip("\"'")
                if token:
                    return token
    raise RuntimeError("Google Drive access token is not set")


def _safe_response(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise RuntimeError("Google Drive access expired; renew the local token")
    if response.status_code == 403:
        raise RuntimeError("Google Drive denied access to a selected file")
    if response.status_code == 429 or response.status_code >= 500:
        raise RuntimeError("Google Drive request failed after retry limit")
    response.raise_for_status()


def _get_json(client: httpx.Client, url: str, token: str,
              params: Mapping[str, object] | None = None) -> dict:
    for attempt in range(3):
        try:
            response = client.get(url, params=params,
                                  headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    time.sleep(min(float(response.headers.get("Retry-After", "1")), 5.0))
                    continue
            _safe_response(response)
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("Google Drive returned invalid metadata")
            return value
        except httpx.HTTPError:
            if attempt == 2:
                raise RuntimeError("Google Drive request failed") from None
    raise RuntimeError("Google Drive request failed")


def _metadata(client: httpx.Client, file_id: str, token: str) -> dict:
    return _get_json(client, f"{DRIVE_API}/files/{file_id}", token, {
        "fields": "id,name,mimeType,size,modifiedTime,version,headRevisionId,md5Checksum,sha256Checksum,parents",
        "supportsAllDrives": "true",
    })


def list_drive_csvs(folder_id: str, *, client: httpx.Client,
                    source_ids: Mapping[str, str]) -> tuple[DriveFile, ...]:
    """List CSV metadata in the folder tree; only explicit file mappings are used."""
    token = load_drive_token()
    pending = [folder_id]
    visited: set[str] = set()
    files: dict[str, DriveFile] = {}
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        page_token = None
        while True:
            params = {"q": f"'{current}' in parents and trashed=false",
                      "pageSize": 1000,
                      "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,version,headRevisionId,md5Checksum,sha256Checksum,parents)",
                      "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if page_token:
                params["pageToken"] = page_token
            page = _get_json(client, f"{DRIVE_API}/files", token, params)
            for item in page.get("files", ()):
                mime = item.get("mimeType", "")
                file_id, name = item.get("id", ""), item.get("name", "")
                if mime == "application/vnd.google-apps.folder":
                    pending.append(file_id)
                elif (file_id in source_ids and name.lower().endswith(".csv")
                      and mime in CSV_MIME_TYPES and mime != "application/vnd.google-apps.shortcut"):
                    files[file_id] = DriveFile(
                        file_id=file_id, name=name, mime_type=mime,
                        size=int(item.get("size", 0)), modified_time=item.get("modifiedTime", ""),
                        version=str(item.get("version", "")),
                        head_revision_id=item.get("headRevisionId", ""),
                        md5_checksum=item.get("md5Checksum"),
                        sha256_checksum=item.get("sha256Checksum"), source_id=source_ids[file_id],
                    )
            page_token = page.get("nextPageToken")
            if not page_token:
                break
    return tuple(files[key] for key in sorted(files))


class _HashingBytes(io.RawIOBase):
    """Expose HTTP chunks as a file while counting and hashing every byte."""

    def __init__(self, chunks: Iterator[bytes], maximum_bytes: int):
        self.chunks = iter(chunks)
        self.maximum_bytes = maximum_bytes
        self.digest = hashlib.sha256()
        self.md5 = hashlib.md5()
        self.bytes_read = 0
        self.pending = bytearray()
        self.finished = False

    def readable(self) -> bool:
        return True

    def _next(self) -> bool:
        try:
            chunk = next(self.chunks)
        except StopIteration:
            self.finished = True
            return False
        self.bytes_read += len(chunk)
        if self.bytes_read > self.maximum_bytes:
            raise ValueError("Drive file exceeds the configured byte limit")
        self.digest.update(chunk)
        self.md5.update(chunk)
        self.pending.extend(chunk)
        return True

    def readinto(self, target) -> int:
        while not self.pending and not self.finished:
            self._next()
        count = min(len(target), len(self.pending))
        target[:count] = self.pending[:count]
        del self.pending[:count]
        return count


def _source_record(file: DriveFile, version: str, start_date: date,
                   end_date: date) -> SourceFileRecord:
    product = "MODIS" if file.source_id.startswith("MODIS") else "VIIRS"
    mode = "NRT" if file.source_id.endswith("_NRT") else "standard"
    return SourceFileRecord(
        source_file_id=file.file_id, source_id=file.source_id, product=product,
        version=version, processing_mode=mode, start_date=date.min, end_date=date.max,
        downloaded_at=datetime.now(timezone.utc), sha256="0" * 64,
        request_parameters={"drive_file_id": file.file_id},
    )


def _base_version(value: str, nrt: bool) -> str:
    if not nrt:
        return value
    for suffix in ("NRT", "URT", "RT"):
        if value.endswith(suffix):
            return value[:-len(suffix)]
    raise ValueError("NRT CSV has no known version suffix")


def scan_drive_csv(file: DriveFile, *, client: httpx.Client, grid: GridSettings,
                   area: AreaRecord, start_date: date, end_date: date,
                   platforms: tuple[str, ...], maximum_bytes: int,
                   maximum_memberships: int) -> ProcessedSource:
    """Stream one verified CSV and retain only selected daily cell IDs."""
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", file.file_id)
            or not file.name.lower().endswith(".csv") or file.mime_type not in CSV_MIME_TYPES):
        raise ValueError("Drive selection is not an allowed CSV file")
    if start_date >= end_date or file.size > maximum_bytes or maximum_bytes < 1:
        raise ValueError("invalid date window or Drive file size")
    token = load_drive_token()
    before = _metadata(client, file.file_id, token)
    _check_drive_version(file, before)
    headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"}
    url = f"{DRIVE_API}/files/{file.file_id}?alt=media"
    daily: dict[date, set[str]] = defaultdict(set)
    rows_seen = rows_used = 0
    source = None
    hasher = None
    try:
        with client.stream("GET", url, headers=headers, timeout=60, follow_redirects=False) as response:
            _safe_response(response)
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Drive stream must use identity encoding")
            if "text/html" in response.headers.get("content-type", "").lower():
                raise ValueError("Drive returned an HTML login page")
            hasher = _HashingBytes(response.iter_bytes(CHUNK_BYTES), maximum_bytes)
            with io.TextIOWrapper(hasher, encoding="utf-8-sig", newline="") as text:
                csv.field_size_limit(MAX_FIELD_BYTES)
                reader = _csv_reader(text, REQUIRED_COLUMNS)
                columns = _band_fields(reader.fieldnames or [], "MODIS" if file.source_id.startswith("MODIS") else "VIIRS")
                for row_id, row in enumerate(reader, 1):
                    rows_seen += 1
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("CSV row has the wrong number of fields")
                    if sum(len(value.encode("utf-8")) for value in row.values()) > MAX_RECORD_BYTES:
                        raise ValueError("CSV record exceeds the configured byte limit")
                    version = row["version"]
                    nrt = file.source_id.endswith("_NRT")
                    base = _base_version(version, nrt)
                    if source is None:
                        source = _source_record(file, base, start_date, end_date)
                    observation, _ = _parse_observation(row, row_id, source, columns)
                    if observation.platform not in platforms or not start_date <= observation.observed_at.date() < end_date:
                        continue
                    cell = assign_cell(observation.longitude, observation.latitude, grid)
                    if shape(area.geometry).covers(Point(cell.center_longitude, cell.center_latitude)):
                        day_cells = daily[observation.observed_at.date()]
                        day_cells.add(cell.cell_id)
                        rows_used += 1
                        if sum(len(items) for items in daily.values()) > maximum_memberships:
                            raise ValueError("processed memberships exceed the configured limit")
    except (httpx.HTTPError, UnicodeDecodeError, csv.Error):
        raise RuntimeError("Drive CSV stream failed validation") from None
    if hasher is None or not hasher.finished:
        raise RuntimeError("Drive CSV stream did not reach EOF")
    after = _metadata(client, file.file_id, token)
    _check_drive_version(file, after)
    if before.get("version") != after.get("version") or before.get("modifiedTime") != after.get("modifiedTime"):
        raise ValueError("Drive source changed during streaming")
    digest = hasher.digest.hexdigest()
    if hasher.bytes_read != file.size:
        raise ValueError("Drive source byte length changed")
    if file.sha256_checksum and digest != file.sha256_checksum:
        raise ValueError("Drive source checksum does not match")
    if file.md5_checksum and hasher.md5.hexdigest() != file.md5_checksum:
        raise ValueError("Drive source checksum does not match")
    if source is None:
        raise ValueError("Drive CSV contains no data rows")
    return ProcessedSource(file.source_id, source.version, digest, grid.grid_version,
        area.area_id, start_date, end_date,
        {day: frozenset(values) for day, values in daily.items()},
        rows_seen, rows_used, hasher.bytes_read,
        {"version_unchanged": True, "length_checked": True, "sha256": digest,
         "modified_time": file.modified_time})


def _check_drive_version(file: DriveFile, metadata: Mapping[str, object]) -> None:
    if (metadata.get("id") != file.file_id or metadata.get("name") != file.name
            or int(metadata.get("size", -1)) != file.size
            or str(metadata.get("version", "")) != file.version
            or metadata.get("headRevisionId", "") != file.head_revision_id):
        raise ValueError("Drive file identity or version changed")
