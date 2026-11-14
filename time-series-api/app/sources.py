"""Read checked FIRMS CSV files and small test visit files.

The readers preserve source rows. Selection happens after all files are read.
"""

import csv
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from pydantic import JsonValue, TypeAdapter
import httpx

from app.models import AreaGeometry, BBox, BandRecord, ObservationRecord, OpportunityRecord, SourceBatch, SourceFileRecord

PLATFORMS = {
    "MODIS": {"A": "Aqua", "T": "Terra", "Aqua": "Aqua", "Terra": "Terra"},
    "VIIRS": {"N": "Suomi-NPP", "SNPP": "Suomi-NPP", "N20": "NOAA-20", "N21": "NOAA-21", "1": "NOAA-20", "2": "NOAA-21"},
}
BAND_COLUMNS = {
    "MODIS": {"brightness": "MODIS_21_22", "bright_t31": "MODIS_31"},
    "VIIRS": {"bright_ti4": "VIIRS_I4", "brightness": "VIIRS_I4", "bright_ti5": "VIIRS_I5", "brightness_2": "VIIRS_I5", "bright_t31": "VIIRS_bright_t31_unverified"},
}
PRIMARY_BAND_COLUMNS = {"MODIS": {"brightness"}, "VIIRS": {"bright_ti4", "brightness"}}
REQUIRED_COLUMNS = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "version"}
SOURCE_PLATFORMS = {"MODIS": None, "VIIRS_SNPP": "Suomi-NPP", "VIIRS_NOAA20": "NOAA-20", "VIIRS_NOAA21": "NOAA-21"}
FIRMS_HOST = "https://firms.modaps.eosdis.nasa.gov"
FIRMS_SOURCES = {"MODIS_NRT", "MODIS_SP", "VIIRS_SNPP_NRT", "VIIRS_SNPP_SP",
                 "VIIRS_NOAA20_NRT", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT", "VIIRS_NOAA21_SP"}

def _firms_key() -> str:
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if key: return key
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.is_file() and not env_path.is_symlink():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "FIRMS_MAP_KEY":
                key = value.strip().strip("\"'")
                if key: return key
    raise RuntimeError("FIRMS_MAP_KEY is not set")

def _transaction_count(client: httpx.Client, key: str, timeout: float) -> int:
    url = f"{FIRMS_HOST}/mapserver/mapkey_status/"
    try:
        response = client.get(url, params={"MAP_KEY": key}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        count = data.get("current_transactions") if isinstance(data, dict) else None
        if type(count) is not int or count < 0: raise ValueError("invalid transaction count")
        return count
    except Exception as error:
        raise RuntimeError("FIRMS transaction status is unknown") from None

def _check_budget(client: httpx.Client, key: str, settings, *, reserve: int = 1) -> None:
    used = _transaction_count(client, key, settings.downloads.timeout_seconds)
    if used + 1 + reserve >= settings.downloads.transaction_pause_at: raise RuntimeError("FIRMS transaction pause limit reached")

def _get_text(client: httpx.Client, url: str, key: str, settings) -> str:
    # NASA's usage example reports five transactions for availability.
    reserve = 5 if "/api/data_availability/" in url else 1
    for attempt in range(settings.downloads.retry_limit + 1):
        _check_budget(client, key, settings, reserve=reserve)
        try:
            response = client.get(url, timeout=settings.downloads.timeout_seconds)
            response.raise_for_status()
            text = response.text
            if text.lstrip().startswith("<"): raise RuntimeError("FIRMS returned a non-CSV response")
            return text
        except Exception:
            if attempt == settings.downloads.retry_limit:
                raise RuntimeError("FIRMS request failed") from None
    raise RuntimeError("FIRMS request failed")

def _available_dates(client: httpx.Client, key: str, source_id: str, settings) -> tuple[date, date]:
    url = f"{FIRMS_HOST}/api/data_availability/csv/{quote(key, safe='')}/{source_id}"
    rows = list(csv.DictReader(_get_text(client, url, key, settings).splitlines()))
    match = next((row for row in rows if row.get("data_id") == source_id), None)
    try:
        first, last = date.fromisoformat(match["min_date"]), date.fromisoformat(match["max_date"])
    except (TypeError, KeyError, ValueError):
        raise RuntimeError("FIRMS availability is unknown") from None
    if first > last: raise RuntimeError("FIRMS availability is invalid")
    return first, last

def _progress_path(root: Path) -> Path:
    return root / "download-progress.json"

def _read_progress(root: Path) -> dict[str, dict[str, str]]:
    path = _progress_path(root)
    if not path.exists(): return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000: raise RuntimeError("download progress file is unsafe")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("download progress file is invalid") from None
    required = {"file", "sha256", "bbox", "source", "start_date", "end_date", "downloaded_at"}
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict)
        or not required.issubset(value)
        or any(not isinstance(value[name], str) for name in required)
        for key, value in data.items()
    ):
        raise RuntimeError("download progress file is invalid")
    return data

