import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preprocess_firms import build_database


def test_focused_area_pages_and_daily_summaries(tmp_path, monkeypatch):
    source = tmp_path / "hotspots.csv"
    source.write_text("latitude,longitude,acq_date\n21,105.8,2024-01-01\n-23.5,-46.6,2024-01-01\n-30,-70,2024-01-01\n21,105.8,2024-01-03\n")
    release = tmp_path / "release"
    result = build_database([source], release)
    source_settings = Path(__file__).parents[1] / "config/settings.json"
    data = json.loads(source_settings.read_text())
    data["storage"]["data_format"] = "sqlite"
    data["storage"]["global_release_path"] = str(release)
    data["storage"]["world_areas_path"] = "config"
    data["api"]["allowed_hosts"] = ["testserver", "localhost", "127.0.0.1"]
    settings = tmp_path / "settings.json"; settings.write_text(json.dumps(data))
    monkeypatch.setenv("CURSOR_SECRET", "area-query-test-secret-0123456789")
    from app.main import create_app
    with TestClient(create_app(settings)) as client:
        body = {"release_id": result["release_id"], "area_name": "South America", "date": "2024-01-01", "page_size": 1}
        first = client.post("/v2/hotspots/query", json=body)
        assert first.status_code == 200 and first.json()["active_cell_count"] == 2
        assert first.json()["returned_count"] == 1 and first.json()["has_more"]
        second = client.post("/v2/hotspots/query", json={**body, "cursor": first.json()["next_cursor"]})
        assert second.status_code == 200 and second.json()["returned_count"] == 1
        assert first.json()["features"][0]["id"] != second.json()["features"][0]["id"]
        summary = client.post("/v2/hotspots/summaries/query", json={
            "release_id": result["release_id"], "area_name": "việt nam",
            "start_date": "2024-01-01", "end_date": "2024-01-04"})
        assert summary.status_code == 200
        assert [day["active_cell_count"] for day in summary.json()["days"]] == [1, 0, 1]
        assert summary.json()["days"][1]["input_state"] == "no_records"
        unknown = client.post("/v2/hotspots/query", json={**body, "area_name": "Egypt"})
        assert unknown.status_code == 404 and unknown.json()["code"] == "AREA_NOT_FOUND"
        bad_cursor = client.post("/v2/hotspots/query", json={**body, "cursor": first.json()["next_cursor"], "date": "2024-01-02"})
        assert bad_cursor.status_code == 422 and bad_cursor.json()["code"] == "INVALID_CURSOR"
