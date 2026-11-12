# AIrch

AIrch (AI + archaeology) is a single web app for preliminary landscape and archaeological prospection. It is built for archaeologists with little IT background and brings the project's tools together in one interface:

- **RVT (LiDAR)**: DTM/DSM exploration with RVT relief visualisations, filters, exports, method grid, reports and the interactive **3D Cloud** viewer;
- **Crop Marks**: multispectral screening for crop marks and soil marks on Sentinel-2 (from 2016) and Landsat (from 1984);
- **Candidates**: a local archive of verification dossiers that link each anomaly to its area, its date ranking and its verification status;
- **GIS tool layer** (`airch/gis/`): QGIS Processing algorithms and ready-made archaeological workflows exposed as tools an AI assistant can call, with a resolvability guardrail and a provenance log that replays as a script;
- **3D export for research** (`airch/terrain/export3d.py`): georeferenced point cloud (LAZ/LAS, PLY), terrain mesh (glTF) and metadata sidecar, from the "Export 3D for research" panel of 3D Cloud.

The catalogue of known sites (CAM-M / Potenza Valley Survey) is kept in `airch/data/` only as an example dataset: users load their own site lists. Scores are investigation priorities, not archaeological probabilities.

## Quick start

```bash
cd "/Users/ivan/Desktop/Neural-Detecting"
./start_airch.command
```

Or manually:

```bash
python -m venv .venv_airch
source .venv_airch/bin/activate
pip install -r requirements.txt
streamlit run airch_app.py
```

## How the Crop Marks engine picks dates

The ranking does not reward the images with the most variance: field boundaries and different crops produce that, not buried structures. Each acquisition is scored on three independent axes.

1. **Local contrast.** For every index the engine measures the deviation from the neighbourhood mean (60 m), the scale of a wall or a ditch rather than of the landscape.
2. **Crop phase.** Mean NDVI and bare-soil fraction classify the scene as *vegetation*, *bare soil* or *mixed*. Crop marks need a growing crop, soil marks a ploughed field: the «Target mark» option decides which dates enter the composite.
3. **Antecedent dryness.** Rainfall in the 30 days before each scene is compared with the 1991-2020 ERA5-Land mean. A mark that does not show after a wet month can show after a dry one, and the ranking takes this into account.

Statistics are computed only on arable land and open areas (ESA WorldCover): a roof edge produces more contrast than any buried structure, and without the mask the score follows the built-up area.

Besides the vegetation deficit and excess maps, the engine produces:

- **Linear marks**, the anomaly weighted by the directional coherence of the local gradient: natural soil variability is isotropic, a wall or a ditch is not;
- **Soil marks**, the brightness and colour contrast of bare soil;
- **Persistence**, how many of the selected dates show the anomaly, and **Multi-year recurrence**, in how many different years it reappears, which is the strongest clue;
- **Check against known sites**: samples the layer at the catalogued sites inside the AOI and at random control points, and reports the AUC. It is a sanity check on a small, non-random sample, not a statistical validation.

## Georeferencing toponyms

The CAM-M PDF publishes no coordinates: it describes places in words. Only 148 of 1,708 records come with a point from the linked sources.

The local gazetteer closes the gap:

```bash
python scripts/build_gazetteer.py
```

The script downloads the GeoNames dump for Italy, keeps the toponyms of the study area and writes `airch/data/gazetteer.json` (GeoNames, CC BY 4.0). `airch/geocoding.py` then matches the locality of each record against the gazetteer, disambiguates homonyms by distance from the municipality centre and discards matches beyond 9 km. About 390 records get a position within a few hundred metres; about 1,100 stay at municipality level.

An inferred coordinate is never presented as published: it carries its own precision label, uncertainty radius and the name it was matched on. The check against known sites uses published coordinates only, because testing the detector on inferred positions would measure the gazetteer.

## Local documentary sources

Authorised local copies of the documents and, optionally, the 53 CAM-M municipal maps can be synchronised into the git-ignored cache:

```bash
python scripts/sync_archaeological_sources.py --maps
```

The manifest `airch/data/source_manifest.json` stores institutional URLs, licences, coverage, sizes and checksums.

MASE and Google Earth are available as external resources in the top bar.

## Bring your own data (upload first)

Every screen starts from the user's own files, from any country, sensor and coordinate system; public archives come second.