def _write_progress(root: Path, progress: dict[str, dict[str, str]]) -> None:
    path = _progress_path(root)
    fd, temporary = tempfile.mkstemp(prefix="progress-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(progress, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def _saved_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.iterdir()
               if path.is_file() and not path.is_symlink() and path.name != "download-progress.json")

def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def _downloaded_record(path: Path, source_id: str, start: date, end: date,
                       settings, downloaded_at: datetime | None = None) -> SourceFileRecord:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = _csv_reader(stream, REQUIRED_COLUMNS)
        first = next(reader, None)
        version = first["version"] if first else "unknown"
        if source_id.endswith("_NRT"):
            for suffix in ("NRT", "URT", "RT"):
                if version.endswith(suffix):
                    version = version[:-len(suffix)]
                    break
        if first:
            sample_source = _source_record(path, source_id, version, start, end, settings.downloads.bbox, downloaded_at)
            _observation_time(first, sample_source)
            _platform(first, sample_source)
            _band_fields(reader.fieldnames or [], sample_source.product)
        for row in reader:
            if row["version"] not in ({version + "NRT", version + "RT", version + "URT"} if source_id.endswith("_NRT") else {version}):
                raise ValueError("mixed source collection versions")
            if not start <= date.fromisoformat(row["acq_date"]) < end:
                raise ValueError("provider returned a row outside the requested window")
    record = _source_record(path, source_id, version, start, end, settings.downloads.bbox, downloaded_at)
    for _ in read_source(path, record, batch_size=1000):
        pass
    return record

def _source_record(path: Path, source_id: str, version: str, start: date,
                   end: date, bbox: BBox, downloaded_at: datetime | None = None) -> SourceFileRecord:
    return SourceFileRecord(
        source_file_id=f"{source_id}_{start.isoformat()}_{end.isoformat()}",
        source_id=source_id, product="MODIS" if source_id.startswith("MODIS") else "VIIRS",
        version=version, processing_mode="NRT" if source_id.endswith("_NRT") else "standard",
        start_date=start, end_date=end, downloaded_at=downloaded_at or datetime.now(timezone.utc),
        sha256=_sha256(path),
        request_parameters={"start_date": start.isoformat(), "end_date": end.isoformat(),
                            "source": source_id, "bbox": list(bbox)},
    )

def _fetch_window(client: httpx.Client, key: str, source_id: str, start: date,
                  days: int, settings, root: Path,
                  progress: dict[str, dict[str, str]]) -> SourceFileRecord:
    end = start + timedelta(days=days)
    identity = f"{source_id}:{start.isoformat()}:{end.isoformat()}"
    west, south, east, north = settings.downloads.bbox
    bbox = ",".join(str(value) for value in (west, south, east, north))
    saved = progress.get(identity)
    if saved:
        name, digest = saved.get("file", ""), saved.get("sha256", "")
        path = root / name
        if saved.get("bbox") != bbox or Path(name).name != name or path.is_symlink() or not path.is_file():
            raise RuntimeError("saved download path is unsafe")
        if _sha256(path) == digest:
            downloaded_at = datetime.fromisoformat(saved["downloaded_at"])
            if downloaded_at.tzinfo is None or downloaded_at.utcoffset() != timedelta(0):
                raise RuntimeError("saved download time is invalid")
            return _downloaded_record(path, source_id, start, end, settings, downloaded_at)
        raise RuntimeError("saved download hash does not match")
    url = f"{FIRMS_HOST}/api/area/csv/{quote(key, safe='')}/{source_id}/{bbox}/{days}/{start.isoformat()}"
    path = root / f"{source_id}_{start.isoformat()}_{days}.csv"
    partial = path.with_suffix(".csv.part")
    for attempt in range(settings.downloads.retry_limit + 1):
        _check_budget(client, key, settings)
        try:
            with client.stream("GET", url, timeout=settings.downloads.timeout_seconds) as response:
                response.raise_for_status()
                if "text/csv" not in response.headers.get("content-type", "").lower():
                    raise RuntimeError("FIRMS returned a non-CSV response")
                written = _saved_bytes(root)
                with partial.open("wb") as stream:
                    for chunk in response.iter_bytes(65536):
                        written += len(chunk)
                        if written > settings.storage.temporary_bytes_limit:
                            raise RuntimeError("temporary download limit reached")
                        stream.write(chunk)
            record = _downloaded_record(partial, source_id, start, end, settings)
            if _saved_bytes(root) > settings.storage.saved_bytes_limit:
                raise RuntimeError("saved download limit reached")
            os.replace(partial, path)
            progress[identity] = {
                "file": path.name, "sha256": record.sha256,
                "bbox": ",".join(str(value) for value in settings.downloads.bbox),
                "source": source_id, "start_date": start.isoformat(), "end_date": end.isoformat(),
                "downloaded_at": record.downloaded_at.isoformat(),
            }
            _write_progress(root, progress)
            return record
        except RuntimeError as error:
            partial.unlink(missing_ok=True)
            if attempt == settings.downloads.retry_limit:
                raise RuntimeError(str(error)) from None
        except Exception as error:
            partial.unlink(missing_ok=True)
            if attempt == settings.downloads.retry_limit:
                raise RuntimeError("FIRMS window download failed") from None
    raise RuntimeError("FIRMS window download failed")

