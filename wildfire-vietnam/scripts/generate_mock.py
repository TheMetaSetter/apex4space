import hashlib
import json
import math
import random
from pathlib import Path

from pyproj import Transformer
from shapely import orient_polygons, segmentize, transform
from shapely.geometry import MultiPolygon, box, mapping, shape

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-11-14"
SEED = 20261114


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry] if geometry.area > 0 else []
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return [part for child in geometry.geoms for part in polygon_parts(child)]
    return []


def make_response(country, metadata):
    to_grid = Transformer.from_crs("EPSG:4326", metadata["grid_crs"], always_xy=True)
    to_geo = Transformer.from_crs(metadata["grid_crs"], "EPSG:4326", always_xy=True)
    west, south, east, north = transform(country, to_grid.transform, interleaved=False).bounds
    origin_x, origin_y = metadata["grid_origin_m"]
    size = metadata["grid_cell_size_m"]
    interior = []
    edge = []
    # A sub-millimetre inset avoids floating-point overhangs along shared edges.
    inset_country = country.buffer(-1e-9)

    for row in range(math.floor((south - origin_y) / size), math.ceil((north - origin_y) / size)):
        for col in range(math.floor((west - origin_x) / size), math.ceil((east - origin_x) / size)):
            x, y = origin_x + col * size, origin_y + row * size
            square = box(x, y, x + size, y + size)
            geographic = transform(segmentize(square, 1000), to_geo.transform, interleaved=False)
            if not country.intersects(geographic):
                continue
            grid_id = f"VN-{row}-{col}"
            if country.covers(geographic):
                interior.append((grid_id, geographic, False))
                continue
            clipped = country.intersection(geographic)
            if not country.covers(clipped):
                clipped = inset_country.intersection(geographic)
            parts = polygon_parts(clipped)
            if parts:
                geometry = parts[0] if len(parts) == 1 else MultiPolygon(parts)
                edge.append((grid_id, geometry, True))

    rng = random.Random(SEED)
    sample = rng.sample(interior, 64) + rng.sample(edge, 16)
    features = []
    for grid_id, geometry, clipped in sorted(sample, key=lambda cell: cell[0]):
        if not geometry.is_valid or not country.covers(geometry):
            raise ValueError(f"Invalid or out-of-country geometry in {grid_id}")
        features.append({
            "type": "Feature",
            "id": grid_id,
            "properties": {
                "grid_id": grid_id,
                "detection_count": rng.randint(1, 25),
                "clipped": clipped,
            },
            "geometry": mapping(orient_polygons(geometry)),
        })

    return {
        "country": {"code": "VN", "name": "Việt Nam"},
        "date": DATE,
        "is_mock": True,
        "general_statistics": {
            "affected_grid_count": len(features),
            "detection_count": sum(f["properties"]["detection_count"] for f in features),
        },
        "detail_grids_info": {"type": "FeatureCollection", "features": features},
    }


def main():
    metadata = json.loads((ROOT / "data/boundary-source.json").read_text(encoding="utf-8"))
    source = (ROOT / "public/data/vietnam-boundary.geojson").read_bytes()
    if hashlib.sha256(source).hexdigest() != metadata["sha256"]:
        raise ValueError("Boundary file checksum does not match source metadata")
    country = shape(json.loads(source)["features"][0]["geometry"])
    if not country.is_valid or country.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Invalid country boundary geometry")

    response = make_response(country, metadata)
    output = ROOT / f"public/mock/vn-{DATE}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(response["general_statistics"])


if __name__ == "__main__":
    main()
