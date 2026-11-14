"""Tests use invented MODIS rows and invented visit areas."""

import csv
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from importlib import import_module, util
from pathlib import Path

import pytest

from app.models import SourceFileRecord

FIXTURES = Path(__file__).parent / "fixtures"


def source_for(path, product="MODIS"):
    return SourceFileRecord(
        source_file_id="fixture", source_id="MODIS_SP", product=product,
        version="6.03", processing_mode="standard", start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2), downloaded_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), request_parameters={},
    )


def test_source_reader_keeps_text_versions(tmp_path):
    sources = import_module("app.sources")
    path = FIXTURES / "observations.csv"
    batches = list(sources.read_source(path, source_for(path), batch_size=2))
    first = batches[0].observations[0]
    assert batches[0].source_file.version == "6.03"
    assert first.original_fields["version"] == "6.03"
    assert first.observed_at == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    assert first.frp_mw == 0 and first.hotspot_type == "unknown"
    assert {(band.band_name, band.unit) for band in batches[0].bands} == {("MODIS_21_22", "K"), ("MODIS_31", "K")}
    full_name = tmp_path / "full-name.csv"
    full_name.write_text(path.read_text().replace(",A,MODIS,", ",Aqua,MODIS,"))
    named = list(sources.read_source(full_name, source_for(full_name), batch_size=2))
    assert named[0].observations[0].platform == "Aqua"
    with pytest.raises(ValueError, match="source"):
        list(sources.read_source(path, replace(source_for(path), source_id="UNKNOWN"), batch_size=2))
    with pytest.raises(ValueError, match="processing"):
        list(sources.read_source(path, replace(source_for(path), processing_mode="NRT"), batch_size=2))
    viirs = tmp_path / "viirs.csv"
    viirs.write_text("latitude,longitude,bright_ti4,bright_ti5,acq_date,acq_time,satellite,instrument,version,frp\n10.5,106.2,367,290,2026-01-01,1,N,VIIRS,2.0NRT,0\n10.5,106.3,320,290,2026-01-01,2,N,VIIRS,2.0URT,1\n")
    viirs_source = replace(source_for(viirs, "VIIRS"), source_id="VIIRS_SNPP_NRT", version="2.0", processing_mode="NRT")
    viirs_batch = list(sources.read_source(viirs, viirs_source, batch_size=2))[0]
    assert viirs_batch.observations[0].platform == "Suomi-NPP"
    assert {band.band_name for band in viirs_batch.bands} == {"VIIRS_I4", "VIIRS_I5"}
    assert [item.original_fields["version"] for item in viirs_batch.observations] == ["2.0NRT", "2.0URT"]
    assert next(band for band in viirs_batch.bands if band.band_name == "VIIRS_I4").flags == ("possible_sensor_limit",)
    assert sources._platform({"satellite": "N20", "instrument": "VIIRS"},
                             replace(viirs_source, source_id="VIIRS_NOAA20_NRT")) == "NOAA-20"
    assert sources._platform({"satellite": "N21", "instrument": "VIIRS"},
                             replace(viirs_source, source_id="VIIRS_NOAA21_NRT")) == "NOAA-21"
    with pytest.raises(ValueError, match="version"):
        list(sources.read_source(viirs, replace(viirs_source, version="1.0"), batch_size=2))
    unsuffixed = tmp_path / "unsuffixed.csv"
    unsuffixed.write_text(viirs.read_text().replace("2.0NRT", "2.0", 1))
    unsuffixed_source = replace(viirs_source, sha256=hashlib.sha256(unsuffixed.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="version"):
        list(sources.read_source(unsuffixed, unsuffixed_source, batch_size=2))
    exported = tmp_path / "exported.csv"
    exported.write_text(viirs.read_text().replace("bright_ti4", "brightness").replace("bright_ti5", "bright_t31").replace(",N,VIIRS,", ",SNPP,VIIRS,"))
    export_source = replace(viirs_source, sha256=hashlib.sha256(exported.read_bytes()).hexdigest())
    export_batch = list(sources.read_source(exported, export_source, batch_size=2))[0]
    assert export_batch.observations[0].platform == "Suomi-NPP"
    assert next(band for band in export_batch.bands if band.band_name == "VIIRS_bright_t31_unverified").flags == ("unverified_band",)
    raw = path.read_text()
    rows = list(csv.DictReader(raw.splitlines()))
    columns = [name for name in rows[0] if name != "brightness"]
    for row in rows:
        row.pop("brightness")
    missing_band = tmp_path / "missing-band.csv"
    with missing_band.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="brightness band"):
        list(sources.read_source(missing_band, source_for(missing_band), batch_size=2))
    bad = tmp_path / "invalid.csv"
    for content in (raw.replace(",1,A,MODIS,", ",2460,A,MODIS,", 1),
                    raw.replace("latitude,longitude", "lat,longitude", 1),
                    "<html>provider error</html>",
                    raw.replace("bright_t31", "bright_t99", 1)):
        bad.write_text(content)
        with pytest.raises(ValueError):
            list(sources.read_source(bad, source_for(bad), batch_size=2))
    bad.write_text(raw.splitlines()[0] + "\n")
    empty = list(sources.read_source(bad, source_for(bad), batch_size=2))
    assert not any(batch.observations or batch.opportunities for batch in empty)
    bad.write_text(raw)
    reader = sources.read_source(bad, source_for(bad), batch_size=2)
    next(reader)
    bad.write_text(raw + "\n")
    with pytest.raises(ValueError, match="changed"):
        list(reader)


