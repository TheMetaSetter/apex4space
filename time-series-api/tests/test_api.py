"""Contract tests for requests accepted by the API."""

import importlib
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("change", "valid"),
    [
        ({}, True),
        ({"start_date": "2026-01-01T00:00:00Z"}, False),
        ({"bbox": [True, 10, 107, 11]}, False),
        ({"bbox": ["106", 10, 107, 11]}, False),
        ({"bbox": [float("nan"), 10, 107, 11]}, False),
        ({"bbox": [106, 10, float("inf"), 11]}, False),
        ({"extra": 1}, False),
        ({"platforms": ["Aqua", "Aqua"]}, False),
        ({"release_id": "../release"}, False),
        ({"end_date": "2025-12-31"}, False),
        ({"end_date": "2027-01-02", "comparison": {"mode": "same_elapsed_days", "baseline_start_year": 2020, "baseline_end_year": 2024}}, False),
    ],
)
def test_request_fields(change, valid):
    models = importlib.import_module("app.models")
    data = {
        "release_id": "pilot-v1", "bbox": [106, 10, 107, 11],
        "start_date": "2026-01-01", "end_date": "2026-01-02",
        "metric": "observed_hotspot_count", "aggregation": "day",
        "platforms": ["Aqua"],
    }
    data.update(change)
    if valid:
        assert models.AnalysisRequest.model_validate(data).start_date.isoformat() == "2026-01-01"
        if not change:
            with pytest.raises(ValidationError):
                models.ExportRequest.model_validate({
                    "release_id": "pilot-v1", "bbox": [106, 10, 107, 11],
                    "start_date": "2026-01-01", "end_date": "2026-01-02",
                    "kind": "observations", "format": "json", "platforms": ["Aqua"],
                })
    else:
        with pytest.raises(ValidationError):
            models.AnalysisRequest.model_validate(data)


def test_selection_geometry_keeps_input_and_closes_ring():
    models = importlib.import_module("app.models")
    bbox = (106.0, 10.0, 107.0, 11.0)
    assert models.selection_geometry(bbox) == {
        "type": "Polygon",
        "coordinates": (((106.0, 10.0), (107.0, 10.0), (107.0, 11.0),
                         (106.0, 11.0), (106.0, 10.0)),),
    }
    assert bbox == (106.0, 10.0, 107.0, 11.0)
    cells = importlib.import_module("app.cells")
    query = cells.CellMapQuery.model_validate({
        "release_id": "pilot-v1", "date": "2026-01-01", "bbox": [106, 10, 107, 11],
    })
    assert query.bbox == bbox and query.area_id is None
    for invalid in (
        {"release_id": "pilot-v1", "date": "2026-01-01"},
        {"release_id": "pilot-v1", "date": "2026-01-01", "bbox": [106, 10, 107, 11], "area_id": "vn"},
    ):
        with pytest.raises(ValidationError):
            cells.CellMapQuery.model_validate(invalid)
    assert cells.DailyHotspotSummary.model_validate({
        "release_id": "pilot-v1", "area_id": "test-area", "date": "2026-01-01",
        "active_cell_count": 2, "hotspot_cell_ids": ["0:0", "1:0"], "status": "available",
    }).active_cell_count == 2
    with pytest.raises(ValidationError):
        cells.DailyHotspotSummary.model_validate({
            "release_id": "pilot-v1", "area_id": "test-area", "date": "2026-01-01",
            "active_cell_count": 2, "hotspot_cell_ids": ["0:0"], "status": "available",
        })
    cell = cells.CellRecord(grid_version="grid-v1", cell_id="0:0",
        center_longitude=1.0, center_latitude=1.0,
        geometry={"type": "Polygon", "coordinates": (((0, 0), (2, 0), (2, 2), (0, 2), (0, 0)),)})
    summary = cells.DailyHotspotSummary(release_id="pilot-v1", area_id="test-area",
        date=date(2026, 1, 1), active_cell_count=1, hotspot_cell_ids=("0:0",), status="available")
    map_query = cells.CellMapQuery(release_id="pilot-v1", date=date(2026, 1, 1), bbox=(0, 0, 2, 2))
    clipped = cells.make_cell_map(map_query, summary, (cell,), grid_version="grid-v1",
        selection={"type": "Polygon", "coordinates": (((0.5, 0.5), (1.5, 0.5),
            (1.5, 1.5), (0.5, 1.5), (0.5, 0.5)),)})
    assert clipped.active_cell_count == 1
    assert clipped.features[0].id == "0:0"
    assert clipped.features[0].geometry["type"] == "Polygon"
    excluded = cells.make_cell_map(map_query, summary, (cell,), grid_version="grid-v1",
        selection={"type": "Polygon", "coordinates": (((0.5, 0.5), (1.5, 0.5),
            (1.5, 1.5), (0.5, 1.5), (0.5, 0.5)),
            ((0.9, 0.9), (1.1, 0.9), (1.1, 1.1), (0.9, 1.1), (0.9, 0.9)))})
    assert excluded.active_cell_count == 0


