"""Small published releases for API tests."""

import hashlib
import json
import csv
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.models import (
    BandRecord, ObservationRecord, ReleaseRecord, ReleaseSummary, SourceBatch,
    SourceFileRecord, ValidationReport, load_settings,
)


def _release_bundle():
    source = SourceFileRecord(
        source_file_id="fixture-file", source_id="MODIS_SP", product="MODIS",
        version="6.03", processing_mode="standard", start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 2), downloaded_at=datetime(2024, 3, 3, tzinfo=timezone.utc),
        sha256="0" * 64, request_parameters={},
    )
    rows = tuple(ObservationRecord(
        observation_id=f"fixture-file:{row}", source_file_id="fixture-file", source_row_id=row,
        pass_id=None, platform="Aqua", instrument="MODIS",
        observed_at=datetime(2024, 3, 1, 0, row, tzinfo=timezone.utc),
        longitude=(106.21, 106.22, -106.23)[row - 1], latitude=10.5, scan_km=1, track_km=1,
        frp_mw=0, confidence=("High, fire\nwatch", "  =1+1", "90")[row - 1],
        hotspot_type="unknown", quality=(),
        original_fields={"version": "6.03", "satellite": "A"},
    ) for row in (1, 2, 3))
    batch = SourceBatch(source_file=source, observations=rows,
        bands=tuple(BandRecord(observation_id=row.observation_id, band_name="MODIS_31",
                               value=290, unit="K", flags=()) for row in rows), opportunities=())
    summary = ReleaseSummary(release_id="api-fixture-v1", study_areas=((-180, -90, 180, 90),),
        start_date=date(2024, 1, 1), end_date=date(2025, 1, 1),
        latest_source_dates={"Aqua": date(2024, 3, 1)},
        available_metrics=("observed_hotspot_count",), allowed_platforms=("Aqua",))
    frozen = {"schema_version": 1, "tested_scope": {}}
    report = ValidationReport(release_id=summary.release_id,
        checks={"provenance": {"source_hashes": {source.source_file_id: source.sha256},
                               "code_version": "fixture", "method_id": None, "settings": frozen}},
        supported_metrics=summary.available_metrics, tested_scope={}, failures=(),
        random_seed=None, repeat_count=None, memory_bytes=0, elapsed_seconds=0)
    data = TypeAdapter(ValidationReport).dump_python(report, mode="json")
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    release = ReleaseRecord(summary=summary, method_id=None, reference_count_definition=None,
        code_version="fixture", settings=frozen, source_files=(source,),
        source_selection={"rows": {source.source_file_id: [1, 2, 3]}}, baseline_rules={},
        report_sha256=hashlib.sha256(raw).hexdigest(), report_urls=())
    return release, report, batch


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    data_path = Path(__file__).parents[1] / "config/settings.json"
    data = json.loads(data_path.read_text())
    data["storage"].update({"database_path": str(tmp_path / "api.sqlite3"),
        "staging_path": str(tmp_path / "staging"), "releases_path": str(tmp_path / "releases"),
        "cell_database_path": str(tmp_path / "processed.sqlite3"),
        "cell_releases_path": str(tmp_path / "processed-releases")})
    data["api"].update({"selected_release_id": "api-fixture-v1",
        "allowed_origins": ["http://localhost:3000"],
        "allowed_hosts": ["testserver", "localhost", "127.0.0.1"]})
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(data))
    monkeypatch.setenv("CURSOR_SECRET", "a" * 32)
    settings = load_settings(settings_path)
    release, report, batch = _release_bundle()
    from app import storage

    storage.initialize_database(settings.storage.database_path)
    storage.publish_release(settings.storage.database_path, iter((batch,)), iter(()), release, report,
                            storage=settings.storage)
    from app.cells import CellRecord, CellReleaseManifest, DailyHotspotSummary, GridSettings

    grid = GridSettings(grid_version="test-grid-v1", width_km=10.0)
    cell = CellRecord(grid_version=grid.grid_version, cell_id="0:0",
        center_longitude=106.5, center_latitude=10.5,
        geometry={"type": "Polygon", "coordinates": (((106, 10), (107, 10),
            (107, 11), (106, 11), (106, 10)),)})
    cell_release = CellReleaseManifest(release_id="cell-fixture-v1", grid_version=grid.grid_version,
        start_date=date(2024, 3, 1), end_date=date(2024, 3, 2), grid=grid,
        areas={"test-area": {"name": "Test area", "version": "1",
                              "geometry": {"type": "Polygon", "coordinates": (((106, 10),
                                  (107, 10), (107, 11), (106, 11), (106, 10)),)}}},
        sources=(), code_version="fixture", catalog_sha256="0" * 64)
    cell_summary = DailyHotspotSummary(release_id="cell-fixture-v1", area_id="test-area",
        date=date(2024, 3, 1), active_cell_count=1, hotspot_cell_ids=("0:0",), status="available")
    # The API test only needs this one day; the fixture remains small.
    storage.initialize_cell_database(settings.storage.cell_database_path)
    storage.publish_cell_release(settings.storage.cell_database_path, iter((cell,)),
        iter((cell_summary,)), cell_release, settings.storage.model_copy(update={
            "database_path": settings.storage.cell_database_path,
            "releases_path": settings.storage.cell_releases_path,
        }))
    from app.main import create_app

    with TestClient(create_app(settings_path)) as client:
        yield client