def test_batches_keep_provenance(tmp_path, monkeypatch):
    sources = import_module("app.sources")
    path = FIXTURES / "observations.csv"
    batches = list(sources.read_source(path, source_for(path), batch_size=2))
    assert all(len(batch.observations) <= 2 for batch in batches)
    rows = tuple(item for batch in batches for item in batch.observations)
    assert [item.source_row_id for item in rows] == [1, 2, 3]
    assert len({item.observation_id for item in rows}) == 3
    selected = sources.select_source_records(rows, {"types": ["unknown", "0"], "confidences": ["90", "80"]})
    assert [item.source_row_id for item in selected] == [1, 2]
    other = replace(rows[1], source_file_id="standard", observation_id="standard:1")
    with pytest.raises(ValueError, match="preference"):
        sources.select_source_records((rows[1], other), {})
    preferred = sources.select_source_records((rows[1], other), {"preferred_sources": ["standard", "fixture"]})
    assert [item.observation_id for item in preferred] == ["standard:1"]
    visits = FIXTURES / "opportunities.csv"
    visit_batches = list(sources.read_opportunities(visits, source_for(visits, "fixture-opportunities"), batch_size=1))
    opportunities = tuple(item for batch in visit_batches for item in batch.opportunities)
    assert len(opportunities) == 2 and opportunities[0].footprint["type"] == "Polygon"
    assert opportunities[1].usable_footprint is None
    with visits.open(newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    source_rows[0]["footprint"] = '{"type":"Polygon","coordinates":[[[106,10],[107,10],[107,11],[106,10.1]]]}'
    invalid = tmp_path / "visits.csv"
    with invalid.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=source_rows[0].keys())
        writer.writeheader()
        writer.writerows(source_rows)
    with pytest.raises(ValueError, match="ring"):
        list(sources.read_opportunities(invalid, source_for(invalid, "fixture-opportunities"), batch_size=1))

    drive = import_module("app.drive")
    monkeypatch.setenv("GOOGLE_DRIVE_ACCESS_TOKEN", "test-token")
    csv_bytes = (
        b"latitude,longitude,bright_ti4,bright_ti5,acq_date,acq_time,satellite,instrument,version,frp,confidence\n"
        b'10.5,106.2,320,290,2026-01-01,1,N,VIIRS,2.0NRT,1,"fire\nwatch"\n'
        b"10.5,106.3,321,291,2025-12-31,2,N,VIIRS,2.0URT,2,nominal\n"
    )

    class Reply:
        status_code = 200
        headers = {"content-type": "text/csv"}

        def __init__(self, body=None):
            self.body = body

        def json(self):
            return self.body

        def raise_for_status(self):
            return None

        def iter_bytes(self, size):
            for offset in range(0, len(csv_bytes), 7):
                yield csv_bytes[offset:offset + 7]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class DriveClient:
        def get(self, url, **kwargs):
            if url.endswith("/files"):
                page_token = kwargs.get("params", {}).get("pageToken")
                if page_token:
                    return Reply({"files": []})
                return Reply({"files": [
                    {"id": "drive-csv", "name": "sensor.csv", "mimeType": "text/csv",
                     "size": str(len(csv_bytes)), "modifiedTime": "2026-01-02T00:00:00Z",
                     "version": "7", "headRevisionId": "r7"},
                    {"id": "ignored-zip", "name": "sensor.zip", "mimeType": "application/zip"},
                    {"id": "ignored-notebook", "name": "sensor.ipynb", "mimeType": "text/plain"},
                    {"id": "ignored-shortcut", "name": "sensor.csv", "mimeType": "application/vnd.google-apps.shortcut"},
                ], "nextPageToken": "page-2"})
            return Reply({
                "id": "drive-csv", "name": "sensor.csv", "mimeType": "text/csv",
                "size": str(len(csv_bytes)), "modifiedTime": "2026-01-02T00:00:00Z",
                "version": "7", "headRevisionId": "r7",
            })

        def stream(self, method, url, **kwargs):
            return Reply()

    area = drive.AreaRecord(area_id="world", name="World", version="1", geometry={
        "type": "Polygon", "coordinates": (((-180, -90), (180, -90),
            (180, 90), (-180, 90), (-180, -90)),),
    })
    drive_file = drive.DriveFile(
        file_id="drive-csv", name="sensor.csv", mime_type="text/csv", size=len(csv_bytes),
        modified_time="2026-01-02T00:00:00Z", version="7", head_revision_id="r7",
        md5_checksum=None, sha256_checksum=None, source_id="VIIRS_SNPP_NRT",
    )
    listed = drive.list_drive_csvs("folder", client=DriveClient(), source_ids={
        "drive-csv": "VIIRS_SNPP_NRT", "ignored-zip": "VIIRS_SNPP_NRT",
        "ignored-notebook": "VIIRS_SNPP_NRT", "ignored-shortcut": "VIIRS_SNPP_NRT",
    })
    assert [item.file_id for item in listed] == ["drive-csv"]
    grid = import_module("app.cells").GridSettings(grid_version="grid-v1", width_km=10.0)
    processed = drive.scan_drive_csv(drive_file, client=DriveClient(), grid=grid, area=area,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
        platforms=("Suomi-NPP",), maximum_bytes=1024, maximum_memberships=10)
    assert processed.rows_seen == 2 and processed.rows_used == 1
    assert set(processed.daily_cell_sets) == {date(2026, 1, 1)}
    assert processed.bytes_read == len(csv_bytes) and len(processed.sha256) == 64


