import unittest

from archaeoscope import scene_ranking as ranking


def scene(**overrides):
    base = {
        "scene_id": "a",
        "date": "2024-04-01",
        "valid_pixels": 1000,
        "ndvi_mean": 0.6,
        "bare_fraction": 0.05,
        "NDVI_contrast": 0.045,
        "SAVI_contrast": 0.045,
    }
    base.update(overrides)
    return base


class PhenologyTests(unittest.TestCase):
    def test_bare_field_is_a_soil_mark_scene(self):
        self.assertEqual(ranking.phenology_class(0.15, 0.2), ranking.PHENOLOGY_SOIL)
        self.assertEqual(ranking.phenology_class(0.5, 0.7), ranking.PHENOLOGY_SOIL)

    def test_closed_canopy_is_a_crop_mark_scene(self):
        self.assertEqual(ranking.phenology_class(0.62, 0.02), ranking.PHENOLOGY_CANOPY)

    def test_partial_cover_stays_mixed(self):
        self.assertEqual(ranking.phenology_class(0.35, 0.1), ranking.PHENOLOGY_MIXED)


class DrynessTests(unittest.TestCase):
    def test_no_rain_at_all_is_full_drought(self):
        self.assertEqual(ranking.dryness_index(0, 90), 1.0)

    def test_wetter_than_normal_is_not_negative(self):
        self.assertEqual(ranking.dryness_index(180, 90), 0.0)

    def test_half_the_normal_rain_is_half_dry(self):
        self.assertAlmostEqual(ranking.dryness_index(45, 90), 0.5)

    def test_missing_climatology_is_neutral(self):
        self.assertEqual(ranking.dryness_index(30, None), 0.0)


class ContrastTests(unittest.TestCase):
    def test_contrast_is_normalised_per_index(self):
        weak = ranking.contrast_score({"NDVI_contrast": 0.005})
        strong = ranking.contrast_score({"NDVI_contrast": 0.09})
        self.assertLess(weak, strong)

    def test_a_single_extreme_index_cannot_saturate_the_score(self):
        clamped = ranking.contrast_score({"NDVI_contrast": 100.0})
        self.assertLessEqual(clamped, 3.0)


class RankingTests(unittest.TestCase):
    def test_crop_mark_target_demotes_bare_soil_scenes(self):
        scenes = [
            scene(scene_id="bare", ndvi_mean=0.1, bare_fraction=0.9),
            scene(scene_id="green", ndvi_mean=0.65, bare_fraction=0.02),
        ]
        ranked = ranking.rank_scenes(scenes, target="Crop marks (vegetazione)")
        self.assertEqual(ranked[0]["scene_id"], "green")

    def test_soil_mark_target_promotes_bare_soil_scenes(self):
        scenes = [
            scene(scene_id="bare", ndvi_mean=0.1, bare_fraction=0.9),
            scene(scene_id="green", ndvi_mean=0.65, bare_fraction=0.02),
        ]
        ranked = ranking.rank_scenes(scenes, target="Soil marks (suolo nudo)")
        self.assertEqual(ranked[0]["scene_id"], "bare")

    def test_a_dry_month_outranks_an_equal_but_wet_scene(self):
        scenes = [
            scene(scene_id="wet", rain_30d_mm=120, rain_30d_normal_mm=90),
            scene(scene_id="dry", rain_30d_mm=10, rain_30d_normal_mm=90),
        ]
        ranked = ranking.rank_scenes(scenes)
        self.assertEqual(ranked[0]["scene_id"], "dry")

    def test_a_scene_that_sees_a_sliver_of_the_area_is_rejected(self):
        scenes = [
            scene(scene_id="full", valid_pixels=1000),
            scene(scene_id="sliver", valid_pixels=50),
        ]
        ranked = ranking.rank_scenes(scenes)
        self.assertEqual(ranked[0]["scene_id"], "full")
        rejected = next(item for item in ranked if item["scene_id"] == "sliver")
        self.assertEqual(rejected["score"], 0.0)
        self.assertAlmostEqual(rejected["coverage"], 0.05)

    def test_coverage_is_a_filter_not_a_discount(self):
        scenes = [
            scene(scene_id="full", valid_pixels=1000, NDVI_contrast=0.01),
            scene(scene_id="sliver", valid_pixels=800, NDVI_contrast=0.20),
        ]
        ranked = ranking.rank_scenes(scenes, min_coverage=0.9)
        # The sliver has by far the strongest contrast and still must not win:
        # its statistics describe a different piece of ground.
        self.assertEqual(ranked[0]["scene_id"], "full")
        selected = ranking.select_for_composite(ranked, 5)
        self.assertEqual([s["scene_id"] for s in selected if s["selected_for_composite"]], ["full"])

    def test_ranking_does_not_mutate_the_input(self):
        scenes = [scene()]
        ranking.rank_scenes(scenes)
        self.assertNotIn("score", scenes[0])


class SelectionTests(unittest.TestCase):
    def test_only_the_requested_number_of_dates_is_flagged(self):
        scenes = [scene(scene_id=str(i), date=f"2024-04-0{i}") for i in range(1, 6)]
        selected = ranking.select_for_composite(scenes, 2)
        self.assertEqual(sum(item["selected_for_composite"] for item in selected), 2)

    def test_two_granules_of_the_same_day_count_once(self):
        scenes = [
            scene(scene_id="a", date="2024-04-01"),
            scene(scene_id="b", date="2024-04-01"),
            scene(scene_id="c", date="2024-04-02"),
        ]
        selected = ranking.select_for_composite(scenes, 2)
        chosen = [item["scene_id"] for item in selected if item["selected_for_composite"]]
        self.assertEqual(chosen, ["a", "c"])


class ValidationMathTests(unittest.TestCase):
    def test_perfect_separation_scores_one(self):
        self.assertEqual(ranking.roc_auc([3, 4, 5], [0, 1, 2]), 1.0)

    def test_identical_distributions_score_one_half(self):
        self.assertEqual(ranking.roc_auc([1, 2], [1, 2]), 0.5)

    def test_empty_sample_has_no_answer(self):
        self.assertIsNone(ranking.roc_auc([], [1, 2]))

    def test_percentile_bucket_reports_the_highest_threshold_reached(self):
        percentiles = {50: 0.1, 75: 0.3, 90: 0.6, 99: 0.95}
        self.assertEqual(ranking.percentile_bucket(0.7, percentiles), 90)
        self.assertEqual(ranking.percentile_bucket(0.05, percentiles), 0)


if __name__ == "__main__":
    unittest.main()