- **RVT (LiDAR)**: DTM/DSM as GeoTIFF, ASCII grid or zip, or a LAS/LAZ point cloud (gridded to a DTM from its ground points). Files can be uploaded (up to 4 GB, `.streamlit/config.toml`) or read in place from a local path, with no copy. "Download from a public source" lists national LiDAR portals and downloads Copernicus DEM GLO-30 automatically (no account) or OpenTopography DEMs with the user's API key (stored only in `~/.airch/config.json`). "Example data" is the Abruzzo sample.
- **Crop Marks**: multiband GeoTIFFs (one per date) or one file per band (Sentinel-2 `..._B04.jp2`, Landsat `..._SR_B4.TIF`), with presets for Sentinel-2, Landsat, PlanetScope, drone multispectral and RGB orthophotos, and a band editor. Dates come from file names and can be edited. `airch/spectral/local_engine.py` runs locally (no Earth Engine): indices, local contrast, crop phase and date ranking, per-date anomalies, linear marks, persistence and, with three or more dates, a field-boundary mask. The Earth Engine engine (Sentinel-2, Landsat, rainfall and land-cover weighting) stays under "Download from a public source".
- **Known sites**: the user's own list (CSV with lon/lat or x/y, GeoJSON, GeoPackage, zipped Shapefile, KML) is checked against every layer (AUC vs random controls). The CAM-M/PVS catalogue is only an example dataset.
- The resolvability check uses the pixel size read from the user's file.
- `airch/sources.py` lists the public sources (coverage, resolution, licence, access); `airch/data_input.py` holds the loaders, also registered as tools (`load_raster`, `load_point_cloud`, `load_sites`, `check_raster_resolvability`).

## GIS tool layer

The assistant does not compute results itself: it calls tools.

- `airch/gis/tools.py` is the registry. Each tool has a plain-language description and a JSON schema, so `tool_specs()` can be passed as tool definitions to the Claude API (`tool_specs("openai")` gives the function format of Ollama and OpenAI-compatible servers). Tools: `raster_info`, `hillshade`, `slope`, `sky_view_factor`, `openness`, `local_relief_model`, `clip_raster_to_aoi`, `reproject`, `zonal_stats`, `check_resolvability`, `export_3d`, plus `qgis_list_algorithms` and `qgis_run_algorithm` for any QGIS Processing algorithm.
- `airch/gis/backend.py` finds `qgis_process` (PATH, `/Applications/QGIS*.app`, or `AIRCH_QGIS_PROCESS`). With QGIS installed, hillshade, slope, clip, reproject and zonal statistics run in QGIS Processing; without it every tool falls back to rvt-py/rasterio, and each result says which backend ran.
- `airch/gis/guardrails.py` checks, before any detection, whether a feature of a given width can be resolved by the sensor (Phase 0 model: PSF blur, pixel averaging, measured NDVI noise). On Sentinel-2 a 5 m street is refused (SNR ~1.3), 10 m gets a warning, 20 m passes.
- `airch/gis/provenance.py` records every run (parameters, input SHA-256, outputs, backend, versions, exact `qgis_process` command) and saves it as JSON, a Python replay script and a shell script of QGIS commands.
- `airch/gis/workflows.py`: `lidar_micro_relief` (clip, local relief model, sky-view factor, positive and negative openness, hillshade) and `crop_mark_screening` (resolvability check, then the settings for the Crop Marks engine).

```python
from airch.gis import ProvenanceLog, run_tool
log = ProvenanceLog("My survey")
run_tool("local_relief_model", log=log, input="dtm.tif", output="lrm.tif", radius_m=20, target_feature_width_m=2)
log.save_scripts("outputs/")
```

ArcGIS (`arcpy`) is not supported: it needs a proprietary licence. A backend for it could be added next to `backend.py`.

LAZ compression needs `lazrs` (`pip install lazrs`); without it the point cloud is written as LAS.

## Structure

```text
Neural-Detecting/   (AIrch)
  airch_app.py
  start_airch.command
  airch/
    app.py                    shell and navigation
    ui.py                     theme, animations and logo
    rvt_web.py                RVT (LiDAR) screen, including 3D Cloud and 3D research export
    gis/                      tool registry, QGIS backend, guardrails, provenance, workflows
    terrain/export3d.py       LAZ/LAS, PLY, glTF export with metadata sidecar
    cropmarks_engine.py       collections, masks and anomaly maps
    scene_ranking.py          date ranking, no Earth Engine dependency
    candidate_store.py        verification dossiers
    benchmark.py              metrics against known sites
    site_index.py             known-site catalogue as points
    geocoding.py              toponyms -> coordinates, with explicit uncertainty
    database_enrichment.py    CAM-M / PVS joins
    source_registry.py
    paths.py
    data/                     catalogues, gazetteer, calibration regions
    assets/logo.svg
  RVT/
    core.py                   RVT engine (and the legacy Tk desktop GUI)
    scripts/lads_preview.py   3D Cloud viewer
  Crop marks Tool/            standalone Crop Marks launcher
  paper/                      manuscript (0-MAIN.tex + sections/)
  docs/
  scripts/
  tests/
```

## Standalone Crop Marks

```bash
cd "/Users/ivan/Desktop/Neural-Detecting/Crop marks Tool"
./start_mac.command
```

Details: `Crop marks Tool/README.md`.

## Tests

```bash
python -m unittest tests.test_scene_ranking tests.test_geocoding tests.test_cropmarks_helpers tests.test_candidate_store tests.test_database_enrichment tests.test_benchmark
```

Ranking and georeferencing logic live in pure modules so they can be tested without network access: the tests cover phenological classification, dryness index, date ordering, AUC, homonym disambiguation and georeferencing counts.

## Notes

The `.venv*` folders, RVT outputs, local raster data, generated DTMs and Earth Engine credentials/projects are local and should not be versioned.
