import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from airchgis.rvt_web import usable_rasters


def tif(path, crs, transform, shape=(50, 50)):
    with rasterio.open(path, "w", driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="float32", crs=crs,
                       transform=transform, nodata=-9999.0) as dst:
        dst.write(np.ones(shape, np.float32), 1)
    return str(path)


class UploadMosaicTests(unittest.TestCase):
    def test_mixed_crs_and_prep_copies_are_left_out(self):
        # the case that raised "array is too big": a tile in degrees next to a smoothed copy in metres
        with tempfile.TemporaryDirectory() as d:
            a = tif(Path(d) / "marche_DTM.tiff", "EPSG:4326", from_origin(13.64, 43.44, 2e-5, 2e-5))
            p = tif(Path(d) / "marche_DTM_prep1.tiff", "EPSG:32633", from_origin(389906, 4810576, 1.94, 1.94))
            u = tif(Path(d) / "other_utm.tiff", "EPSG:32633", from_origin(389906, 4810576, 1.0, 1.0))
            keep, notes, error = usable_rasters([a, p, u])
            self.assertEqual(keep, [a])
            self.assertIsNone(error)
            self.assertTrue(any("prep" in n for n in notes))
            self.assertTrue(any("coordinate system" in n for n in notes))

    def test_size_is_estimated_before_reading(self):
        with tempfile.TemporaryDirectory() as d:
            a = tif(Path(d) / "a.tif", "EPSG:32633", from_origin(300000, 4800000, 0.01, 0.01))
            b = tif(Path(d) / "b.tif", "EPSG:32633", from_origin(700000, 5300000, 0.01, 0.01))
            keep, notes, error = usable_rasters([a, b])
            self.assertIn("too large", error)


if __name__ == "__main__":
    unittest.main()
