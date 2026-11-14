import json
import unittest
from pathlib import Path

from pyproj import Transformer
from shapely import transform
from shapely.geometry import Polygon, box, mapping, shape

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "public/mock/vn-2026-11-14.json"
BOUNDARY = ROOT / "public/data/vietnam-boundary.geojson"


def check_response(test, response, country):
    test.assertEqual(response["country"]["code"], "VN")
    test.assertEqual(response["date"], "2026-11-14")
    test.assertIs(response["is_mock"], True)
    grids = response["detail_grids_info"]
    test.assertEqual(grids["type"], "FeatureCollection")
    ids = set()
    detections = 0
    for feature in grids["features"]:
        test.assertEqual(feature["type"], "Feature")
        test.assertNotIn(feature["id"], ids)
        ids.add(feature["id"])
        test.assertEqual(feature["id"], feature["properties"]["grid_id"])
        geometry = shape(feature["geometry"])
        test.assertIn(geometry.geom_type, {"Polygon", "MultiPolygon"})
        test.assertTrue(geometry.is_valid)
        test.assertGreater(geometry.area, 0)
        test.assertTrue(country.covers(geometry), f"{feature['id']} crosses the border")
        count = feature["properties"]["detection_count"]
        test.assertIs(type(count), int)
        test.assertGreater(count, 0)
        detections += count
    test.assertEqual(response["general_statistics"], {
        "affected_grid_count": len(ids), "detection_count": detections,
    })


class MockDataTests(unittest.TestCase):
    def test_published_mock(self):
        country = shape(json.loads(BOUNDARY.read_text(encoding="utf-8"))["features"][0]["geometry"])
        response = json.loads(MOCK.read_text(encoding="utf-8"))
        check_response(self, response, country)
        self.assertGreater(response["general_statistics"]["affected_grid_count"], 0)
        flags = {f["properties"]["clipped"] for f in response["detail_grids_info"]["features"]}
        self.assertEqual(flags, {False, True})

    def test_grid_dimensions_in_metres(self):
        metadata = json.loads((ROOT / "data/boundary-source.json").read_text(encoding="utf-8"))
        to_grid = Transformer.from_crs("EPSG:4326", metadata["grid_crs"], always_xy=True)
        response = json.loads(MOCK.read_text(encoding="utf-8"))
        for feature in response["detail_grids_info"]["features"]:
            if feature["properties"]["clipped"]:
                continue
            geometry = transform(shape(feature["geometry"]), to_grid.transform, interleaved=False)
            west, south, east, north = geometry.bounds
            self.assertAlmostEqual(east - west, 10000, delta=0.01)
            self.assertAlmostEqual(north - south, 10000, delta=0.01)

    def test_rejects_polygon_stretching_across_a_hole(self):
        country = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)],
                          holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]])
        response = json.loads(MOCK.read_text(encoding="utf-8"))
        feature = response["detail_grids_info"]["features"][0]
        feature["geometry"] = mapping(box(0.5, 0.5, 3.5, 3.5))
        response["detail_grids_info"]["features"] = [feature]
        with self.assertRaisesRegex(AssertionError, "crosses the border"):
            check_response(self, response, country)

    def test_rejects_wrong_totals(self):
        country = shape(json.loads(BOUNDARY.read_text(encoding="utf-8"))["features"][0]["geometry"])
        response = json.loads(MOCK.read_text(encoding="utf-8"))
        response["general_statistics"]["detection_count"] += 1
        with self.assertRaises(AssertionError):
            check_response(self, response, country)
