import unittest

from airch import geocoding


def gazetteer():
    return geocoding.Gazetteer(
        {
            "places": [
                {"name": "Frontale", "keys": ["frontale"], "lat": 43.42, "lon": 13.09},
                {"name": "Frontale", "keys": ["frontale"], "lat": 43.10, "lon": 13.60},
                {"name": "Villanova", "keys": ["villanova"], "lat": 43.40, "lon": 13.05},
                {"name": "Pievefavera", "keys": ["pievefavera"], "lat": 43.15, "lon": 13.24},
            ],
            "municipalities": {
                "Apiro": {"lat": 43.39, "lon": 13.13},
                "Caldarola": {"lat": 43.14, "lon": 13.22},
            },
        }
    )


class NormaliseTests(unittest.TestCase):
    def test_accents_case_and_punctuation_are_folded(self):
        self.assertEqual(geocoding.normalise("Località Sant'Angelo"), "localita sant angelo")

    def test_empty_values_are_safe(self):
        self.assertEqual(geocoding.normalise(None), "")


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.gazetteer = gazetteer()

    def test_exact_toponym_returns_all_homonyms(self):
        self.assertEqual(len(self.gazetteer.candidates("Frontale")), 2)

    def test_a_contained_name_is_found_inside_a_longer_description(self):
        found = self.gazetteer.candidates("Villanova di Frontale")
        self.assertTrue(found)
        self.assertEqual(found[0]["name"], "Villanova")

    def test_unknown_toponym_returns_nothing(self):
        self.assertEqual(self.gazetteer.candidates("Piano della Casa"), [])


class GeocodeTests(unittest.TestCase):
    def setUp(self):
        self.gazetteer = gazetteer()

    def test_homonyms_are_resolved_by_the_municipality_anchor(self):
        result = geocoding.geocode_record(
            {"comune": "Apiro", "localita": "Frontale"}, self.gazetteer
        )
        self.assertEqual(result["coordinate_method"], "toponimo")
        self.assertAlmostEqual(result["lat"], 43.42)

    def test_a_toponym_too_far_from_the_municipality_is_rejected(self):
        result = geocoding.geocode_record(
            {"comune": "Caldarola", "localita": "Villanova"}, self.gazetteer
        )
        self.assertEqual(result["coordinate_method"], "comune")

    def test_records_without_a_known_toponym_fall_back_to_the_municipality(self):
        result = geocoding.geocode_record(
            {"comune": "Caldarola", "localita": "Fondo Ciampichetti"}, self.gazetteer
        )
        self.assertEqual(result["coordinate_method"], "comune")
        self.assertEqual(result["coordinate_uncertainty_m"], geocoding.UNCERTAINTY_MUNICIPALITY_M)

    def test_the_municipality_fallback_can_be_switched_off(self):
        result = geocoding.geocode_record(
            {"comune": "Caldarola", "localita": "Fondo Ciampichetti"},
            self.gazetteer,
            allow_municipality=False,
        )
        self.assertIsNone(result)

    def test_published_coordinates_are_never_overwritten(self):
        self.assertIsNone(
            geocoding.geocode_record(
                {"comune": "Apiro", "localita": "Frontale", "lat": 1.0, "lon": 2.0}, self.gazetteer
            )
        )

    def test_unknown_municipality_and_toponym_yields_nothing(self):
        self.assertIsNone(
            geocoding.geocode_record({"comune": "Roma", "localita": "Ostiense"}, self.gazetteer)
        )


class ApplyTests(unittest.TestCase):
    def test_counts_and_labels_reflect_how_each_point_was_obtained(self):
        records = [
            {"number": "1", "comune": "Apiro", "localita": "Frontale", "coordinate_precision": "buona"},
            {"number": "2", "comune": "Caldarola", "localita": "Ignota", "coordinate_precision": "mediocre"},
            {"number": "3", "comune": "Apiro", "localita": "x", "lat": 43.0, "lon": 13.0},
            {"number": "4", "comune": "Roma", "localita": "Ostiense"},
        ]
        stats = geocoding.apply_geocoding(records, gazetteer())
        self.assertEqual(
            stats, {"published": 1, "toponym": 1, "municipality": 1, "unresolved": 1}
        )
        self.assertEqual(records[0]["coordinate_precision"], geocoding.PRECISION_TOPONYM)
        self.assertEqual(records[0]["catalog_precision"], "buona")
        self.assertTrue(geocoding.is_derived(records[1]))
        self.assertFalse(geocoding.is_derived(records[2]))

    def test_without_a_gazetteer_nothing_is_invented(self):
        records = [{"number": "1", "comune": "Apiro", "localita": "Frontale"}]
        stats = geocoding.apply_geocoding(records, None)
        self.assertEqual(stats["unresolved"], 1)
        self.assertIsNone(records[0].get("lat"))


if __name__ == "__main__":
    unittest.main()
