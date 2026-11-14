import functools

import numpy as np
import rvt.vis


APPLIED_FIXES = []


def ensure_runtime():
    original = rvt.vis.hillshade
    if getattr(original, "_airchgis_aligned_gradients", False):
        return

    @functools.wraps(original)
    def aligned_hillshade(dem, resolution_x, resolution_y, sun_azimuth=315, sun_elevation=35, slope=None, aspect=None, ve_factor=1, no_data=None):
        if slope is not None and aspect is not None and np.shape(slope) == np.shape(dem) and np.shape(aspect) == np.shape(dem):
            slope = np.pad(slope, 1, mode="edge")
            aspect = np.pad(aspect, 1, mode="edge")
        return original(dem, resolution_x, resolution_y, sun_azimuth=sun_azimuth, sun_elevation=sun_elevation,
                        slope=slope, aspect=aspect, ve_factor=ve_factor, no_data=no_data)

    aligned_hillshade._airchgis_aligned_gradients = True
    rvt.vis.hillshade = aligned_hillshade
    APPLIED_FIXES.append("Preserve grid dimensions when hillshade receives precomputed slope and aspect.")


def ensure_scaling():
    import rvt.blend_func

    within = rvt.blend_func.scale_within_0_and_1
    strict = rvt.blend_func.scale_strict_0_to_1
    if getattr(within, "_airchgis_array_scaling", False):
        return

    @functools.wraps(within)
    def scale_within(numeric_value):
        value = np.array(numeric_value, dtype=float, copy=True)
        if np.nanmin(value) >= 0 and np.nanmax(value) <= 1:
            return value
        value[np.isnan(value)] = np.nanmin(value)
        low, high = np.min(value), np.max(value)
        if 255 >= high > 1 and high - low > 30 and low > 0:
            return value / 255
        lower, upper = max(0, low), min(1, high)
        if lower == upper:
            return np.zeros_like(value)
        scaled = (value - lower) / (upper - lower)
        if np.nanmin(scaled) > -.01:
            scaled[(scaled < 0) & (scaled > -.01)] = 0
        return scaled

    @functools.wraps(strict)
    def scale_strict(numeric_value):
        value = np.array(numeric_value, dtype=float, copy=True)
        if np.nanmin(value) == 0 and np.nanmax(value) == 1:
            return value
        value[np.isnan(value)] = 0
        low, high = np.min(value), np.max(value)
        if high == low:
            return np.zeros_like(value)
        scaled = (value - low) / (high - low)
        if np.nanmin(scaled) > -.01:
            scaled[(scaled < 0) & (scaled > -.01)] = 0
        return scaled

    scale_within._airchgis_array_scaling = True
    rvt.blend_func.scale_within_0_and_1 = scale_within
    rvt.blend_func.scale_strict_0_to_1 = scale_strict
    APPLIED_FIXES.append("Correct NumPy extrema and elementwise comparisons in the array-scaling helpers; handle constant arrays without division by zero.")


def ensure_tiled_mstp():
    import rvt.default
    import rvt.tile

    original = rvt.tile._create_rvt_visualization_blank_raster
    if getattr(original, "_airchgis_mstp_bands", False):
        return

    @functools.wraps(original)
    def create_blank(rvt_visualization, rvt_default, dem_path, output_dir_path, dem_ds, save_float, save_8bit):
        if rvt_visualization == rvt.default.RVTVisualization.MULTI_SCALE_TOPOGRAPHIC_POSITION and save_float:
            original(rvt_visualization, rvt_default, dem_path, output_dir_path, dem_ds, False, save_8bit)
            path = rvt_default.get_visualization_path(rvt_visualization, dem_path, output_dir_path, False)
            rvt.tile._create_blank_raster(in_data_set=dem_ds, out_raster_path=path, nr_bands=3, e_type=6)
        else:
            original(rvt_visualization, rvt_default, dem_path, output_dir_path, dem_ds, save_float, save_8bit)

    create_blank._airchgis_mstp_bands = True
    rvt.tile._create_rvt_visualization_blank_raster = create_blank
    APPLIED_FIXES.append("Allocate three float bands for tiled MSTP output, matching its RGB result.")
