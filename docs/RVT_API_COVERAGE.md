# RVT public API coverage

Upstream: [EarthObservation/RVT_py](https://github.com/EarthObservation/RVT_py/tree/bab109c409fedf77ccec7de5fd84c48b791df3d2).

Pinned commit: `bab109c409fedf77ccec7de5fd84c48b791df3d2`. Package version: 2.2.3.

The docked map workspace exposes all **148 public operations** declared in the five runtime modules below. Constructors and public methods count as operations; private helpers, imported dependencies, test scripts, packaging files and notebook user interfaces do not. All 468 parameters are included in the operation forms. This is coverage of this pinned API, not a guarantee for future versions or every possible parameter combination.

The integration test executes every listed operation on a synthetic 64 × 64 georeferenced terrain. Separate checks cover preset compositions, grid alignment, result reuse, exports, imports, batch processing and library compatibility corrections. The complete machine-readable parameter catalogue is [RVT_API_COVERAGE.json](RVT_API_COVERAGE.json).

| Module | Operations |
|---|---:|
| `rvt.vis` | 21 |
| `rvt.blend` | 37 |
| `rvt.blend_func` | 28 |
| `rvt.default` | 60 |
| `rvt.tile` | 2 |

## Using the workspace

Upload terrain, then open **Visualization tools → Open RVT workspace**. The map stays visible beside the tools. Live preview automatically reruns supported spatial calculations after parameter changes, using the loaded terrain grid. A single temporary output is replaced; Keep result retains outputs in the session. File and object mutations require an explicit Run operation.

Operations include all visualizations, normalization and blending helpers, object constructors, file operations and tiled processing. Required fields have an asterisk. Choose Automatic, Library default, Custom value, None, or any stored input/result. Structured values accept JSON and nested references such as `{"$ref":"settings"}`. A selected mapping or multiband array also supports a member key or band index (zero based).

Use Settings to edit public fields on default, terrain and composition objects. Use Compositions for VAT, Combined VAT, Prismatic openness and City, including terrain profiles. For custom blends create a BlenderCombination, add layers, then render. Inputs & results imports configuration/raster/array files and downloads results or a session package. Batch applies the selected operation to raster files; the two tile operations handle block processing.

Arrays with the same grid as the loaded terrain can be shown on the map as a band or RGB. Applying a result replaces the current relief view. Other grids remain available for analysis and download. GeoTIFF exports preserve their input grid; helper arrays without a matching raster shape use NPY or CSV. Session packages include managed files, arrays, object fields, grid metadata and operation history; they are archives, not an automatic session-restoration format. Processing is synchronous and uses local memory unless a tiled operation is chosen.

## Local compatibility corrections

`airchgis/rvt_runtime.py` preserves public signatures and applies these corrections to the pinned library:

- Hillshade with precomputed slope/aspect retains the terrain dimensions, including multihillshade results.
- Array scaling uses valid NumPy extrema, elementwise comparisons and defined handling of constant inputs.
- Tiled MSTP allocates three floating-point bands for its RGB output.

These corrections are tested explicitly and are local to AIrchGIS; they are not claimed as upstream changes.

## Operation inventory

### rvt.vis

| Operation | Parameters |
|---|---|
| `vis.byte_scale` | `data` *, `c_min`, `c_max`, `high`, `low`, `no_data` |
| `vis.slope_aspect` | `dem` *, `resolution_x`, `resolution_y`, `output_units`, `ve_factor`, `no_data` |
| `vis.roll_fill_nans` | `dem` *, `shift` *, `axis` * |
| `vis.hillshade` | `dem` *, `resolution_x` *, `resolution_y` *, `sun_azimuth`, `sun_elevation`, `slope`, `aspect`, `ve_factor`, `no_data` |
| `vis.multi_hillshade` | `dem` *, `resolution_x` *, `resolution_y` *, `nr_directions`, `sun_elevation`, `slope`, `aspect`, `ve_factor`, `no_data` |
| `vis.mean_filter` | `dem` *, `kernel_radius` * |
| `vis.slrm` | `dem` *, `radius_cell`, `ve_factor`, `no_data` |
| `vis.horizon_shift_vector` | `num_directions`, `radius_pixels`, `min_radius` |
| `vis.sky_view_factor_compute` | `height_arr` *, `radius_max`, `radius_min`, `num_directions`, `compute_svf`, `compute_opns`, `compute_asvf`, `a_main_direction`, `a_poly_level`, `a_min_weight` |
| `vis.sky_view_factor` | `dem` *, `resolution` *, `compute_svf`, `compute_opns`, `compute_asvf`, `svf_n_dir`, `svf_r_max`, `svf_noise`, `asvf_dir`, `asvf_level`, `ve_factor`, `no_data` |
| `vis.local_dominance` | `dem` *, `min_rad`, `max_rad`, `rad_inc`, `angular_res`, `observer_height`, `ve_factor`, `no_data` |
| `vis.horizon_generate_coarse_dem` | `dem_fine` *, `pyramid_scale` *, `conv_from` *, `conv_to` *, `max_radius` * |
| `vis.horizon_generate_pyramids` | `dem` *, `num_directions`, `max_fine_radius`, `max_pyramid_radius`, `pyramid_scale` |
| `vis.sky_illumination` | `dem` *, `resolution` *, `sky_model`, `compute_shadow`, `shadow_horizon_only`, `max_fine_radius`, `num_directions`, `shadow_az`, `shadow_el`, `ve_factor`, `no_data` |
| `vis.shadow_horizon` | `dem` *, `resolution` *, `shadow_az`, `shadow_el`, `ve_factor`, `no_data` |
| `vis.msrm` | `dem` *, `resolution` *, `feature_min` *, `feature_max` *, `scaling_factor` *, `ve_factor`, `no_data` |
| `vis.integral_image` | `dem` *, `data_type` |
| `vis.topographic_dev` | `dem` *, `dem_i_nr_pixels` *, `dem_i1` *, `dem_i2` *, `kernel_radius` * |
| `vis.max_elevation_deviation` | `dem` *, `minimum_radius` *, `maximum_radius` *, `step` * |
| `vis.mstp` | `dem` *, `local_scale`, `meso_scale`, `broad_scale`, `lightness`, `ve_factor`, `no_data` |
| `vis.fill_where_nan` | `dem` *, `method` |

### rvt.blend

| Operation | Parameters |
|---|---|
| `blend.create_blender_file_example` | `file_path` |
| `blend.BlenderLayer` | `vis_method`, `normalization`, `minimum`, `maximum`, `blend_mode`, `opacity`, `colormap`, `min_colormap_cut`, `max_colormap_cut`, `image`, `image_path` |
| `blend.BlenderLayer.check_data` | — |
| `blend.BlenderCombination` | `dem_arr`, `dem_resolution`, `dem_path` |
| `blend.BlenderCombination.add_dem_arr` | `dem_arr` *, `dem_resolution` * |
| `blend.BlenderCombination.add_dem_path` | `dem_path` * |
| `blend.BlenderCombination.create_layer` | `vis_method`, `normalization`, `minimum`, `maximum`, `blend_mode`, `opacity`, `colormap`, `min_colormap_cut`, `max_colormap_cut`, `image`, `image_path` |
| `blend.BlenderCombination.add_layer` | `layer` * |
| `blend.BlenderCombination.remove_all_layers` | — |
| `blend.BlenderCombination.layers_info` | — |
| `blend.BlenderCombination.read_from_file` | `file_path` * |
| `blend.BlenderCombination.read_from_json` | `json_data` * |
| `blend.BlenderCombination.save_to_file` | `file_path` * |
| `blend.BlenderCombination.to_json` | — |
| `blend.BlenderCombination.check_data` | — |
| `blend.BlenderCombination.render_all_images` | `default`, `save_visualizations`, `save_render_path`, `save_float`, `save_8bit`, `no_data` |
| `blend.BlenderCombination.create_log_file` | `dem_path` *, `combination_name` *, `render_path` *, `default` *, `terrain_sett_name`, `custom_dir`, `computation_time` |
| `blend.compare_2_combinations` | `combination1` *, `combination2` * |
| `blend.BlenderCombinations` | — |
| `blend.BlenderCombinations.add_combination` | `combination` *, `name` |
| `blend.BlenderCombinations.remove_all_combinations` | — |
| `blend.BlenderCombinations.select_combination_by_name` | `name` * |
| `blend.BlenderCombinations.remove_combination_by_name` | `name` * |
| `blend.BlenderCombinations.read_from_file` | `file_path` * |
| `blend.BlenderCombinations.save_to_file` | `file_path` * |
| `blend.BlenderCombinations.combination_in_combinations` | `input_combination` * |
| `blend.BlenderCombinations.combinations_names` | — |
| `blend.TerrainSettings` | — |
| `blend.TerrainSettings.read_from_file` | `file_path` * |
| `blend.TerrainSettings.read_from_json` | `json_data` * |
| `blend.TerrainSettings.apply_terrain` | `default` *, `combination` * |
| `blend.TerrainsSettings` | — |
| `blend.TerrainsSettings.read_from_file` | `file_path` * |
| `blend.TerrainsSettings.select_terrain_settings_by_name` | `name` * |
| `blend.color_relief_image_map` | `dem` *, `resolution` *, `default`, `colormap`, `min_colormap_cut`, `max_colormap_cut`, `no_data` |
| `blend.e3mstp` | `dem` *, `resolution` *, `default`, `no_data` |
| `blend.e4mstp` | `dem` *, `resolution` *, `default`, `no_data` |

### rvt.blend_func

| Operation | Parameters |
|---|---|
| `blend_func.gray_scale_to_color_ramp` | `gray_scale` *, `colormap` *, `min_colormap_cut`, `max_colormap_cut`, `alpha`, `output_8bit` |
| `blend_func.truncate_colormap` | `cmap` *, `minval`, `maxval`, `n` |
| `blend_func.normalize_lin` | `image` *, `minimum` *, `maximum` * |
| `blend_func.lin_cutoff_calc_from_perc` | `image` *, `minimum` *, `maximum` * |
| `blend_func.normalize_perc` | `image` *, `minimum` *, `maximum` * |
| `blend_func.advanced_normalization` | `image` *, `minimum` *, `maximum` *, `normalization` * |
| `blend_func.lum` | `img` * |
| `blend_func.matrix_eq_min_lt_zero` | `r` *, `idx_min_lt_zero` *, `lum_c` *, `min_c` * |
| `blend_func.matrix_eq_max_gt_one` | `r` *, `idx_max_c_gt_one` *, `lum_c` *, `max_c` * |
| `blend_func.channel_min` | `r` *, `g` *, `b` * |
| `blend_func.channel_max` | `r` *, `g` *, `b` * |
| `blend_func.clip_color` | `c` *, `min_c`, `max_c` |
| `blend_func.blend_normal` | `active` *, `background` * |
| `blend_func.blend_screen` | `active` *, `background` * |
| `blend_func.blend_multiply` | `active` *, `background` * |
| `blend_func.blend_overlay` | `active` *, `background` * |
| `blend_func.blend_soft_light` | `active` *, `background` * |
| `blend_func.blend_luminosity` | `active` *, `background` *, `min_c`, `max_c` |
| `blend_func.equation_blend` | `blend_mode` *, `active` *, `background` * |
| `blend_func.blend_multi_dim_images` | `blend_mode` *, `active` *, `background` * |
| `blend_func.blend_images` | `blend_mode` *, `active` *, `background` *, `min_c`, `max_c` |
| `blend_func.render_images` | `active` *, `background` *, `opacity` * |
| `blend_func.scale_within_0_and_1` | `numeric_value` * |
| `blend_func.scale_strict_0_to_1` | `numeric_value` * |
| `blend_func.scale_0_to_1` | `numeric_value` * |
| `blend_func.apply_opacity` | `active` *, `background` *, `opacity` * |
| `blend_func.normalize_image` | `visualization` *, `image` *, `min_norm` *, `max_norm` *, `normalization` * |
| `blend_func.cut_off_normalize` | `image` *, `mode` *, `cutoff_min`, `cutoff_max`, `bool_norm` |

### rvt.default

| Operation | Parameters |
|---|---|
| `default.RVTVisualization` | `value` * |
| `default.DefaultValues` | — |
| `default.DefaultValues.save_default_to_file` | `file_path` |
| `default.DefaultValues.read_default_from_file` | `file_path` * |
| `default.DefaultValues.get_shadow_file_name` | `dem_path` * |
| `default.DefaultValues.get_shadow_path` | `dem_path` * |
| `default.DefaultValues.get_hillshade_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_hillshade_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_slope_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_slope_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_multi_hillshade_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_multi_hillshade_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_slrm_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_slrm_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_svf_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_svf_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_asvf_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_asvf_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_opns_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_opns_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_neg_opns_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_neg_opns_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_sky_illumination_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_sky_illumination_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_local_dominance_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_local_dominance_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_msrm_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_msrm_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_mstp_file_name` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_mstp_path` | `dem_path` *, `bit8` |
| `default.DefaultValues.get_visualization_file_name` | `rvt_visualization` *, `dem_path` *, `path_8bit` * |
| `default.DefaultValues.get_visualization_path` | `rvt_visualization` *, `dem_path` *, `output_dir_path` *, `path_8bit` * |
| `default.DefaultValues.float_to_8bit` | `float_arr` *, `visualization` *, `x_res`, `y_res`, `no_data` |
| `default.DefaultValues.get_slope` | `dem_arr` *, `resolution_x` *, `resolution_y` *, `no_data` |
| `default.DefaultValues.save_slope` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_shadow` | `dem_arr` *, `resolution` *, `no_data` |
| `default.DefaultValues.get_hillshade` | `dem_arr` *, `resolution_x` *, `resolution_y` *, `no_data` |
| `default.DefaultValues.save_hillshade` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit`, `save_shadow` |
| `default.DefaultValues.get_multi_hillshade` | `dem_arr` *, `resolution_x` *, `resolution_y` *, `no_data` |
| `default.DefaultValues.save_multi_hillshade` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_slrm` | `dem_arr` *, `no_data` |
| `default.DefaultValues.save_slrm` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_sky_view_factor` | `dem_arr` *, `resolution` *, `compute_svf`, `compute_asvf`, `compute_opns`, `no_data` |
| `default.DefaultValues.save_sky_view_factor` | `dem_path` *, `save_svf`, `save_asvf`, `save_opns`, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_neg_opns` | `dem_arr` *, `resolution` *, `no_data` |
| `default.DefaultValues.save_neg_opns` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_sky_illumination` | `dem_arr` *, `resolution` *, `no_data` |
| `default.DefaultValues.save_sky_illumination` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_local_dominance` | `dem_arr` *, `no_data` |
| `default.DefaultValues.save_local_dominance` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_msrm` | `dem_arr` *, `resolution` *, `no_data` |
| `default.DefaultValues.save_msrm` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.get_mstp` | `dem_arr` *, `no_data` |
| `default.DefaultValues.save_mstp` | `dem_path` *, `custom_dir`, `save_float`, `save_8bit` |
| `default.DefaultValues.save_visualizations` | `dem_path` *, `custom_dir` |
| `default.DefaultValues.calculate_visualization` | `visualization` *, `dem` *, `resolution_x` *, `resolution_y` *, `no_data`, `save_float`, `save_8bit` |
| `default.DefaultValues.create_log_file` | `dem_path` *, `custom_dir`, `compute_time` |
| `default.get_raster_arr` | `raster_path` * |
| `default.get_raster_size` | `raster_path` *, `band` |
| `default.save_raster` | `src_raster_path` *, `out_raster_path` *, `out_raster_arr` *, `no_data`, `e_type` |

### rvt.tile

| Operation | Parameters |
|---|---|
| `tile.save_visualization_tile_by_tile` | `visualization_function` *, `function_parameters` *, `dem_path` *, `overlap` *, `tile_size_x` *, `tile_size_y` *, `out_raster_path` *, `out_raster_nr_of_bands`, `out_raster_e_type`, `out_visualization_dict_key` |
| `tile.save_rvt_visualization_tile_by_tile` | `rvt_visualization` *, `rvt_default` *, `dem_path` *, `output_dir_path`, `save_float`, `save_8bit` |
