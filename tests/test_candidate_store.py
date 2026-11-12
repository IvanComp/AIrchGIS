import json
import tempfile
import unittest
from pathlib import Path

from airchgis import candidate_store


class CandidateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "candidates.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_update_and_export(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[[13.0, 43.0], [13.1, 43.0], [13.1, 43.1], [13.0, 43.0]]],
        }
        saved = candidate_store.save_candidate(
            {
                "title": "Area prova",
                "geometry": geometry,
                "source_record": {"number": "001.001", "source_collection": "CAM-M"},
            },
            self.path,
        )

        self.assertTrue(saved["id"])
        self.assertEqual(saved["status"], "To verify")
        self.assertEqual(len(candidate_store.load_candidates(self.path)), 1)

        updated = candidate_store.update_candidate(
            saved["id"],
            {"status": "Promising", "notes": "Persistente in tre date"},
            self.path,
        )
        self.assertEqual(updated["status"], "Promising")
        self.assertEqual(len(candidate_store.load_candidates(self.path)), 1)

        geojson = json.loads(candidate_store.candidates_geojson([updated]))
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(
            geojson["features"][0]["properties"]["source_number"], "001.001"
        )


if __name__ == "__main__":
    unittest.main()