def test_settings_loads_independently_and_rejects_bad_limits(tmp_path):
    import copy
    import json

    models = importlib.import_module("app.models")
    data = {
        "storage": {"database_path": "data/service.sqlite3", "staging_path": "data/staging", "releases_path": "data/releases", "saved_bytes_limit": 524288000, "temporary_bytes_limit": 2147483648},
        "downloads": {"sources": [], "bbox": [106, 10, 107, 11], "start_date": "2026-09-01", "end_date": "2026-09-03", "window_days": 2, "provider_window_seconds": 600, "transaction_limit": 5000, "transaction_pause_at": 4000, "timeout_seconds": 30, "retry_limit": 2},
        "science": {"study_areas": [[106, 10, 107, 11]], "source_policy": {}, "type_policy": "all", "confidence_policy": {}, "grid": {}, "reference_schedule": {}, "minimum_coverage_fraction": 0.8, "method_id": None, "method_version": None, "random_seed": 0, "repeat_count": 1, "test_splits": {}, "matching_time_gaps_minutes": [15, 30, 60, 120], "acceptance_targets": {}, "rule_notes": {}},
        "api": {"selected_release_id": None, "allowed_origins": [], "allowed_hosts": ["localhost"], "default_page_size": 1000, "maximum_page_size": 10000, "query_limits": {"maximum_days": 3660, "maximum_baseline_years": 10, "maximum_input_rows": 100000, "maximum_cells": 10000, "maximum_execution_seconds": 5}, "export_limits": {"maximum_rows": 10000, "maximum_bytes": 8388608, "maximum_execution_seconds": 5}, "request_bytes_limit": 16384, "requests_per_minute": 60, "stale_after_days": 3, "public_report_base_url": None},
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    first = models.load_settings(path)
    second = models.load_settings(path)
    assert first.api.selected_release_id is None
    assert first.storage.database_path == (__import__("pathlib").Path(models.__file__).resolve().parents[1] / "data/service.sqlite3")
    first.science.source_policy["example"] = True
    assert second.science.source_policy == {}
    for group, field, value in (
        ("downloads", "bbox", [True, 10, 107, 11]),
        ("downloads", "bbox", None),
        ("downloads", "window_days", "2"),
        ("downloads", "start_date", 1788220800),
        ("downloads", "timeout_seconds", True),
        ("api", "selected_release_id", "../release"),
        ("api", "allowed_origins", ["*"]),
        ("science", "method_id", "unchecked"),
        ("science", "study_areas", None),
    ):
        bad = copy.deepcopy(data)
        bad[group][field] = value
        path.write_text(json.dumps(bad))
        with pytest.raises(ValidationError):
            models.load_settings(path)
    data["api"]["query_limits"]["maximum_days"] = -1
    path.write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        models.load_settings(path)
    data["api"]["query_limits"]["maximum_days"] = 3660
    data["api"]["unexpected"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        models.load_settings(path)
    path.write_text(" " * 65537)
    with pytest.raises(ValueError, match="too large"):
        models.load_settings(path)
    data["api"].pop("unexpected")
    data["api"]["query_limits"]["maximum_days"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        models.load_settings(path)


def test_requests_reject_coerced_limits_and_bad_comparisons():
    models = importlib.import_module("app.models")
    valid = {"release_id": "r1", "bbox": [106, 10, 107, 11], "start_date": "2026-01-01", "end_date": "2026-01-02", "platforms": ["Aqua"], "page_size": True}
    with pytest.raises(ValidationError):
        models.HotspotQuery.model_validate(valid)
    valid.pop("page_size")
    valid.update({"kind": "analysis", "format": "json", "metric": "harmonized_hotspot_count", "aggregation": "day"})
    assert models.ExportRequest.model_validate(valid).platforms == ("Aqua",)


def test_serving_rejects_unselected_release(tmp_path, monkeypatch):
    main = importlib.import_module("app.main")
    models = importlib.import_module("app.models")
    settings = models.load_settings
    project_settings = __import__("pathlib").Path(__file__).resolve().parents[1] / "config/settings.json"
    unselected = settings(project_settings)
    unselected = unselected.model_copy(update={
        "api": unselected.api.model_copy(update={"selected_release_id": None})
    })
    monkeypatch.setattr(main, "load_settings", lambda path: unselected)
    with pytest.raises(ValueError, match="release"):
        main.create_app(tmp_path / "settings.json")
    trusted = settings(project_settings)
    trusted = trusted.model_copy(update={"api": trusted.api.model_copy(update={"selected_release_id": "factory-test"})})
    paths = []
    monkeypatch.setattr(main, "load_settings", lambda path: paths.append(path) or trusted)
    monkeypatch.delenv("CURSOR_SECRET", raising=False)
    with pytest.raises(ValueError, match="CURSOR_SECRET"):
        main.create_app(tmp_path / "explicit.json")
    monkeypatch.setenv("CURSOR_SECRET", "short")
    with pytest.raises(ValueError, match="CURSOR_SECRET"):
        main.create_app(tmp_path / "explicit.json")
    monkeypatch.setenv("CURSOR_SECRET", "s" * 32)
    explicit = tmp_path / "explicit.json"
    paths.clear()
    app = main.create_app(explicit)
    assert app.state.settings is trusted and paths == [explicit]
    paths.clear()
    main.create_app()
    assert paths == [Path(main.__file__).resolve().parents[1] / "config/settings.json"]


def test_request_rejects_empty_platform_and_coerced_baseline():
    models = importlib.import_module("app.models")
    query = {"release_id": "r1", "bbox": [106, 10, 107, 11], "start_date": "2026-01-01", "end_date": "2026-01-02", "metric": "observed_hotspot_count", "aggregation": "day", "platforms": [""]}
    with pytest.raises(ValidationError):
        models.AnalysisRequest.model_validate(query)
    query["platforms"] = ["Aqua"]
    query["metric"] = "harmonized_hotspot_count"
    assert models.AnalysisRequest.model_validate(query).platforms == ("Aqua",)
    query["metric"] = "observed_hotspot_count"
    query["comparison"] = {"mode": "same_elapsed_days", "baseline_start_year": True, "baseline_end_year": 2025}
    with pytest.raises(ValidationError):
        models.AnalysisRequest.model_validate(query)
    query["comparison"]["baseline_start_year"] = 0
    with pytest.raises(ValidationError):
        models.AnalysisRequest.model_validate(query)
    query.pop("comparison")
    query["start_date"] = 1767225600
    with pytest.raises(ValidationError):
        models.AnalysisRequest.model_validate(query)
    query["start_date"] = "2026-01-01"
    query["platforms"] = [f"platform-{number}" for number in range(17)]
    with pytest.raises(ValidationError):
        models.AnalysisRequest.model_validate(query)


def test_route_contracts(api_client, monkeypatch, tmp_path):
    assert api_client.get("/health/live").json() == {"status": "ok"}
    assert api_client.get("/health/ready").json() == {"status": "ok"}
    releases = api_client.get("/v1/releases").json()
    assert [item["release_id"] for item in releases] == ["api-fixture-v1"]
    detail = api_client.get("/v1/releases/api-fixture-v1").json()
    assert detail["source_files"][0]["source_id"] == "MODIS_SP"
    assert "database_path" not in detail and "FIRMS_MAP_KEY" not in str(detail)
    assert api_client.get("/v1/metrics").status_code == 200
    _assert_openapi(api_client)
    from app import storage

    with monkeypatch.context() as patch:
        def forbidden(*args, **kwargs):
            raise AssertionError("map request tried to read source data")
        patch.setattr(storage, "read_observations", forbidden)
        patch.setattr("app.drive.list_drive_csvs", forbidden)
        cell_map = api_client.post("/v1/hotspots/cells/query", json={
            "release_id": "cell-fixture-v1", "date": "2024-03-01",
            "area_id": "test-area",
        })
        assert cell_map.status_code == 200
        assert cell_map.json()["active_cell_count"] == 1
        assert cell_map.json()["features"][0]["id"] == "0:0"
        bbox_map = api_client.post("/v1/hotspots/cells/query", json={
            "release_id": "cell-fixture-v1", "date": "2024-03-01",
            "bbox": [106, 10, 107, 11],
        })
        assert bbox_map.status_code == 200 and bbox_map.json()["active_cell_count"] == 1
        outside = api_client.post("/v1/hotspots/cells/query", json={
            "release_id": "cell-fixture-v1", "date": "2024-03-01",
            "bbox": [0, 0, 1, 1],
        })
        assert outside.status_code == 422 and outside.json()["code"] == "AREA_NOT_PREPARED"
        raw = api_client.post("/v1/hotspots/query", json={
            "release_id": "cell-fixture-v1", "bbox": [106, 10, 107, 11],
            "start_date": "2024-03-01", "end_date": "2024-03-02", "platforms": ["Aqua"],
        })
        assert raw.status_code == 409 and raw.json()["code"] == "UNSUPPORTED_DATASET"
    request = _api_request()
    analysis = api_client.post("/v1/analysis", json=request)
    assert analysis.status_code == 200 and analysis.json()["summary"]["value"] == 2
    request_id = analysis.headers["x-request-id"]
    assert len(request_id) == 32 and all(char in "0123456789abcdef" for char in request_id)
    _assert_api_errors(api_client, request, monkeypatch, tmp_path)
    point_request = {key: request[key] for key in ("release_id", "bbox", "start_date", "end_date", "platforms")}
    first = api_client.post("/v1/hotspots/query", json={**point_request, "page_size": 1}).json()
    assert first["type"] == "FeatureCollection" and first["has_more"] is True
    assert first["features"][0]["geometry"]["coordinates"] == [106.21, 10.5]
    assert first["features"][0]["properties"]["version"] == "6.03"
    assert first["features"][0]["properties"]["bands"][0]["band_name"] == "MODIS_31"
    second = api_client.post("/v1/hotspots/query", json={**point_request, "page_size": 1,
                                    "cursor": first["next_cursor"]}).json()
    assert len(second["features"]) == 1 and second["has_more"] is False
    settings = api_client.app.state.settings
    limited_api = settings.api.model_copy(update={"maximum_page_size": 1})
    api_client.app.state.settings = settings.model_copy(update={"api": limited_api})
    too_many = api_client.post("/v1/hotspots/query", json={**point_request, "page_size": 2})
    assert too_many.status_code == 422 and too_many.json()["code"] == "PAGE_SIZE_LIMIT"


def _api_request():
    return {"release_id": "api-fixture-v1", "bbox": [106, 10, 107, 11],
            "start_date": "2024-03-01", "end_date": "2024-03-02",
            "metric": "observed_hotspot_count", "aggregation": "day", "platforms": ["Aqua"]}


def _assert_openapi(client):
    schema = client.get("/openapi.json").json()
    saved_schema = json.loads((Path(__file__).parents[1] / "openapi.json").read_text())
    assert schema == saved_schema
    operations = {operation["operationId"] for path in schema["paths"].values() for operation in path.values()}
    assert operations == {"health_live", "health_ready", "list_releases", "get_release", "list_metrics", "analyze", "query_hotspots", "query_hotspot_cells", "export_results"}
    point = schema["components"]["schemas"]["PointGeometry"]
    assert point["properties"]["type"].get("const") == "Point"
    assert point["properties"]["coordinates"]["type"] == "array"
    export = schema["paths"]["/v1/exports"]["post"]
    assert "ExportRequest" in json.dumps(export["requestBody"])
    response_types = export["responses"]["200"]["content"]
    assert "application/json" in response_types and "text/csv" in response_types


def _assert_api_errors(client, request, monkeypatch, tmp_path):
    bad = client.post("/v1/analysis", json={"private_input": "do-not-return"},
                      headers={"Origin": "http://localhost:3000"})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_REQUEST"
    assert bad.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "do-not-return" not in bad.text and bad.json()["request_id"] == bad.headers["x-request-id"]
    unknown = client.post("/v1/analysis", json={**request, "release_id": "unknown-release"})
    assert unknown.status_code == 404 and unknown.json()["code"] == "RELEASE_NOT_FOUND"
    missing = client.post("/v1/analysis", json={**request, "metric": "harmonized_hotspot_count", "platforms": None})
    assert missing.status_code == 409 and missing.json()["code"] == "METRIC_NOT_AVAILABLE"
    unsupported = client.post("/v1/analysis", content=b"{}", headers={"content-type": "text/plain"})
    assert unsupported.status_code == 415
    host = client.get("/health/live", headers={"host": "evil.invalid", "origin": "http://localhost:3000"})
    assert host.status_code == 400 and host.headers.get("x-request-id")
    main = importlib.import_module("app.main")
    settings = client.app.state.settings
    storage = settings.storage.model_copy(update={"database_path": tmp_path / "absent.sqlite3"})
    unavailable = settings.model_copy(update={"storage": storage})
    monkeypatch.setattr(main, "load_settings", lambda path: unavailable)
    from fastapi.testclient import TestClient
    with TestClient(main.create_app(tmp_path / "offline-settings.json")) as offline:
        not_ready = offline.get("/health/ready")
    assert not_ready.status_code == 503 and not_ready.json()["code"] == "NOT_READY"
    from starlette.requests import Request
    internal = main.handle_server_error(Request({"type": "http", "state": {"request_id": "safe-id"}}),
                                        RuntimeError("private path"))
    assert internal.status_code == 500 and b"private path" not in internal.body


def test_body_limit_without_content_length():
    import asyncio

    from app.main import RequestGuard
    models = importlib.import_module("app.models")
    settings = models.load_settings(Path(__file__).parents[1] / "config/settings.json").api
    settings = settings.model_copy(update={"request_bytes_limit": 4})

    async def app(scope, receive, send):
        while (await receive()).get("more_body", False):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def call(guard, body, path="/v1/analysis", method="POST"):
        messages = [{"type": "http.request", "body": part, "more_body": index < len(body) - 1}
                    for index, part in enumerate(body)]

        async def receive():
            return messages.pop(0)

        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
                 "query_string": b"", "headers": [(b"content-type", b"application/json")] if method == "POST" else [],
                 "state": {}}
        await guard(scope, receive, send)
        return sent

    async def run():
        guard = RequestGuard(app, settings=settings)
        large = await call(guard, [b"123", b"45"])
        assert large[0]["status"] == 413
        assert b"x-request-id" in dict(large[0]["headers"])
        small_a, small_b = await asyncio.gather(call(guard, [b"123"]), call(guard, [b"1234"]))
        assert small_a[0]["status"] == small_b[0]["status"] == 200
        limited = RequestGuard(app, settings=settings.model_copy(update={"requests_per_minute": 1}))
        await call(limited, [b""], method="GET", path="/health/live")
        blocked = await call(limited, [b""], method="GET", path="/health/live")
        assert blocked[0]["status"] == 429
        assert b"retry-after" in dict(blocked[0]["headers"])

    asyncio.run(run())


def test_cursor_rejects_a_changed_query():
    from datetime import date, datetime, timezone

    from app.main import decode_cursor, encode_cursor
    from app.models import ApiError, CursorPosition, HotspotQuery
    query = HotspotQuery(release_id="release-a", bbox=(106, 10, 107, 11),
        start_date="2024-03-01", end_date="2024-03-02", platforms=("Aqua",), page_size=10)
    position = CursorPosition(observed_at=datetime(2024, 3, 1, tzinfo=timezone.utc), observation_id="source:1")
    secret = b"z" * 32
    token = encode_cursor(position, query, secret=secret)
    assert decode_cursor(token, query, secret=secret) == position
    changed = (
        query.model_copy(update={"bbox": (106.1, 10, 107, 11)}),
        query.model_copy(update={"start_date": date(2024, 3, 2)}),
        query.model_copy(update={"platforms": ("Terra",)}),
        query.model_copy(update={"release_id": "release-b"}),
        query.model_copy(update={"page_size": 11}),
    )
    for request in changed:
        with pytest.raises(ApiError, match="cursor is invalid"):
            decode_cursor(token, request, secret=secret)
    with pytest.raises(ApiError, match="cursor is invalid"):
        decode_cursor("x" * 2049, query, secret=secret)
    with pytest.raises(ApiError, match="cursor is invalid"):
        decode_cursor(token[:-1] + ("A" if token[-1] != "A" else "B"), query, secret=secret)


def test_export_matches_screen(api_client):
    import csv
    import io

    request = _api_request()
    screen_analysis = api_client.post("/v1/analysis", json=request).json()
    analysis_export = api_client.post("/v1/exports", json={
        **request, "kind": "analysis", "format": "json",
    })
    assert analysis_export.status_code == 200
    assert analysis_export.headers["content-type"].startswith("application/json")
    assert "attachment" in analysis_export.headers["content-disposition"]
    exported_analysis = analysis_export.json()
    assert {key: value for key, value in exported_analysis.items() if key != "response_time_ms"} == {
        key: value for key, value in screen_analysis.items() if key != "response_time_ms"
    }
    assert "used_area" in exported_analysis and exported_analysis["used_area"] is None
    point_query = {key: request[key] for key in ("release_id", "bbox", "start_date", "end_date", "platforms")}
    point_query["bbox"] = [-180, 10, 180, 11]
    page = api_client.post("/v1/hotspots/query", json={**point_query, "page_size": 1}).json()
    screen_ids = []
    while True:
        screen_ids.extend(feature["id"] for feature in page["features"])
        if not page["has_more"]:
            break
        page = api_client.post("/v1/hotspots/query", json={
            **point_query, "page_size": 1, "cursor": page["next_cursor"],
        }).json()
    points_export = api_client.post("/v1/exports", json={
        **point_query, "kind": "observations", "format": "csv",
    })
    assert points_export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(points_export.text)))
    assert [row["observation_id"] for row in rows] == screen_ids
    assert rows[0]["confidence"] == "High, fire\nwatch"
    assert rows[1]["confidence"] == "'  =1+1"
    assert float(rows[2]["longitude"]) == -106.23
    assert json.loads(rows[0]["bands"])[0]["band_name"] == "MODIS_31"


