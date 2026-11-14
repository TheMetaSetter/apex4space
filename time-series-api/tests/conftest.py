"""Small published releases for API tests."""

import hashlib
import json
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
        "staging_path": str(tmp_path / "staging"), "releases_path": str(tmp_path / "releases")})
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
    from app.main import create_app

    with TestClient(create_app(settings_path)) as client:
        yield client
