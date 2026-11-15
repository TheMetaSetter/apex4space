import csv
import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest
from pyproj import Transformer
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preprocess_firms as importer
from scripts.check_results import check_firms_release


def _fixture(root, rename=False):
    nested = root / "nested"; nested.mkdir(parents=True)
    first = nested / ("renamed.csv" if rename else "火點.CSV")
    first.write_bytes(("\ufefflatitude,longitude,acq_date,acq_time,note,satellite,instrument,version\r\n"
        '0,0,2024-02-28,0000,"two\nlines",Terra,MODIS,A\r\n0,0,2024-03-01,2359,x,Terra,MODIS,B\r\n'
        "90,179,2024-03-01,1200,pole,Terra,MODIS,B\r\n86.1,20,2024-03-01,1200,north,Terra,MODIS,B\r\n").encode("utf-8"))
    second = root / "overlap.csv"
    second.write_text("latitude,longitude,acq_date\n0,0,2024-03-01\n-90,-180,2024-03-01", encoding="utf-8")
    sample = root / "different-name.CsV"
    sample.write_text("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n0,0,300,1,1,2024-03-01,3,NPP,VIIRS,n, C,290,2.3,D")
    return first, second


def test_grid_boundaries_and_antimeridian():
    assert importer.assign_grid_cell(180, 0) == importer.assign_grid_cell(-180, 0)
    assert importer.assign_grid_cell(0, 86)[0] == "firms-ease-global-10km-v2"
    assert importer.assign_grid_cell(0, 86.00001)[0] == "firms-ease-north-10km-v2"
    assert importer.assign_grid_cell(0, -86.00001)[0] == "firms-ease-south-10km-v2"
    assert importer._grid_index(10_000) == importer._grid_index(9_999.9999999) == 1
    assert importer._grid_index(-10_000) == -1
    grid, _, column, row = importer.assign_grid_cell(-180, 0)
    seam = shape(importer.make_cell_geometry(grid, column, row))
    assert seam.is_valid and seam.bounds[0] >= -180 and seam.bounds[2] <= 180


def test_multifile_build_is_deduplicated_dense_and_rename_stable(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"; one.mkdir(); two.mkdir()
    first, second = _fixture(one); renamed_first, renamed_second = _fixture(two, rename=True)
    a = tmp_path / "release-a"; b = tmp_path / "release-b"
    result = importer.build_database([one, second], a)
    again = importer.build_database([renamed_second, two, renamed_first.parent], b)
    assert result["release_id"] == again["release_id"]
    manifest = json.loads((a / "manifest.json").read_text())
    assert manifest["rows_read"] == manifest["rows_assigned"] == 7
    assert manifest["distinct_memberships"] == 5
    assert manifest["duplicate_memberships"] == 2
    expected = set()
    for path in (item for item in one.rglob("*") if item.is_file() and item.suffix.casefold() == ".csv"):
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for item in csv.DictReader(stream):
                lon, lat = float(item["longitude"]), float(item["latitude"])
                grid, epsg = (("firms-ease-north-10km-v2", 6931) if lat > 86 else
                              ("firms-ease-south-10km-v2", 6932) if lat < -86 else
                              ("firms-ease-global-10km-v2", 6933))
                x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(-180 if lon == 180 else lon, lat)
                indexes = []
                for value in (x, y):
                    edge = round(value / 10_000) * 10_000
                    indexes.append(round(value / 10_000) if abs(value - edge) <= 1e-6 else math.floor(value / 10_000))
                expected.add((item["acq_date"], grid, f"{indexes[0]}:{indexes[1]}"))
    labeled = next(source for source in manifest["sources"] if source["path"].startswith("nested/"))
    assert labeled["identity_labels"] == {
        "instrument": ["MODIS"], "satellite": ["Terra"], "version": ["A", "B"]}
    with sqlite3.connect(a / "database.sqlite3") as db:
        assert set(db.execute("select date,grid_version,cell_id from hotspot_cell_day")) == expected
        assert db.execute("select count(*) from hotspot_cell_day").fetchone()[0] == 5
        assert db.execute("select date,active_cell_count,input_state from daily_hotspot_summary order by date").fetchall() == [
            ("2024-02-28", 1, "records_present"), ("2024-02-29", 0, "no_records"),
            ("2024-03-01", 4, "records_present")]
        assert db.execute("pragma foreign_key_check").fetchall() == []
        assert db.execute("select count(*) from hotspot_cell").fetchone()[0] == 4
        assert all(shape(json.loads(row[0])).is_valid for row in db.execute("select geometry_json from hotspot_cell"))
        assert [row[0] for row in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")] == [
            "daily_hotspot_summary", "hotspot_cell", "hotspot_cell_day"]
    assert check_firms_release(a)["status"] == "passed"
    assert check_firms_release(b)["logical_sha256"] == check_firms_release(a)["logical_sha256"]


def test_invalid_row_aborts_without_publishing(tmp_path):
    source = tmp_path / "wrong-name.csv"
    source.write_text("latitude,longitude,acq_date\nNaN,1,2024-01-01\n", encoding="utf-8")
    output = tmp_path / "not-published"
    with pytest.raises(ValueError, match="non-finite coordinates"):
        importer.build_database([source], output)
    assert not output.exists()


def test_existing_output_is_refused(tmp_path):
    source = tmp_path / "x.csv"; source.write_text("latitude,longitude,acq_date\n0,0,2024-01-01\n")
    output = tmp_path / "existing"; output.mkdir()
    with pytest.raises(ValueError, match="output must be new"):
        importer.build_database([source], output)


def test_source_mutation_and_work_limit_fail_cleanly(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("latitude,longitude,acq_date\n0,0,2024-01-01\n")
    identity, = importer.discover_inputs([source])
    source.write_text("latitude,longitude,acq_date\n1,1,2024-01-01\n")
    with pytest.raises(ValueError, match="changed after discovery"):
        list(importer.read_rows(identity))
    source.write_text("latitude,longitude,acq_date\n" + "0,0,2024-01-01\n" * 4000)
    output = tmp_path / "limited"
    with pytest.raises(OSError, match="max-work-bytes"):
        importer.build_database([source], output, max_work_bytes=1)
    assert not output.exists() and not list(tmp_path.glob(".firms-work-*"))
