"""Processed cell records and small map response contracts."""

from collections.abc import Mapping, Sequence
from datetime import date
from functools import lru_cache
from pathlib import Path
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from app.models import AreaGeometry, BBox, ContractModel, StorageSettings, validate_bbox


class GridSettings(ContractModel):
    grid_version: StrictStr
    width_km: float
    projection: StrictStr = "EPSG:8857"
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0
    edge_rule: Literal["floor_half_open"] = "floor_half_open"

    @model_validator(mode="after")
    def validate_grid(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.grid_version):
            raise ValueError("invalid grid version")
        if not math.isfinite(self.width_km) or self.width_km <= 0:
            raise ValueError("grid width must be positive")
        if not math.isfinite(self.origin_x_m) or not math.isfinite(self.origin_y_m):
            raise ValueError("grid origin must be finite")
        return self


class CellRecord(ContractModel):
    grid_version: StrictStr
    cell_id: StrictStr
    center_longitude: float
    center_latitude: float
    geometry: AreaGeometry

    @model_validator(mode="after")
    def validate_geometry(self):
        _check_area_geometry(self.geometry)
        if not (-180 <= self.center_longitude <= 180 and -90 <= self.center_latitude <= 90):
            raise ValueError("cell center is outside longitude/latitude bounds")
        return self


class DailyHotspotSummary(ContractModel):
    release_id: StrictStr
    area_id: StrictStr
    date: date
    active_cell_count: StrictInt | None
    hotspot_cell_ids: tuple[StrictStr, ...] | None
    status: Literal["coverage_unknown", "partial", "missing", "available", "observed_zero"]

    @model_validator(mode="after")
    def validate_cell_ids(self):
        if (self.active_cell_count is None) != (self.hotspot_cell_ids is None):
            raise ValueError("count and cell IDs must both be present or absent")
        if self.hotspot_cell_ids is not None:
            if tuple(sorted(set(self.hotspot_cell_ids))) != self.hotspot_cell_ids:
                raise ValueError("cell IDs must be sorted and unique")
            if self.active_cell_count != len(self.hotspot_cell_ids):
                raise ValueError("count must equal the number of cell IDs")
        if self.active_cell_count is not None and self.active_cell_count < 0:
            raise ValueError("count cannot be negative")
        if self.status == "missing" and self.active_cell_count is not None:
            raise ValueError("missing input must have a null count and ID list")
        if self.status == "observed_zero" and self.active_cell_count != 0:
            raise ValueError("observed-zero status requires a zero count")
        if self.status == "available" and self.active_cell_count == 0:
            raise ValueError("zero-count days need an explicit zero or unknown-coverage status")
        return self


class CellMapQuery(ContractModel):
    release_id: StrictStr
    date: date
    bbox: BBox | None = None
    area_id: StrictStr | None = None

    @model_validator(mode="before")
    @classmethod
    def check_selector(cls, value):
        if isinstance(value, dict):
            if (value.get("bbox") is None) == (value.get("area_id") is None):
                raise ValueError("provide exactly one of bbox or area_id")
            if value.get("bbox") is not None:
                validate_bbox(tuple(value["bbox"]))
            day = value.get("date")
            if not (type(day) is date or isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)):
                raise ValueError("date must use YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def validate_fields(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.release_id):
            raise ValueError("invalid release ID")
        if self.bbox is not None:
            validate_bbox(self.bbox)
        if self.area_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.area_id):
            raise ValueError("invalid area ID")
        return self


class CellMapFeature(ContractModel):
    type: Literal["Feature"]
    id: StrictStr
    geometry: AreaGeometry
    properties: Mapping[str, StrictStr]


