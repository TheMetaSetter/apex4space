"""Build the pinned, offline Natural Earth country and continent catalog."""

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

import shapefile
import shapely
from pyproj import CRS, __version__ as pyproj_version
from shapely import normalize
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely.validation import explain_validity

VERSION = "5.1.1"
SOURCE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
CONTINENTS = {"South America": "south-america"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _valid_geometry(geometry, label):
    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
        raise ValueError(f"invalid polygon for {label}: {explain_validity(geometry)}")
    coords = shapely.get_coordinates(geometry)
    if not len(coords) or any(not math.isfinite(float(value)) for point in coords for value in point):
        raise ValueError(f"empty or invalid coordinates for {label}")
    if coords[:, 0].min() < -180 or coords[:, 0].max() > 180 or coords[:, 1].min() < -90 or coords[:, 1].max() > 90:
        raise ValueError(f"WGS84 bounds exceeded for {label}")
    return normalize(geometry)


def prepare(source_zip, output_dir, focus_continent="South America"):
    continents = {focus_continent: focus_continent.lower().replace(" ", "-")}
    source_zip, output = Path(source_zip), Path(output_dir).expanduser().absolute()
    if shapefile.__version__ != "2.3.1":
        raise ValueError("catalog build requires pyshp==2.3.1")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("catalog output must be a new directory with an existing parent")
    with source_zip.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    with zipfile.ZipFile(source_zip) as archive:
        projection = CRS.from_wkt(archive.read(next(name for name in archive.namelist() if name.endswith(".prj"))).decode())
        if projection.to_epsg() != 4326:
            raise ValueError("Natural Earth source is not WGS84/EPSG:4326")
    reader = shapefile.Reader(str(source_zip)); fields = [item[0] for item in reader.fields[1:]]
    required = {"ADM0_A3", "ADMIN", "NAME", "ISO_A2", "ISO_A3", "CONTINENT"}
    if not required.issubset(fields):
        raise ValueError("Natural Earth archive is missing required fields")
    countries, members, aliases, geometries, seen = [], {key: [] for key in continents.values()}, {}, {}, set()
    outside_continents = []
    for index, (record, source_shape) in enumerate(zip(reader.iterRecords(), reader.iterShapes(), strict=True), 1):
        row = dict(zip(fields, record)); code = str(row["ADM0_A3"]).strip()
        if code != "VNM" and row["CONTINENT"] != focus_continent:
            continue
        if not code or code == "-99" or code in seen:
            raise ValueError(f"missing or duplicate ADM0_A3 at feature {index}")
        area_id = f"country:{code}"; name = str(row["ADMIN"]).strip()
        geometry = _valid_geometry(shape(source_shape.__geo_interface__), area_id)
        seen.add(code); geometries[area_id] = geometry
        countries.append({"type": "Feature", "id": area_id, "properties": {"area_id": area_id, "name": name, "area_type": "country"}, "geometry": mapping(geometry)})
        continent = continents.get(row["CONTINENT"])
        if continent: members[continent].append(area_id)
        elif code != "VNM": outside_continents.append(area_id)
        for value in (name, row["NAME"], row["ISO_A2"], row["ISO_A3"]):
            if value and str(value) not in {"-99", "None"}:
                aliases.setdefault(normalize_name(str(value)), set()).add(area_id)
    aliases.update({normalize_name(key): set(value.split(",")) for key, value in {
        "VN": "country:VNM", "VNM": "country:VNM",
        "Vietnam": "country:VNM", "Viet Nam": "country:VNM", "Việt Nam": "country:VNM"}.items()})
    for name, slug in continents.items():
        area_id = f"continent:{slug}"
        if not members[slug]: raise ValueError(f"continent has no source members: {name}")
        geometry = _valid_geometry(unary_union([geometries[item] for item in members[slug]]), area_id)
        geometries[area_id] = geometry
        countries.append({"type": "Feature", "id": area_id, "properties": {"area_id": area_id, "name": name, "area_type": "continent"}, "geometry": mapping(geometry)})
        aliases.setdefault(normalize_name(name), set()).add(area_id)
    for name in continents:
        aliases.setdefault("america", set()).add(f"continent:{continents[name]}")
    assets = {
        "world-areas.geojson": {"type": "FeatureCollection", "features": sorted(countries, key=lambda item: item["id"])},
        "area-aliases.json": {key: sorted(value) for key, value in sorted(aliases.items())},
        "continent-membership.json": {key: sorted(value) for key, value in sorted(members.items())},
    }
    encoded = {name: canonical(value) + b"\n" for name, value in assets.items()}
    digest = hashlib.sha256(b"apex4space.world-areas.catalog.v1\0" + source_hash.encode())
    for name, data in sorted(encoded.items()):
        digest.update(name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    catalog_hash = digest.hexdigest(); catalog_version = f"ne-admin0-10m-{VERSION}-{catalog_hash[:16]}"
    manifest = {"catalog_version": catalog_version, "catalog_sha256": catalog_hash,
        "source_url": SOURCE_URL, "source_sha256": source_hash, "source_version": VERSION,
        "source_attribution": "Made with Natural Earth.", "boundary_policy": "de-facto Admin-0 Countries",
        "source_fields": sorted(required), "catalog_scope": ["country:VNM", *[f"continent:{slug}" for slug in continents.values()]],
        "feature_count": len(countries),
        "continent_members": members, "non_continental_area_ids": sorted(outside_continents),
        "build_tools": {"python": sys.version, "pyshp": shapefile.__version__,
                        "shapely": shapely.__version__, "pyproj": pyproj_version}}
    stage = Path(tempfile.mkdtemp(prefix=".areas-", dir=output.parent))
    try:
        for name, data in encoded.items(): (stage / name).write_bytes(data)
        (stage / "world-areas-manifest.json").write_bytes(canonical(manifest) + b"\n")
        os.rename(stage, output)
    except Exception:
        shutil.rmtree(stage); raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True); parser.add_argument("--output-dir", required=True)
    parser.add_argument("--continent", choices=["South America", "North America"], default="South America")
    args = parser.parse_args()
    try: print(canonical(prepare(args.source_zip, args.output_dir, args.continent)).decode())
    except (OSError, ValueError, zipfile.BadZipFile) as error: parser.exit(2, f"prepare_world_areas: {error}\n")


if __name__ == "__main__":
    main()