def _forbid_source_reader(*args, **kwargs):
    raise AssertionError("map request tried to read source data")


def _assert_cell_map_selectors(client, storage, patch, cells):
    read_cells = storage.read_hotspot_cells
    area_map = client.post("/v1/hotspots/cells/query", json={
        "release_id": "cell-fixture-v1", "date": "2024-03-01", "area_id": "test-area",
    })
    assert area_map.status_code == 200 and area_map.json()["active_cell_count"] == 1
    assert area_map.json()["features"][0]["id"] == "0:0"
    bbox_map = client.post("/v1/hotspots/cells/query", json={
        "release_id": "cell-fixture-v1", "date": "2024-03-01", "bbox": [106, 10, 107, 11],
    })
    assert bbox_map.status_code == 200 and bbox_map.json()["active_cell_count"] == 1
    oversized_ids = tuple(sorted(("0:0", *(f"{i:05d}:0" for i in range(10000)))))
    oversized = cells.DailyHotspotSummary(release_id="cell-fixture-v1", area_id="test-area",
        date=date(2024, 3, 1), active_cell_count=10001,
        hotspot_cell_ids=oversized_ids, status="available")
    patch.setattr(storage, "read_hotspot_summary", lambda *args, **kwargs: oversized)
    too_many = client.post("/v1/hotspots/cells/query", json={
        "release_id": "cell-fixture-v1", "date": "2024-03-01", "area_id": "test-area",
    })
    assert too_many.status_code == 413 and too_many.json()["code"] == "CELL_LIMIT"
    patch.setattr(storage, "read_hotspot_cell_ids_in_bbox", lambda *args, **kwargs: ("0:0",))
    patch.setattr(storage, "read_hotspot_cells", read_cells)
    selected = client.post("/v1/hotspots/cells/query", json={
        "release_id": "cell-fixture-v1", "date": "2024-03-01", "bbox": [106, 10, 107, 11],
    })
    assert selected.status_code == 200 and selected.json()["active_cell_count"] == 1
    assert selected.json()["features"][0]["id"] == "0:0"
    outside = client.post("/v1/hotspots/cells/query", json={
        "release_id": "cell-fixture-v1", "date": "2024-03-01", "bbox": [0, 0, 1, 1],
    })
    assert outside.status_code == 422 and outside.json()["code"] == "AREA_NOT_PREPARED"