class CellMapResponse(ContractModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: tuple[CellMapFeature, ...]
    release_id: str
    grid_version: str
    date: date
    requested_selector: Mapping[str, object]
    active_cell_count: int | None
    status: str
    warnings: tuple[StrictStr, ...] = ()


class CellReleaseManifest(ContractModel):
    schema_version: StrictInt = 1
    release_id: StrictStr
    grid_version: StrictStr
    start_date: date
    end_date: date
    grid: GridSettings
    areas: Mapping[str, object]
    platforms: tuple[StrictStr, ...] = ()
    filter_rules: Mapping[str, object] = Field(default_factory=dict)
    sources: tuple[Mapping[str, object], ...]
    code_version: StrictStr
    catalog_sha256: StrictStr
    processed_sha256: StrictStr | None = None
    validation_sha256: StrictStr | None = None

    @model_validator(mode="after")
    def validate_release(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.release_id):
            raise ValueError("invalid release ID")
        if not self.start_date < self.end_date:
            raise ValueError("release dates must be a half-open range")
        if self.grid.grid_version != self.grid_version:
            raise ValueError("manifest grid version does not match its grid settings")
        if not re.fullmatch(r"[0-9a-f]{64}", self.catalog_sha256):
            raise ValueError("invalid area catalog hash")
        return self


class CellPreparationSettings(ContractModel):
    storage: StorageSettings
    area_catalog_path: Path
    grid: GridSettings
    start_date: date
    end_date: date
    area_id: StrictStr
    platforms: tuple[StrictStr, ...]
    drive_source_ids: Mapping[StrictStr, StrictStr]
    local_source_files: Mapping[StrictStr, StrictStr] = Field(default_factory=dict)
    maximum_file_bytes: StrictInt
    maximum_run_bytes: StrictInt
    maximum_memberships: StrictInt

    @model_validator(mode="after")
    def validate_settings(self):
        if self.start_date >= self.end_date or not self.area_id:
            raise ValueError("invalid processing area or date range")
        if not self.platforms or len(set(self.platforms)) != len(self.platforms):
            raise ValueError("platforms must be nonempty and unique")
        if any(Path(name).is_absolute() or ".." in Path(name).parts or not name.lower().endswith(".csv")
               for name in self.local_source_files):
            raise ValueError("local source file names must be relative CSV paths")
        if any(source_id not in {"MODIS_NRT", "MODIS_SP", "VIIRS_SNPP_NRT", "VIIRS_SNPP_SP",
                                 "VIIRS_NOAA20_NRT", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT", "VIIRS_NOAA21_SP"}
               for source_id in self.local_source_files.values()):
            raise ValueError("local source mapping contains an unknown FIRMS source")
        if not (0 < self.maximum_file_bytes <= 80 * 1024**2
                and self.maximum_file_bytes <= self.maximum_run_bytes <= 256 * 1024**2
                and 0 < self.maximum_memberships <= 100_000):
            raise ValueError("invalid Drive or processed-data limits")
        return self


def load_cell_settings(path: Path) -> CellPreparationSettings:
    """Load processed-run settings and resolve paths under the project."""
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError("processed settings file is too large")
    value = json.loads(raw)
    project = Path(__file__).resolve().parents[1]
    storage = value["storage"]
    for name in ("database_path", "staging_path", "releases_path"):
        storage[name] = str((project / storage[name]).resolve())
    value["area_catalog_path"] = str((project / value["area_catalog_path"]).resolve())
    return CellPreparationSettings.model_validate(value)


class AreaRecord(ContractModel):
    area_id: StrictStr
    name: StrictStr
    version: StrictStr
    geometry: AreaGeometry

    @model_validator(mode="after")
    def validate_area(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.area_id):
            raise ValueError("invalid area ID")
        _check_area_geometry(self.geometry)
        return self


def _check_area_geometry(geometry: AreaGeometry) -> None:
    from shapely.geometry import shape

    try:
        area = shape(geometry)
    except Exception as error:
        raise ValueError("invalid area geometry") from error
    if area.geom_type not in {"Polygon", "MultiPolygon"} or not area.is_valid or area.area <= 0:
        raise ValueError("invalid area geometry")
    west, south, east, north = area.bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("area geometry is outside longitude/latitude bounds")


def load_area_catalog(path: Path) -> tuple[AreaRecord, ...]:
    """Read the small, reviewed GeoJSON catalog."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise ValueError("invalid area catalog")
    areas = []
    for feature in value["features"]:
        properties = feature.get("properties", {})
        areas.append(AreaRecord(
            area_id=properties["area_id"], name=properties["name"],
            version=properties["version"], geometry=feature["geometry"],
        ))
    if not areas or len({item.area_id for item in areas}) != len(areas):
        raise ValueError("area catalog must have unique areas")
    return tuple(areas)


def assign_cell(longitude: float, latitude: float, grid: GridSettings) -> CellRecord:
    """Assign one point to its equal-area grid cell and build that cell shape."""
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("coordinate is outside longitude/latitude bounds")
    try:
        from pyproj import Transformer
    except ImportError as error:
        raise RuntimeError("install the checked pyproj dependency before assigning cells") from error
    forward, reverse = _transformers(grid.projection)
    x, y = forward.transform(longitude, latitude)
    size = grid.width_km * 1000
    column = _grid_index(x, grid.origin_x_m, size)
    row = _grid_index(y, grid.origin_y_m, size)
    left = grid.origin_x_m + column * size
    bottom = grid.origin_y_m + row * size
    corners = [reverse.transform(px, py) for px, py in (
        (left, bottom), (left + size, bottom), (left + size, bottom + size),
        (left, bottom + size), (left, bottom),
    )]
    center_longitude, center_latitude = reverse.transform(left + size / 2, bottom + size / 2)
    geometry = _geometry_at_seam(corners, center_longitude)
    return CellRecord(
        grid_version=grid.grid_version, cell_id=f"{column}:{row}",
        center_longitude=center_longitude, center_latitude=center_latitude,
        geometry=geometry,
    )


def cell_from_id(cell_id: str, grid: GridSettings) -> CellRecord:
    """Rebuild a cell shape from its frozen grid settings."""
    if not re.fullmatch(r"-?\d+:-?\d+", cell_id):
        raise ValueError("invalid cell ID")
    column_text, row_text = cell_id.split(":")
    size = grid.width_km * 1000
    try:
        from pyproj import Transformer
    except ImportError as error:
        raise RuntimeError("install the checked pyproj dependency before assigning cells") from error
    _, reverse = _transformers(grid.projection)
    left = grid.origin_x_m + int(column_text) * size
    bottom = grid.origin_y_m + int(row_text) * size
    coordinates = [reverse.transform(x, y) for x, y in (
        (left, bottom), (left + size, bottom), (left + size, bottom + size),
        (left, bottom + size), (left, bottom),
    )]
    center = reverse.transform(left + size / 2, bottom + size / 2)
    geometry = _geometry_at_seam(coordinates, center[0])
    return CellRecord(grid_version=grid.grid_version, cell_id=cell_id,
                      center_longitude=center[0], center_latitude=center[1],
                      geometry=geometry)


@lru_cache(maxsize=4)
def _transformers(projection: str):
    from pyproj import Transformer
    return (Transformer.from_crs("EPSG:4326", projection, always_xy=True),
            Transformer.from_crs(projection, "EPSG:4326", always_xy=True))


def _grid_index(value: float, origin: float, size: float) -> int:
    """Keep projection round-off from moving an exact edge to its lower cell."""
    position = (value - origin) / size
    nearest = round(position)
    if math.isclose(position, nearest, rel_tol=0.0, abs_tol=1e-8):
        return nearest
    return math.floor(position)


def _geometry_at_seam(corners, center_longitude: float) -> AreaGeometry:
    """Split a projected cell at the date line before returning GeoJSON."""
    from shapely.affinity import translate
    from shapely.geometry import LineString, Polygon, box, mapping, shape
    from shapely.ops import split

    unwrapped = []
    for longitude, latitude in corners:
        while longitude - center_longitude > 180:
            longitude -= 360
        while longitude - center_longitude < -180:
            longitude += 360
        unwrapped.append((longitude, latitude))
    polygon = Polygon(unwrapped)
    pieces = [polygon]
    for boundary in (-180.0, 180.0):
        line = LineString(((boundary, -90), (boundary, 90)))
        pieces = [part for item in pieces for part in split(item, line).geoms]
    normalized = []
    for piece in pieces:
        if piece.is_empty:
            continue
        center_x = piece.representative_point().x
        if center_x > 180:
            piece = translate(piece, xoff=-360)
        elif center_x < -180:
            piece = translate(piece, xoff=360)
        clipped = piece.intersection(box(-180, -90, 180, 90))
        if not clipped.is_empty and clipped.geom_type == "Polygon":
            normalized.append(mapping(clipped))
    if not normalized:
        raise ValueError("projected grid cell has no valid geographic shape")
    if len(normalized) == 1:
        return normalized[0]
    return {"type": "MultiPolygon", "coordinates": tuple(item["coordinates"] for item in normalized)}


def summarize_hotspots(day_cells: Mapping[date, frozenset[str]], *, release_id: str,
                       area_id: str, start_date: date, end_date: date,
                       day_states: Mapping[date, str]) -> tuple[DailyHotspotSummary, ...]:
    """Create one count row for each UTC day in the half-open date range."""
    from datetime import timedelta

    rows = []
    current = start_date
    while current < end_date:
        state = day_states.get(current, "missing")
        identifiers = day_cells.get(current)
        if state == "missing":
            ids, count = None, None
        else:
            ids = tuple(sorted(identifiers or ()))
            count = len(ids)
            if state == "available" and count == 0:
                state = "observed_zero"
        rows.append(DailyHotspotSummary(release_id=release_id, area_id=area_id,
                    date=current, active_cell_count=count, hotspot_cell_ids=ids, status=state))
        current += timedelta(days=1)
    return tuple(rows)


def make_cell_map(query: CellMapQuery, summary: DailyHotspotSummary,
                  cells: Sequence[CellRecord], *, grid_version: str,
                  selection: AreaGeometry) -> CellMapResponse:
    """Build a small GeoJSON collection from stored cell IDs and shapes."""
    from shapely.geometry import box, shape, mapping

    if (summary.release_id != query.release_id or summary.date != query.date
            or query.area_id is not None and summary.area_id != query.area_id):
        raise ValueError("summary does not match map query")
    selector = ({"bbox": query.bbox} if query.bbox is not None
                else {"area_id": query.area_id})
    warnings = _cell_map_warnings(summary.status)
    if summary.hotspot_cell_ids is None:
        return CellMapResponse(features=(), release_id=query.release_id,
            grid_version=grid_version, date=query.date,
            requested_selector=selector, active_cell_count=None,
            status=summary.status, warnings=warnings)
    by_id = {cell.cell_id: cell for cell in cells}
    area_shape = shape(selection)
    bounds_shape = box(*query.bbox) if query.bbox else area_shape
    features = []
    for cell_id in summary.hotspot_cell_ids:
        cell = by_id.get(cell_id)
        if cell is None or cell.grid_version != grid_version:
            raise ValueError("summary cell shape is missing")
        center = shape({"type": "Point", "coordinates": (cell.center_longitude, cell.center_latitude)})
        if not area_shape.covers(center) or not bounds_shape.covers(center):
            continue
        clipped = shape(cell.geometry).intersection(area_shape).intersection(bounds_shape)
        if clipped.is_empty:
            continue
        geometry = mapping(clipped)
        features.append(CellMapFeature(type="Feature", id=cell.cell_id,
            geometry=geometry, properties={"cell_id": cell.cell_id}))
        if len(features) > 10000:
            raise ValueError("map contains more than 10,000 cells")
    return CellMapResponse(features=tuple(features), release_id=query.release_id,
        grid_version=grid_version, date=query.date,
        requested_selector=selector, active_cell_count=len(features),
        status=summary.status, warnings=warnings)


def _cell_map_warnings(status: str) -> tuple[str, ...]:
    if status == "coverage_unknown":
        return ("Observation coverage is unknown for this date.",)
    if status == "partial":
        return ("Only partial source input is available for this date.",)
    if status == "missing":
        return ("No source input is available for this date.",)
    return ()