def fetch_windows(settings) -> Iterator[SourceFileRecord]:
    if any(source not in FIRMS_SOURCES for source in settings.downloads.sources): raise ValueError("untrusted FIRMS source ID")
    if not settings.downloads.sources: return
    root = settings.storage.staging_path
    if root.is_symlink():
        raise RuntimeError("staging path is unsafe")
    root.mkdir(parents=True, exist_ok=True)
    progress = _read_progress(root)
    key = _firms_key()
    with httpx.Client(verify=True, follow_redirects=False) as client:
        for source_id in settings.downloads.sources:
            earliest, latest = _available_dates(client, key, source_id, settings)
            start, end = settings.downloads.start_date, settings.downloads.end_date
            if start < earliest or end - timedelta(days=1) > latest:
                raise RuntimeError("requested FIRMS dates are unavailable")
            while start < end:
                days = min(settings.downloads.window_days, (end - start).days)
                record = _fetch_window(client, key, source_id, start, days, settings, root, progress)
                yield record
                start += timedelta(days=days)

def _check_file(path: Path, source: SourceFileRecord) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source path is not a regular file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != source.sha256:
        raise ValueError("source file changed or hash does not match")


def _csv_reader(stream, required: set[str]) -> csv.DictReader:
    reader = csv.DictReader(stream)
    names = reader.fieldnames or []
    if len(names) != len(set(names)) or not required.issubset(names):
        raise ValueError("source CSV has missing or duplicate columns")
    return reader


def _number(value: str, *, optional: bool = False) -> float | None:
    if not value and optional:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid numeric source field") from error
    if not math.isfinite(result):
        raise ValueError("source values must be finite")
    return result


def _observation_time(row: Mapping[str, str], source: SourceFileRecord) -> datetime:
    text = row["acq_date"]
    try:
        day = date.fromisoformat(text)
        clock = row["acq_time"]
        if day.isoformat() != text or not clock.isascii() or not clock.isdigit() or len(clock) > 4:
            raise ValueError("invalid acquisition date or time")
        clock = clock.zfill(4)
        result = datetime.combine(day, time(int(clock[:2]), int(clock[2:])), timezone.utc)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid acquisition date or UTC time") from error
    if not source.start_date <= day < source.end_date:
        raise ValueError("acquisition date is outside the source window")
    return result


def _band_fields(names: Sequence[str], product: str) -> dict[str, str]:
    if product not in BAND_COLUMNS:
        raise ValueError("unsupported source product")
    known = BAND_COLUMNS[product]
    unknown = [name for name in names if name.startswith("bright") and name not in known]
    columns = {name: known[name] for name in names if name in known}
    if unknown or not columns or not (set(names) & PRIMARY_BAND_COLUMNS[product]) or len(set(columns.values())) != len(columns):
        raise ValueError("unknown or ambiguous brightness band")
    return columns


