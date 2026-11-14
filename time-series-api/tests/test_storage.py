"""Tests for fixed releases in a temporary database."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone
from importlib import import_module

import pytest
from pydantic import TypeAdapter

from app.models import (
    AnalysisRequest, ApiError, BandRecord, CoverageResult, DailyRecord, HotspotQuery, ObservationRecord, ReleaseRecord, ReleaseSummary,
    SourceBatch, SourceFileRecord, StorageSettings, ValidationReport, load_settings,
)


def report_bytes(report):
    data = TypeAdapter(ValidationReport).dump_python(report, mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.fixture
def candidate(tmp_path):
    storage = StorageSettings(
        database_path=tmp_path / "data.sqlite3", staging_path=tmp_path / "staging",
        releases_path=tmp_path / "releases", saved_bytes_limit=1000000,
        temporary_bytes_limit=1000000,
    )

    def make(release_id, source_id, row_ids=(1, 2), mode="NRT"):
        file = SourceFileRecord(
            source_file_id=source_id, source_id="test", product="invented",
            version="6.03", processing_mode=mode, start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2), downloaded_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            sha256="0" * 64, request_parameters={},
        )
        observations = tuple(ObservationRecord(
            observation_id=f"{source_id}-{row}", source_file_id=source_id,
            source_row_id=row, pass_id=None, platform="Aqua", instrument="MODIS",
            observed_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            longitude=106.0 + row / 10, latitude=10.5, scan_km=1.0, track_km=1.0,
            frp_mw=0.0, confidence="nominal", hotspot_type="unknown", quality=(),
            original_fields={"row": str(row)},
        ) for row in row_ids)
        batch = SourceBatch(source_file=file, observations=observations, bands=(), opportunities=())
        summary = ReleaseSummary(
            release_id=release_id, study_areas=((106, 10, 107, 11),),
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
            latest_source_dates={"Aqua": date(2026, 1, 1)},
            available_metrics=("observed_hotspot_count",), allowed_platforms=("Aqua",),
        )
        frozen_settings = {"schema_version": 1, "tested_scope": {}}
        report = ValidationReport(
            release_id=release_id,
            checks={"provenance": {"source_hashes": {source_id: file.sha256}, "code_version": "test", "method_id": None, "settings": frozen_settings}},
            supported_metrics=("observed_hotspot_count",),
            tested_scope={}, failures=(), random_seed=None, repeat_count=None,
            memory_bytes=0, elapsed_seconds=0.0,
        )
        manifest = ReleaseRecord(
            summary=summary, method_id=None, reference_count_definition=None,
            code_version="test", settings=frozen_settings, source_files=(file,),
            source_selection={"rows": {source_id: list(row_ids)}}, baseline_rules={},
            report_sha256=hashlib.sha256(report_bytes(report)).hexdigest(), report_urls=(),
        )
        return storage, manifest, report, batch
    return make


def query(release_id, page_size=1):
    return HotspotQuery(release_id=release_id, bbox=(106, 10, 107, 11),
                        start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
                        platforms=("Aqua",), page_size=page_size)


def test_storage_round_trip(candidate):
    store = import_module("app.storage")
    settings, manifest, report, batch = candidate("release-a", "file-a")
    original = {"row": "1"}
    copied = replace(batch.observations[0], original_fields=original)
    original["row"] = "changed"
    assert copied.original_fields["row"] == "1"
    selection = {"rows": {"file-a": [1, 2]}}
    copied_manifest = replace(manifest, source_selection=selection)
    selection["rows"]["file-a"].append(3)
    assert copied_manifest.source_selection["rows"]["file-a"] == [1, 2]
    with pytest.raises(sqlite3.OperationalError):
        store.list_releases(settings.database_path)
    assert not settings.database_path.exists()
    store.initialize_database(settings.database_path)
    store.publish_release(settings.database_path, iter([batch]), iter(()), manifest, report, storage=settings)
    assert store.list_releases(settings.database_path) == (manifest.summary,)
    assert store.load_release(settings.database_path, "release-a") == manifest
    first = store.read_observations(settings.database_path, query("release-a"), None)
    assert [row.observation_id for row in first.observations] == ["file-a-1"]
    assert first.observations[0].observed_at == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    second = store.read_observations(settings.database_path, query("release-a"), first.next_position)
    assert [row.observation_id for row in second.observations] == ["file-a-2"]
    assert second.next_position is None
    api_settings = load_settings(__import__("pathlib").Path(__file__).resolve().parents[1] / "config/settings.json").api
    request = AnalysisRequest(release_id="release-a", bbox=(106, 10, 107, 11),
                              start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
                              metric="observed_hotspot_count", aggregation="day", platforms=("Aqua",))
    inputs = store.read_daily(settings.database_path, request, settings=api_settings)
    assert [row.observation_id for row in inputs.observations] == ["file-a-1", "file-a-2"]
    assert inputs.daily == () and inputs.opportunities == ()
    too_many_years = AnalysisRequest(
        release_id="release-a", bbox=(106, 10, 107, 11), start_date=date(2024, 2, 29),
        end_date=date(2024, 3, 1), metric="observed_hotspot_count", aggregation="day", platforms=("Aqua",),
        comparison={"mode": "same_elapsed_days", "baseline_start_year": 2010, "baseline_end_year": 2023},
    )
    with pytest.raises(ApiError) as too_large:
        store.read_daily(settings.database_path, too_many_years, settings=api_settings)
    assert too_large.value.code == "QUERY_TOO_LARGE"
    _, leap_manifest, leap_report, leap_batch = candidate("release-leap", "file-leap")
    leap_source = replace(leap_batch.source_file, start_date=date(2023, 1, 1), end_date=date(2025, 1, 1))
    leap_summary = leap_manifest.summary.model_copy(update={"start_date": date(2023, 1, 1), "end_date": date(2025, 1, 1)})
    leap_manifest = replace(leap_manifest, source_files=(leap_source,), summary=leap_summary)
    leap_observations = tuple(replace(item, observed_at=datetime(year, 3, 1, tzinfo=timezone.utc))
                              for item, year in zip(leap_batch.observations, (2023, 2024)))
    leap_batch = replace(leap_batch, source_file=leap_source, observations=leap_observations)
    store.publish_release(settings.database_path, iter([leap_batch]), iter(()), leap_manifest, leap_report, storage=settings)
    leap_query = AnalysisRequest(
        release_id="release-leap", bbox=(106, 10, 107, 11), start_date=date(2024, 2, 29),
        end_date=date(2024, 3, 2), metric="observed_hotspot_count", aggregation="day", platforms=("Aqua",),
        comparison={"mode": "same_elapsed_days", "baseline_start_year": 2023, "baseline_end_year": 2023},
    )
    leap_inputs = store.read_daily(settings.database_path, leap_query, settings=api_settings)
    assert {item.observed_at.year for item in leap_inputs.observations} == {2023, 2024}
    with pytest.raises(ApiError) as missing:
        store.load_release(settings.database_path, "' OR 1=1 --")
    assert missing.value.code == "RELEASE_NOT_FOUND"
    (settings.releases_path / "release-a" / "validation.json").write_text("{}")
    with pytest.raises(ValueError, match="match"):
        store.load_release(settings.database_path, "release-a")


def test_failed_publish_rolls_back(candidate, monkeypatch):
    store = import_module("app.storage")
    settings, manifest, report, batch = candidate("release-a", "file-a")
    closed = []
    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            super().close()
    connect = sqlite3.connect
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *args, **kwargs: connect(*args, **kwargs, factory=TrackedConnection))
        store.initialize_database(settings.database_path)
    assert closed == [True]
    wrong_report = ValidationReport(**{**report.__dict__, "release_id": "other"})
    with pytest.raises(ValueError):
        store.publish_release(settings.database_path, iter([batch]), iter(()), manifest, wrong_report, storage=settings)
    assert store.list_releases(settings.database_path) == ()
    bad_daily = DailyRecord(release_id="release-a", method_id=None, cell_id="cell-1",
        cell_area={"type": "Polygon", "coordinates": (((106.0, 10.0), (107.0, 10.0), (107.0, 11.0), (106.0, 10.0)),)},
        cell_center={"type": "Point", "coordinates": (106.5, 10.5)},
        date=date(2026, 1, 1), source_count=-1, reference_count_estimate=None,
        coverage=CoverageResult(expected_days=1, usable_days=None, numerator=None, denominator=None, unit="km2_visits", valid_coverage_fraction=None),
        uncertainty=None, status="missing")
    written = []
    write_files = store._write_release_files
    def observe_files(directory, manifest_data, report_data):
        write_files(directory, manifest_data, report_data)
        written.append((directory / "manifest.json").exists() and (directory / "validation.json").exists())
    monkeypatch.setattr(store, "_write_release_files", observe_files)
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        store.publish_release(settings.database_path, iter([batch]), iter([bad_daily]), manifest, report, storage=settings)
    assert written == [True]
    assert store.list_releases(settings.database_path) == ()
    unchecked_estimate = replace(bad_daily, source_count=1, reference_count_estimate=1.0)
    with pytest.raises(ValueError, match="estimate"):
        store.publish_release(settings.database_path, iter([batch]), iter([unchecked_estimate]), manifest, report, storage=settings)
    assert store.list_releases(settings.database_path) == ()
    wrong_count = replace(bad_daily, source_count=True)
    with pytest.raises(ValueError, match="count"):
        store.publish_release(settings.database_path, iter([batch]), iter([wrong_count]), manifest, report, storage=settings)
    assert store.list_releases(settings.database_path) == ()
    bad_observation = replace(batch.observations[0], observed_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
    invalid_batch = replace(batch, observations=(bad_observation, batch.observations[1]))
    with pytest.raises(ValueError, match="date"):
        store.publish_release(settings.database_path, iter([invalid_batch]), iter(()), manifest, report, storage=settings)
    assert store.list_releases(settings.database_path) == ()
    guessed_settings = {**manifest.settings, "method_id": "unverified"}
    provenance = {**report.checks["provenance"], "method_id": "unverified", "settings": guessed_settings}
    guessed_report = replace(report, checks={"provenance": provenance}, supported_metrics=("harmonized_hotspot_count",))
    guessed_manifest = replace(manifest, method_id="unverified", settings=guessed_settings,
        summary=manifest.summary.model_copy(update={"available_metrics": ("harmonized_hotspot_count",)}),
        report_sha256=hashlib.sha256(report_bytes(guessed_report)).hexdigest())
    with pytest.raises(ValueError, match="validated"):
        store.publish_release(settings.database_path, iter([batch]), iter(()), guessed_manifest, guessed_report, storage=settings)
    assert store.list_releases(settings.database_path) == ()


def test_old_release_is_unchanged_after_publication(candidate):
    store = import_module("app.storage")
    settings, first_manifest, first_report, first_batch = candidate("release-a", "file-a")
    _, second_manifest, second_report, second_batch = candidate("release-b", "file-b", mode="standard")
    provenance = dict(second_report.checks["provenance"])
    provenance["source_hashes"] = {"file-a": first_batch.source_file.sha256, "file-b": second_batch.source_file.sha256}
    second_report = replace(second_report, checks={"provenance": provenance})
    sources = import_module("app.sources")
    selected = sources.select_source_records(first_batch.observations + second_batch.observations,
                                              {"preferred_sources": ["file-b", "file-a"]})
    assert [item.observation_id for item in selected] == ["file-b-1", "file-b-2"]
    selection = {"file-a": [], "file-b": [item.source_row_id for item in selected]}
    second_manifest = replace(second_manifest, source_files=(first_batch.source_file, second_batch.source_file),
                              source_selection={"rows": selection, "reason": "standard replaces NRT"},
                              report_sha256=hashlib.sha256(report_bytes(second_report)).hexdigest())
    store.initialize_database(settings.database_path)
    store.publish_release(settings.database_path, iter([first_batch]), iter(()), first_manifest, first_report, storage=settings)
    store.publish_release(settings.database_path, iter([first_batch, second_batch]), iter(()), second_manifest, second_report, storage=settings)
    assert store.load_release(settings.database_path, "release-a") == first_manifest
    page = store.read_observations(settings.database_path, query("release-a", 10), None)
    assert [row.observation_id for row in page.observations] == ["file-a-1", "file-a-2"]
    new_page = store.read_observations(settings.database_path, query("release-b", 10), None)
    assert [row.observation_id for row in new_page.observations] == ["file-b-1", "file-b-2"]
    with pytest.raises(ValueError):
        store.publish_release(settings.database_path, iter([first_batch]), iter(()), first_manifest, first_report, storage=settings)
    _, third_manifest, third_report, third_batch = candidate("release-c", "file-c")
    foreign_band = BandRecord(observation_id="file-a-1", band_name="test", value=1.0, unit="K", flags=())
    bad_batch = SourceBatch(source_file=third_batch.source_file, observations=third_batch.observations,
                            bands=(foreign_band,), opportunities=())
    with pytest.raises(ValueError):
        store.publish_release(settings.database_path, iter([bad_batch]), iter(()), third_manifest, third_report, storage=settings)
    assert store.read_observations(settings.database_path, query("release-a", 10), None).bands == ()
    _, fourth_manifest, fourth_report, fourth_batch = candidate("release-d", "file-a")
    changed_batch = SourceBatch(source_file=fourth_batch.source_file, observations=fourth_batch.observations,
                                bands=(foreign_band,), opportunities=())
    with pytest.raises(ValueError):
        store.publish_release(settings.database_path, iter([changed_batch]), iter(()), fourth_manifest, fourth_report, storage=settings)
    assert store.read_observations(settings.database_path, query("release-a", 10), None).bands == ()
