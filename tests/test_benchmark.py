import unittest

import numpy as np

from airch import benchmark


class LocalMaximaTests(unittest.TestCase):
    def test_peaks_come_out_strongest_first(self):
        array = np.zeros((20, 20))
        array[5, 5] = 1.0
        array[15, 15] = 2.0
        peaks = benchmark.local_maxima(array, 3)
        self.assertEqual(peaks[0][:2], (15, 15))
        self.assertEqual(peaks[1][:2], (5, 5))

    def test_a_broad_bump_is_reported_once(self):
        array = np.zeros((20, 20))
        array[9:12, 9:12] = 1.0
        array[10, 10] = 2.0
        peaks = benchmark.local_maxima(array, 5, limit=10)
        strong = [p for p in peaks if p[2] > 0]
        self.assertEqual(len(strong), 1)

    def test_masked_pixels_never_become_candidates(self):
        array = np.zeros((10, 10))
        array[2, 2] = 5.0
        mask = np.ones((10, 10), dtype=bool)
        mask[2, 2] = False
        peaks = benchmark.local_maxima(array, 2, mask=mask, limit=5)
        self.assertNotIn((2, 2), [p[:2] for p in peaks])

    def test_limit_is_honoured(self):
        array = np.random.default_rng(0).random((40, 40))
        self.assertEqual(len(benchmark.local_maxima(array, 2, limit=7)), 7)


class PrecisionTests(unittest.TestCase):
    def test_a_candidate_within_tolerance_counts_as_a_hit(self):
        peaks = [(10, 10, 1.0), (30, 30, 0.5)]
        self.assertEqual(benchmark.precision_at_k(peaks, [(12, 10)], 3, 2), 0.5)

    def test_no_candidates_has_no_answer(self):
        self.assertIsNone(benchmark.precision_at_k([], [(1, 1)], 3, 5))

    def test_random_baseline_is_the_share_of_area_within_tolerance(self):
        share = benchmark.random_precision_baseline((100, 100), [(50, 50)], 10)
        self.assertAlmostEqual(share, np.pi * 100 / 10000, places=2)

    def test_random_baseline_respects_the_mask(self):
        mask = np.zeros((100, 100), dtype=bool)
        mask[40:60, 40:60] = True
        share = benchmark.random_precision_baseline((100, 100), [(50, 50)], 10, mask=mask)
        self.assertGreater(share, benchmark.random_precision_baseline((100, 100), [(50, 50)], 10))


class EdgeTests(unittest.TestCase):
    def test_candidates_on_a_boundary_are_counted(self):
        edges = np.zeros((10, 10), dtype=bool)
        edges[5, :] = True
        peaks = [(5, 1, 1.0), (0, 0, 0.5)]
        self.assertEqual(benchmark.edge_contamination(peaks, edges, 2), 0.5)

    def test_dilation_widens_the_boundary(self):
        edges = np.zeros((10, 10), dtype=bool)
        edges[5, 5] = True
        peaks = [(5, 6, 1.0)]
        self.assertEqual(benchmark.edge_contamination(peaks, edges, 1), 0.0)
        self.assertEqual(benchmark.edge_contamination(peaks, edges, 1, dilate_px=1), 1.0)


class BoundaryTests(unittest.TestCase):
    def make_stack(self):
        """Two fields with different seasonal behaviour, split down the middle."""
        stack = np.zeros((4, 20, 20))
        stack[:, :, :10] = np.array([0.2, 0.8, 0.7, 0.1]).reshape(4, 1, 1)
        stack[:, :, 10:] = np.array([0.7, 0.2, 0.1, 0.6]).reshape(4, 1, 1)
        return stack

    def test_the_strength_peaks_on_the_boundary(self):
        strength = benchmark.boundary_strength(self.make_stack())
        self.assertGreater(strength[10, 9], strength[10, 4])
        self.assertGreater(strength[10, 10], strength[10, 15])

    def test_uniform_fields_have_no_internal_boundary(self):
        strength = benchmark.boundary_strength(self.make_stack())
        self.assertAlmostEqual(float(strength[10, 4]), 0.0, places=6)

    def test_mask_marks_a_minority_of_pixels(self):
        mask = benchmark.boundary_mask(self.make_stack(), percentile=88)
        self.assertLess(mask.mean(), 0.35)
        self.assertTrue(mask[:, 9].any() or mask[:, 10].any())

    def test_a_two_dimensional_input_is_rejected(self):
        with self.assertRaises(ValueError):
            benchmark.boundary_strength(np.zeros((5, 5)))


class SamplingTests(unittest.TestCase):
    def test_positions_outside_the_raster_are_dropped(self):
        array = np.arange(9, dtype=float).reshape(3, 3)
        self.assertEqual(benchmark.sample_at(array, [(0, 0), (99, 99), (2, 2)]), [0.0, 8.0])

    def test_nan_pixels_are_dropped(self):
        array = np.array([[np.nan, 1.0]])
        self.assertEqual(benchmark.sample_at(array, [(0, 0), (0, 1)]), [1.0])


class SummaryTests(unittest.TestCase):
    def test_missing_values_render_as_not_available(self):
        text = benchmark.summarise({"auc": None, "precision": 0.1, "k": 20, "peaks": 3})
        self.assertIn("n.d.", text)
        self.assertIn("candidati 3", text)


if __name__ == "__main__":
    unittest.main()