def _assert_processed_paths_reject_raw_reads(client):
    request = {"release_id": "cell-fixture-v1", "bbox": [106, 10, 107, 11],
        "start_date": "2024-03-01", "end_date": "2024-03-02",
        "metric": "observed_hotspot_count", "aggregation": "day", "platforms": ["Aqua"]}
    for path, body in (
        ("/v1/hotspots/query", {key: request[key] for key in (
            "release_id", "bbox", "start_date", "end_date", "platforms")} ),
        ("/v1/analysis", request),
        ("/v1/exports", {**request, "kind": "analysis", "format": "json"}),
        ("/v1/exports", {"release_id": "cell-fixture-v1", "bbox": [106, 10, 107, 11],
            "start_date": "2024-03-01", "end_date": "2024-03-02",
            "kind": "observations", "format": "csv", "platforms": ["Aqua"]}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 409
        assert response.json()["code"] == "UNSUPPORTED_DATASET"


def _assert_processed_cell_routes(client, monkeypatch):
    from app import storage
    from app import cells
    with monkeypatch.context() as patch:
        patch.setattr(storage, "read_observations", _forbid_source_reader)
        patch.setattr("app.drive.list_drive_csvs", _forbid_source_reader)
        patch.setattr("app.drive.scan_drive_csv", _forbid_source_reader)
        _assert_cell_map_selectors(client, storage, patch, cells)
        _assert_processed_paths_reject_raw_reads(client)


@pytest.fixture
def processed_cell_contracts():
    return _assert_processed_cell_routes


def _write_local_source(tmp_path):
    root = tmp_path / "local-csv-tree"
    folder = root / "MODIS"
    folder.mkdir(parents=True)
    path = folder / "MODIS_Terra_Aqua_near_real_time_2026.csv"
    columns = ("latitude", "longitude", "brightness", "scan", "track", "acq_date",
               "acq_time", "satellite", "instrument", "confidence", "version",
               "bright_t31", "frp", "daynight")
    rows = [("1200", "6.1NRT"), ("1201", "6.1URT")]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for clock, version in rows:
            writer.writerow({"latitude": "-14.5", "longitude": "-59.5", "brightness": "300",
                "scan": "1", "track": "1", "acq_date": "2026-01-01", "acq_time": clock,
                "satellite": "A", "instrument": "MODIS", "confidence": "fire\nwatch",
                "version": version, "bright_t31": "290", "frp": "1", "daynight": "D"})
    (root / "Readme.txt").write_text("ignored")
    (root / "ignored.zip").write_bytes(b"not opened")
    (folder / "MODIS_Terra_Aqua_archive_2000-2026.csv").write_bytes(b"not opened")
    return root, path, columns


def _scan_local_source(root, path):
    from app.cells import AreaRecord, GridSettings
    from app.local import discover_local_csvs, scan_local_csv
    selected = {"MODIS/MODIS_Terra_Aqua_near_real_time_2026.csv": "MODIS_NRT"}
    assert discover_local_csvs(root, selected) == ((path, "MODIS_NRT"),)
    world = AreaRecord(area_id="world", name="World", version="1", geometry={
        "type": "Polygon", "coordinates": (((-180, -90), (180, -90),
            (180, 90), (-180, 90), (-180, -90)),)})
    result = scan_local_csv(path, root=root, source_id="MODIS_NRT",
        grid=GridSettings(grid_version="grid-v1", width_km=10.0), area=world,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
        platforms=("Aqua",), maximum_memberships=1)
    assert result.rows_seen == 2 and result.rows_used == 2
    assert result.bytes_read == path.stat().st_size and len(result.sha256) == 64
    assert result.versions == ("6.1NRT", "6.1URT")
    assert len(result.daily_cell_sets[date(2026, 1, 1)]) == 1
    return result


def _assert_processed_checkpoint(tmp_path, result):
    from app.local import write_processed_checkpoint
    checkpoint, digest = write_processed_checkpoint(
        tmp_path / "processed-staging", "local-folder-v1", result, "a" * 64)
    data = json.loads(checkpoint.read_bytes())
    assert len(digest) == 64 and checkpoint.suffix == ".json"
    assert set(data) == {"schema_version", "release_id", "source_id", "file_id",
        "source_sha256", "versions", "selection_sha256", "daily_cell_sets",
        "rows_seen", "rows_used", "bytes_read"}
    assert not list(checkpoint.parent.glob("*.part"))


def _append_changed_local_version(path, columns):
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writerow({"latitude": "-14.5", "longitude": "-59.5", "brightness": "300",
            "scan": "1", "track": "1", "acq_date": "2026-01-01", "acq_time": "1202",
            "satellite": "A", "instrument": "MODIS", "confidence": "nominal",
            "version": "6.2NRT", "bright_t31": "290", "frp": "1", "daynight": "D"})


def _check_local_source(tmp_path):
    root, path, columns = _write_local_source(tmp_path)
    result = _scan_local_source(root, path)
    _assert_processed_checkpoint(tmp_path, result)
    _append_changed_local_version(path, columns)
    from app.cells import AreaRecord, GridSettings
    from app.local import discover_local_csvs, scan_local_csv
    world = AreaRecord(area_id="world", name="World", version="1", geometry={
        "type": "Polygon", "coordinates": (((-180, -90), (180, -90),
            (180, 90), (-180, 90), (-180, -90)),)})
    with pytest.raises(ValueError, match="version changed"):
        scan_local_csv(path, root=root, source_id="MODIS_NRT",
            grid=GridSettings(grid_version="grid-v1", width_km=10.0), area=world,
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
            platforms=("Aqua",), maximum_memberships=1)
    (root / "unknown.csv").write_text("ignored")
    assert discover_local_csvs(root, {"MODIS/MODIS_Terra_Aqua_near_real_time_2026.csv": "MODIS_NRT"}) == ((path, "MODIS_NRT"),)


@pytest.fixture
def local_source_check():
    return _check_local_source
