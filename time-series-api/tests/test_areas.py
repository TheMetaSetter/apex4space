from pathlib import Path
import json
import shutil
import sqlite3
import sys

import pytest
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_world_areas import _valid_geometry, normalize_name
from app.areas import AreaError, load_world_areas, matching_cells, resolve_area_name


def test_area_names_use_unicode_case_and_whitespace_normalization():
    assert normalize_name("  VIỆT   NAM ") == "việt nam"


def test_catalog_builder_rejects_invalid_source_polygon():
    bow_tie = Polygon(((0, 0), (1, 1), (0, 1), (1, 0), (0, 0)))
    with pytest.raises(ValueError, match="invalid polygon"):
        _valid_geometry(bow_tie, "fixture")


def test_focused_catalog_aliases_and_exact_polygon_filtering():
    catalog = load_world_areas(Path(__file__).parents[1] / "config")
    assert set(catalog["areas"]) == {"country:VNM", "continent:south-america", *json.loads(
        (Path(__file__).parents[1] / "config/continent-membership.json").read_text())["south-america"]}
    assert resolve_area_name(catalog, " Việt   Nam ")["id"] == "country:VNM"
    assert resolve_area_name(catalog, "SOUTH AMERICA")["id"] == "continent:south-america"
    with pytest.raises(AreaError) as error:
        resolve_area_name(catalog, "Atlantis")
    assert error.value.status == 404
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE hotspot_cell(grid_version,cell_id,center_longitude,center_latitude,geometry_json)")
    db.executemany("INSERT INTO hotspot_cell VALUES(?,?,?,?,?)", [
        ("g", "vietnam", 105.8, 21.0, "{}"), ("g", "south-america", -46.6, -23.5, "{}")])
    assert [row[1] for row in matching_cells(db, resolve_area_name(catalog, "Vietnam"))] == ["vietnam"]
    assert [row[1] for row in matching_cells(db, resolve_area_name(catalog, "South America"))] == ["south-america"]


def test_catalog_checksum_rejects_changed_asset(tmp_path):
    source = Path(__file__).parents[1] / "config"
    for name in ("world-areas.geojson", "area-aliases.json", "continent-membership.json", "world-areas-manifest.json"):
        shutil.copy(source / name, tmp_path / name)
    with (tmp_path / "area-aliases.json").open("a") as output:
        output.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        load_world_areas(tmp_path)
