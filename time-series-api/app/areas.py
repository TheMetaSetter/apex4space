"""Load and resolve the small, versioned FIRMS area catalog."""

import hashlib
import json
import unicodedata
from pathlib import Path

from shapely.geometry import Point, shape
from shapely import prepare


class AreaError(ValueError):
    def __init__(self, status, code, message, candidates=()):
        super().__init__(message)
        self.status, self.code, self.candidates = status, code, tuple(candidates)


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def load_world_areas(directory):
    directory = Path(directory)
    if (directory / 'area-catalog.json').exists():
        return _load_global(directory)
    names = ("world-areas.geojson", "area-aliases.json", "continent-membership.json")
    raw = {name: (directory / name).read_bytes() for name in names}
    manifest = json.loads((directory / "world-areas-manifest.json").read_bytes())
    digest = hashlib.sha256(b"apex4space.world-areas.catalog.v1\0" + manifest["source_sha256"].encode())
    for name, content in sorted(raw.items()):
        digest.update(name.encode() + b"\0" + len(content).to_bytes(8, "big") + content)
    if digest.hexdigest() != manifest.get("catalog_sha256"):
        raise ValueError("area catalog checksum mismatch")
    collection = json.loads(raw[names[0]]); areas = {}
    for feature in collection["features"]:
        area_id = feature["properties"]["area_id"]
        geometry = shape(feature["geometry"])
        if area_id in areas or geometry.geom_type not in {"Polygon", "MultiPolygon"} or not geometry.is_valid:
            raise ValueError("area catalog contains duplicate or invalid geometry")
        if geometry.bounds[0] < -180 or geometry.bounds[2] > 180 or geometry.bounds[1] < -90 or geometry.bounds[3] > 90:
            raise ValueError("area geometry is outside WGS84 bounds")
        prepare(geometry)  # Prepare once before concurrent API readers use this polygon.
        areas[area_id] = {"id": area_id, "name": feature["properties"]["name"], "geometry": geometry}
    aliases = json.loads(raw[names[1]])
    if any(not ids or any(area_id not in areas for area_id in ids) for ids in aliases.values()):
        raise ValueError("area aliases refer to an unknown area")
    members = json.loads(raw[names[2]])
    if any(area_id not in areas for ids in members.values() for area_id in ids):
        raise ValueError("continent membership refers to an unknown area")
    if not members or set(members) - {"south-america", "north-america"} or set(areas) != {"country:VNM", *[f"continent:{name}" for name in members], *[item for values in members.values() for item in values]}:
        raise ValueError("area catalog scope does not match declared members")
    return {"version": manifest["catalog_version"], "areas": areas, "aliases": aliases}


def resolve_area_name(catalog, value):
    if not isinstance(value, str) or not value.strip():
        raise AreaError(422, "INVALID_QUERY", "area_name must be a non-empty string")
    candidates = catalog["aliases"].get(normalize_name(value), ())
    if not candidates:
        raise AreaError(404, "AREA_NOT_FOUND", "area name was not found")
    if len(candidates) > 1:
        raise AreaError(409, "AREA_AMBIGUOUS", "area name has multiple matches", sorted(candidates))
    return catalog["areas"][candidates[0]]


def matching_cells(connection, area):
    """Stream cells whose centers the exact area polygon covers."""
    geometry = area["geometry"]; parts = geometry.geoms if geometry.geom_type == "MultiPolygon" else (geometry,)
    seen = set()
    for part in parts:
        min_x, min_y, max_x, max_y = part.bounds
        query = "SELECT grid_version,cell_id,center_longitude,center_latitude,geometry_json FROM hotspot_cell WHERE center_longitude BETWEEN ? AND ? AND center_latitude BETWEEN ? AND ? ORDER BY grid_version,cell_id"
        for row in connection.execute(query, (min_x, max_x, min_y, max_y)):
            key = row[0], row[1]
            if key not in seen:
                seen.add(key)
                if geometry.covers(Point(row[2], row[3])):
                    yield row


def _load_global(directory):
    raw=(directory/'area-catalog.json').read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=(directory/'catalog-sha256.txt').read_text().strip():
        raise ValueError('Global catalog checksum mismatch')
    data=json.loads(raw)
    for area in data['areas'].values():
        if not area['country_codes']:
            raise ValueError('Empty country membership')
        geometry=area['geometry']
        if geometry is not None:
            geometry=shape(geometry)
            if not geometry.is_valid or geometry.geom_type not in {'Polygon','MultiPolygon'}:
                raise ValueError('Invalid global display geometry')
        area['geometry']=geometry
    if any(area_id not in data['areas'] for ids in data['aliases'].values() for area_id in ids):
        raise ValueError('Unknown area alias')
    return {'version':'global-'+digest[:16],**data}