def _platform(row: Mapping[str, str], source: SourceFileRecord) -> str:
    name = PLATFORMS.get(source.product, {}).get(row["satellite"])
    if name is None or (row.get("instrument") and row["instrument"] != source.product):
        raise ValueError("unknown satellite or mismatched instrument")
    source_family = source.source_id.rsplit("_", 1)[0]
    expected = SOURCE_PLATFORMS[source_family]
    if expected is not None and name != expected:
        raise ValueError("satellite does not match source")
    return name


def _parse_observation(row: dict[str, str], row_id: int, source: SourceFileRecord,
                       columns: Mapping[str, str]) -> tuple[ObservationRecord, tuple[BandRecord, ...]]:
    if None in row or any(value is None for value in row.values()):
        raise ValueError("CSV row has the wrong number of fields")
    versions = {source.version}
    if source.processing_mode == "NRT":
        base_version = source.version
        for suffix in ("NRT", "URT", "RT"):
            if base_version.endswith(suffix):
                base_version = base_version[:-len(suffix)]
                break
        versions = {base_version + suffix for suffix in ("NRT", "RT", "URT")}
    if row["version"] not in versions:
        raise ValueError("source version changed")
    longitude = _number(row["longitude"])
    latitude = _number(row["latitude"])
    if longitude is None or latitude is None or not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("invalid observation location")
    scan = _number(row.get("scan", ""), optional=True)
    track = _number(row.get("track", ""), optional=True)
    frp = _number(row.get("frp", ""), optional=True)
    if any(value is not None and value < 0 for value in (scan, track, frp)):
        raise ValueError("source values cannot be negative")
    hotspot_type = row.get("type", "") or "unknown"
    if hotspot_type not in {"0", "1", "2", "3", "unknown"}:
        raise ValueError("unknown hotspot type")
    observation_id = f"{source.source_file_id}:{row_id}"
    daynight = row.get("daynight", "")
    if daynight not in {"", "D", "N"}:
        raise ValueError("invalid day or night flag")
    observation = ObservationRecord(
        observation_id=observation_id, source_file_id=source.source_file_id, source_row_id=row_id,
        pass_id=None, platform=_platform(row, source), instrument=source.product,
        observed_at=_observation_time(row, source), longitude=longitude, latitude=latitude,
        scan_km=scan, track_km=track, frp_mw=frp, confidence=row.get("confidence") or None,
        hotspot_type=hotspot_type, quality=(f"daynight:{daynight}",) if daynight else (), original_fields=row,
    )
    bands = tuple(_band(observation_id, name, row[column]) for column, name in columns.items())
    return observation, bands


def _band(observation_id: str, name: str, raw_value: str) -> BandRecord:
    value = _number(raw_value, optional=True)
    flags = ("possible_sensor_limit",) if name == "VIIRS_I4" and value == 367 else ()
    if name == "VIIRS_bright_t31_unverified":
        flags = ("unverified_band",)
    return BandRecord(observation_id=observation_id, band_name=name, value=value, unit="K", flags=flags)


def read_source(path: Path, source_definition: SourceFileRecord, *, batch_size: int) -> Iterator[SourceBatch]:
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch size must be positive")
    family, separator, mode = source_definition.source_id.rpartition("_")
    if not separator or family not in SOURCE_PLATFORMS or mode not in {"NRT", "SP"}:
        raise ValueError("unknown source ID")
    if source_definition.product != ("MODIS" if family == "MODIS" else "VIIRS"):
        raise ValueError("source ID does not match product")
    expected_modes = {"SP": {"standard", "SP"}, "NRT": {"NRT"}}
    if source_definition.processing_mode not in expected_modes[mode]:
        raise ValueError("source processing mode does not match ID")
    _check_file(path, source_definition)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = _csv_reader(stream, REQUIRED_COLUMNS)
        columns = _band_fields(reader.fieldnames or [], source_definition.product)
        observations: list[ObservationRecord] = []
        bands: list[BandRecord] = []
        for row_id, row in enumerate(reader, 1):
            observation, row_bands = _parse_observation(row, row_id, source_definition, columns)
            observations.append(observation)
            bands.extend(row_bands)
            if len(observations) == batch_size:
                yield SourceBatch(source_file=source_definition, observations=tuple(observations), bands=tuple(bands), opportunities=())
                observations, bands = [], []
        if observations:
            yield SourceBatch(source_file=source_definition, observations=tuple(observations), bands=tuple(bands), opportunities=())
    _check_file(path, source_definition)