def test_export_limit_returns_error_before_download(api_client, monkeypatch):
    main = importlib.import_module("app.main")
    settings = api_client.app.state.settings
    query = {"release_id": "api-fixture-v1", "bbox": [-180, 10, 180, 11],
             "start_date": "2024-03-01", "end_date": "2024-03-02",
             "kind": "observations", "format": "csv", "platforms": ["Aqua"]}
    limits = dict(settings.api.export_limits)
    for name, value in (("maximum_rows", 2), ("maximum_bytes", 1)):
        api = settings.api.model_copy(update={"export_limits": {**limits, name: value}})
        api_client.app.state.settings = settings.model_copy(update={"api": api})
        response = api_client.post("/v1/exports", json=query)
        assert response.status_code == 413
        assert "content-disposition" not in response.headers
        assert "attachment" not in response.text
    elapsed = {"after_read": False}
    read_observations = main.storage.read_observations

    def mark_read(*args, **kwargs):
        result = read_observations(*args, **kwargs)
        elapsed["after_read"] = True
        return result

    monkeypatch.setattr(main.storage, "read_observations", mark_read)
    monkeypatch.setattr(main.time, "perf_counter", lambda: 2.0 if elapsed["after_read"] else 0.0)
    api = settings.api.model_copy(update={"export_limits": {**limits, "maximum_execution_seconds": 1}})
    api_client.app.state.settings = settings.model_copy(update={"api": api})
    response = api_client.post("/v1/exports", json=query)
    assert response.status_code == 413
    assert "content-disposition" not in response.headers
