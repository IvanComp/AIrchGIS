import json
import unittest
from pathlib import Path

from airch import source_registry
from airch.database_enrichment import enrich_database, pvs_2006_reference_ids


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DatabaseEnrichmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = json.loads(
            (PROJECT_ROOT / "airch/data/cam_m_sites.json").read_text(encoding="utf-8")
        )
        cls.enriched = enrich_database(cls.database)

    def test_explicit_citation_parser_ignores_unrelated_bibliography(self):
        bibliography = (
            "Autore 1999, scheda 77; Percossi, Pignocchi, Vermeulen 2006, p. 148, scheda 58; "
            "Vermeulen et al. 2017, p. 20."
        )
        self.assertEqual(pvs_2006_reference_ids(bibliography), ["058"])

    def test_confident_join_moves_coordinate_to_cam_and_deduplicates_pvs(self):
        cam = next(record for record in self.enriched["records"] if record["number"] == "039.024")
        self.assertAlmostEqual(cam["lat"], 43.1795075)
        self.assertIn("PVS 2006, record 059", cam["coordinate_source"])
        self.assertIn("UTM EPSG:32633", cam["coordinate_source"])
        self.assertFalse(any(record["number"] == "PVS.059" for record in self.enriched["records"]))

    def test_2017_coordinates_and_anomaly_flag_are_integrated(self):
        pitino = next(record for record in self.enriched["records"] if record["number"] == "047.044")
        self.assertAlmostEqual(pitino["lat"], 43.280212)
        self.assertAlmostEqual(pitino["lon"], 13.237912)
        self.assertIn("pvs_2017", pitino["source_document_keys"])
        self.assertTrue(pitino["validation_flags"])

    def test_out_of_scope_pvs_context_is_preserved(self):
        loreto = next(record for record in self.enriched["records"] if record["number"] == "PVS.215")
        self.assertEqual(loreto["comune"], "Loreto")
        self.assertEqual(loreto["source_collection"], "PVS 2017")

    def test_enrichment_counts_are_stable(self):
        metadata = self.enriched["metadata"]["enrichment"]
        self.assertEqual(metadata["citation_links_accepted"], 99)
        self.assertEqual(metadata["citation_links_for_review"], 20)
        self.assertEqual(metadata["pvs_duplicate_rows_removed"], 66)
        self.assertEqual(self.enriched["stats"]["with_coordinates"], 148)

    def test_source_manifest_has_portable_cache_names(self):
        manifest = source_registry.load_manifest()
        self.assertEqual(len(manifest["documents"]), 3)
        for document in manifest["documents"]:
            self.assertFalse(Path(document["local_name"]).is_absolute())
            self.assertTrue(document["landing_url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