def _fixture_geometry(value: str) -> AreaGeometry:
    """Check the small GeoJSON areas used by the test interchange file."""
    try:
        data = json.loads(value)
        kind = data["type"]
        coordinates = data["coordinates"]
        if kind not in {"Polygon", "MultiPolygon"}:
            raise ValueError("invalid area type")
        polygons = [coordinates] if kind == "Polygon" else coordinates
        count = 0
        for polygon in polygons:
            if not polygon:
                raise ValueError("empty area")
            for ring in polygon:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("invalid area ring")
                count += len(ring)
                for point in ring:
                    if len(point) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point):
                        raise ValueError("invalid area coordinate")
                    if not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                        raise ValueError("area coordinate out of range")
        if count == 0 or count > 10000:
            raise ValueError("invalid area size")
        return TypeAdapter(AreaGeometry).validate_python(data)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid area geometry") from error


def _fixture_opportunity(row: dict[str, str], source: SourceFileRecord) -> OpportunityRecord:
    if None in row or any(value is None for value in row.values()):
        raise ValueError("visit row has the wrong number of fields")
    try:
        observed_at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid visit time") from error
    if observed_at.tzinfo is None or observed_at.utcoffset() != timezone.utc.utcoffset(observed_at):
        raise ValueError("visit time must be UTC")
    if not source.start_date <= observed_at.date() < source.end_date:
        raise ValueError("visit time is outside source window")
    if not row["pass_id"] or row["platform"] not in {"Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"} or not row["quality"]:
        raise ValueError("invalid visit identity")
    if row["expected"] not in {"", "true", "false"}:
        raise ValueError("invalid visit expectation")
    expected = None if not row["expected"] else row["expected"] == "true"
    return OpportunityRecord(source_file_id=source.source_file_id, pass_id=row["pass_id"],
        platform=row["platform"], observed_at=observed_at.astimezone(timezone.utc),
        footprint=_fixture_geometry(row["footprint"]),
        usable_footprint=_fixture_geometry(row["usable_footprint"]) if row["usable_footprint"] else None,
        expected=expected, quality=row["quality"])


def read_opportunities(path: Path, source_definition: SourceFileRecord, *, batch_size: int) -> Iterator[SourceBatch]:
    if source_definition.product != "fixture-opportunities":
        raise ValueError("native visit readers are not implemented")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch size must be positive")
    _check_file(path, source_definition)
    required = {"pass_id", "platform", "observed_at", "footprint", "usable_footprint", "expected", "quality"}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = _csv_reader(stream, required)
        visits: list[OpportunityRecord] = []
        for row in reader:
            visits.append(_fixture_opportunity(row, source_definition))
            if len(visits) == batch_size:
                yield SourceBatch(source_file=source_definition, observations=(), bands=(), opportunities=tuple(visits))
                visits = []
        if visits:
            yield SourceBatch(source_file=source_definition, observations=(), bands=(), opportunities=tuple(visits))
    _check_file(path, source_definition)


def _selection_key(record: ObservationRecord) -> tuple:
    original = tuple(sorted((key, value) for key, value in record.original_fields.items()
                            if key not in {"version", "satellite"}))
    return (record.platform, record.instrument, record.observed_at, record.longitude, record.latitude,
            record.scan_km, record.track_km, record.frp_mw, record.confidence, record.hotspot_type, original)


def select_source_records(records: Sequence[ObservationRecord], policy: Mapping[str, JsonValue]) -> tuple[ObservationRecord, ...]:
    if set(policy) - {"types", "confidences", "preferred_sources"}:
        raise ValueError("unknown selection policy")
    for name in policy:
        value = policy[name]
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value) or len(set(value)) != len(value):
            raise ValueError("selection lists must contain unique names")
    types = policy.get("types")
    confidences = policy.get("confidences")
    priority = policy.get("preferred_sources", [])
    chosen: dict[tuple, tuple[int, ObservationRecord]] = {}
    for index, record in enumerate(records):
        if types is not None and record.hotspot_type not in types:
            continue
        if confidences is not None and (record.confidence or "unknown") not in confidences:
            continue
        key = _selection_key(record)
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = (index, record)
        elif previous[1].source_file_id != record.source_file_id:
            if previous[1].source_file_id not in priority or record.source_file_id not in priority:
                raise ValueError("source preference is required for duplicate rows")
            if priority.index(record.source_file_id) < priority.index(previous[1].source_file_id):
                chosen[key] = (index, record)
    return tuple(record for _, record in sorted(chosen.values(), key=lambda item: item[0]))