def test_fetch_windows_checks_budget_and_resumes(monkeypatch, tmp_path):
    sources = import_module("app.sources")
    models = import_module("app.models")
    settings_path = Path(__file__).parents[1] / "config" / "settings.json"
    settings = models.load_settings(settings_path)
    settings = settings.model_copy(update={
        "downloads": settings.downloads.model_copy(update={"sources": ("MODIS_SP",)})
    })
    secret = "test-map-key-never-log"
    monkeypatch.setenv("FIRMS_MAP_KEY", secret)
    calls = []

    class Reply:
        status_code = 200

        def json(self):
            return {"unexpected": 1}

    class Client:
        def __init__(self, **kwargs):
            assert kwargs.get("verify") is True
            assert kwargs.get("follow_redirects") is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs.get("timeout") is not None
            return Reply()

    httpx = import_module("httpx")
    monkeypatch.setattr(httpx, "Client", Client)
    with pytest.raises(RuntimeError, match="transaction status") as error:
        list(sources.fetch_windows(settings))
    assert len(calls) == 1
    assert "mapkey_status" in calls[0]
    assert secret not in str(error.value)

    data = models.load_settings(settings_path)
    downloads = data.downloads.model_copy(update={
        "sources": ("MODIS_SP",), "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 2),
    })
    storage = data.storage.model_copy(update={"staging_path": tmp_path})
    settings = data.model_copy(update={"downloads": downloads, "storage": storage})
    payload = (FIXTURES / "observations.csv").read_bytes()
    request_urls = []
    stream_calls = []

    class GoodReply:
        status_code = 200
        headers = {"content-type": "text/csv"}
        text = "data_id,min_date,max_date\nMODIS_SP,2020-01-01,2026-12-31\n"

        def json(self):
            return {"current_transactions": 3}

        def raise_for_status(self):
            return None

        def iter_bytes(self, size):
            yield payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class GoodClient:
        def __init__(self, **kwargs):
            assert kwargs == {"verify": True, "follow_redirects": False}
            self.stream_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            request_urls.append(url)
            reply = GoodReply()
            if "mapkey_status" in url:
                return reply
            reply.text = "data_id,min_date,max_date\nMODIS_SP,2020-01-01,2026-12-31\n"
            return reply

        def stream(self, method, url, **kwargs):
            assert method == "GET" and kwargs.get("timeout") == 30
            stream_calls.append(url)
            self.stream_count += 1
            reply = GoodReply()
            reply.headers = {"content-type": "text/csv"}
            if self.stream_count == 1:
                def interrupted(size):
                    yield payload[:10]
                    raise OSError("connection interrupted")
                reply.iter_bytes = interrupted
            return reply

    monkeypatch.setattr(httpx, "Client", GoodClient)
    records = list(sources.fetch_windows(settings))
    assert len(records) == 1 and records[0].source_id == "MODIS_SP"
    assert records[0].start_date == date(2026, 1, 1)
    assert records[0].end_date == date(2026, 1, 2)
    assert len(stream_calls) == 2 and "/106.0,10.0,107.0,11.0/1/2026-01-01" in stream_calls[0]
    assert records[0].sha256 == hashlib.sha256(payload).hexdigest()
    progress = (tmp_path / "download-progress.json").read_text()
    assert secret not in progress
    resumed = list(sources.fetch_windows(settings))
    assert len(resumed) == 1 and len(stream_calls) == 2
    assert sum("mapkey_status" in url for url in request_urls) == 4

    database = tmp_path / "release.sqlite3"
    releases = tmp_path / "releases"
    pipeline_storage = storage.model_copy(update={
        "database_path": database, "releases_path": releases,
    })
    pipeline_settings = settings.model_copy(update={"storage": pipeline_storage})
    storage_module = import_module("app.storage")
    prep_spec = util.spec_from_file_location(
        "prepare_data_cli", Path(__file__).parents[1] / "scripts" / "prepare_data.py")
    prep_cli = util.module_from_spec(prep_spec)
    prep_spec.loader.exec_module(prep_cli)
    prep_cli.prepare_release(pipeline_settings, "fixture-v1")
    assert storage_module.load_release(database, "fixture-v1").summary.available_metrics == ()
    records, paths = prep_cli._source_inputs(pipeline_settings)
    observations, bands = prep_cli._source_rows(records, paths, 1000, 100000)
    selected = sources.select_source_records(observations, settings.science.source_policy)
    first_batches = tuple(prep_cli._iter_batches(records, selected, bands, 1000))
    second_batches = tuple(prep_cli._iter_batches(records, selected, bands, 1000))
    assert first_batches == second_batches
    before_import = {item.name for item in tmp_path.iterdir()}
    check_spec = util.spec_from_file_location(
        "check_results_cli", Path(__file__).parents[1] / "scripts" / "check_results.py")
    check_cli = util.module_from_spec(check_spec)
    check_spec.loader.exec_module(check_cli)
    assert before_import == {item.name for item in tmp_path.iterdir()}
    checked = check_cli.check_release(pipeline_settings, "fixture-v1")
    assert checked["status"] == "passed" and checked["rows_checked"] == 3
    cli_settings = models.load_settings(settings_path).model_dump(mode="json")
    cli_settings["storage"].update({
        "database_path": str(database), "staging_path": str(tmp_path),
        "releases_path": str(releases),
    })
    cli_settings["downloads"].update({
        "sources": ["MODIS_SP"], "start_date": "2026-01-01", "end_date": "2026-01-02",
    })
    cli_settings_path = tmp_path / "cli-settings.json"
    cli_settings_path.write_text(json.dumps(cli_settings))
    assert check_cli.main(["--settings", str(cli_settings_path), "--release-id", "fixture-v1"]) == 0
    assert prep_cli.main(["--settings", str(cli_settings_path), "--release-id", "fixture-v1"]) == 1
    prep_cli.prepare_release(pipeline_settings, "fixture-v2")
    assert check_cli.check_release(pipeline_settings, "fixture-v2")["rows_checked"] == 3
    assert check_cli.check_release(pipeline_settings, "fixture-v1")["rows_checked"] == 3
    csv_path = tmp_path / "MODIS_SP_2026-01-01_1.csv"
    csv_path.write_bytes(payload.replace(b",320,", b",321,", 1))
    with pytest.raises(ValueError, match="hash"):
        prep_cli.prepare_release(pipeline_settings, "failed-v1")
    assert "failed-v1" not in {item.release_id for item in storage_module.list_releases(database)}
    assert not (releases / "failed-v1").exists()

    limited_root = tmp_path / "limited"
    limited_storage = storage.model_copy(update={
        "staging_path": limited_root, "temporary_bytes_limit": 10,
    })
    limited_settings = settings.model_copy(update={"storage": limited_storage})

    class LargeClient(GoodClient):
        def stream(self, method, url, **kwargs):
            reply = GoodReply()
            reply.headers = {"content-type": "text/csv"}
            assert "content-length" not in reply.headers
            return reply

    monkeypatch.setattr(httpx, "Client", LargeClient)
    with pytest.raises(RuntimeError, match="temporary download limit"):
        list(sources.fetch_windows(limited_settings))
    assert not list(limited_root.glob("*.part"))

    class PauseReply(GoodReply):
        def json(self):
            return {"current_transactions": 4000}

    class PauseClient(GoodClient):
        def get(self, url, **kwargs):
            request_urls.append(url)
            return PauseReply()

        def stream(self, method, url, **kwargs):
            raise AssertionError("must stop before data request")

    monkeypatch.setattr(httpx, "Client", PauseClient)
    with pytest.raises(RuntimeError, match="pause limit"):
        list(sources.fetch_windows(settings.model_copy(update={
            "storage": storage.model_copy(update={"staging_path": tmp_path / "pause"})
        })))

    class NearPauseReply(GoodReply):
        def json(self):
            return {"current_transactions": 3994}

    class NearPauseClient(GoodClient):
        def get(self, url, **kwargs):
            request_urls.append(url)
            return NearPauseReply()

        def stream(self, method, url, **kwargs):
            raise AssertionError("must reserve budget before availability request")

    before_near_pause = len(request_urls)
    monkeypatch.setattr(httpx, "Client", NearPauseClient)
    with pytest.raises(RuntimeError, match="pause limit"):
        list(sources.fetch_windows(settings.model_copy(update={
            "storage": storage.model_copy(update={"staging_path": tmp_path / "near-pause"})
        })))
    new_urls = request_urls[before_near_pause:]
    assert len(new_urls) == 1 and "mapkey_status" in new_urls[0]

    class ErrorReply(GoodReply):
        def raise_for_status(self):
            raise ValueError("provider error with private URL")

    class ErrorClient(GoodClient):
        def get(self, url, **kwargs):
            request_urls.append(url)
            return GoodReply() if "mapkey_status" in url else ErrorReply()

    monkeypatch.setattr(httpx, "Client", ErrorClient)
    with pytest.raises(RuntimeError, match="FIRMS request failed") as provider_error:
        list(sources.fetch_windows(settings.model_copy(update={
            "storage": storage.model_copy(update={"staging_path": tmp_path / "error"})
        })))
    assert secret not in str(provider_error.value)

    spec = util.spec_from_file_location("fetch_data_cli", Path(__file__).parents[1] / "scripts" / "fetch_data.py")
    fetch_cli = util.module_from_spec(spec)
    spec.loader.exec_module(fetch_cli)
    args = fetch_cli.parse_arguments([])
    assert args.settings == Path(__file__).parents[1] / "config" / "settings.json"
    with pytest.raises(SystemExit):
        fetch_cli.parse_arguments(["--map-key", secret])
    empty_settings = models.load_settings(settings_path).model_dump(mode="json")
    empty_settings["downloads"]["sources"] = []
    empty_settings_path = tmp_path / "empty-settings.json"
    empty_settings_path.write_text(json.dumps(empty_settings))
    assert fetch_cli.main(["--settings", str(empty_settings_path)]) == 0
    for name in ("prepare_data", "check_results"):
        spec = util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with pytest.raises(SystemExit):
            module.parse_arguments([])
        parsed = module.parse_arguments(["--release-id", "fixture-v1"])
        assert parsed.settings == Path(__file__).parents[1] / "config" / "settings.json"
        if name == "prepare_data":
            sample_path = Path(__file__).parents[1] / "data" / "samples" / "sample_viirs_snpp_071223.csv"
            local_args = module.parse_arguments([
                "--release-id", "local-sample-v1", "--input-csv", str(sample_path),
            ])
            assert local_args.input_csv == sample_path
            with pytest.raises(SystemExit):
                module.parse_arguments(["--release-id", "bad", "--input-csv", str(sample_path),
                                        "--drive-folder-id", "folder"])
