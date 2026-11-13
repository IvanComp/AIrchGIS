<p align="center">
  <img src="docs/assets/airchgis-logo.svg" alt="AIrchGIS" width="620">
</p>

<p align="center"><b>An AI-assisted archaeological GIS for LiDAR and multispectral prospection, on your own data, anywhere in the world.</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Streamlit-1.58-FF4B4B?logo=streamlit&logoColor=white" alt="Streamlit 1.58">
  <img src="https://img.shields.io/badge/QGIS-optional%20backend-589632?logo=qgis&logoColor=white" alt="QGIS optional backend">
  <img src="https://img.shields.io/badge/LiDAR-RVT%20%C2%B7%20LAS%2FLAZ-8a6d3b" alt="LiDAR">
  <img src="https://img.shields.io/badge/3D%20export-LAZ%20%C2%B7%20PLY%20%C2%B7%20glTF-c99a26" alt="3D export">
  <img src="https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-555" alt="Platforms">
  <img src="https://img.shields.io/badge/status-paper%20in%20preparation%20(DAACH)-orange" alt="Paper in preparation">
</p>

AIrchGIS brings LiDAR relief visualization, 3D terrain exploration and multi-date screening for crop and soil marks into one browser app, built for archaeologists with little IT background. You start from your own files (any country, sensor or coordinate system); public archives are an optional download. AI helps you see your data better: it cleans terrain and images, ranks relief views by how clearly they show features of your size, and blends the best ones. Every step shows what it changed, keeps your original and is saved as a re-runnable script. A resolution check tells you when the data cannot show what you are looking for.

<p align="center">
  <img src="docs/assets/screenshot-terrain.jpg" alt="AIrchGIS terrain screen: LiDAR hillshade over satellite imagery" width="900">
</p>

# Table of contents

- [What it does](#what-it-does)
- [Bring your own data](#bring-your-own-data)
- [Enhance & best view](#enhance--best-view)
- [Scripts and provenance](#scripts-and-provenance)
- [3D export for research](#3d-export-for-research)
- [Quick start](#quick-start)
- [How the field-marks engine works](#how-the-field-marks-engine-works)
- [Project structure](#project-structure)

# What it does

| Screen | For | What you get |
|---|---|---|
| **Terrain (LiDAR)** | Earthworks, mounds, ditches, terraces under vegetation | Relief visualizations (hillshade, sky-view factor, openness, local relief model, MSRM…), **Enhance & best view** (cleaning, automatic best view, fused view), interactive 3D view, GeoTIFF/PNG and 3D export |
| **Field marks** | Crop and soil marks of buried features | Image quality per date (clouds, shadows, haze, band problems) with masking, date ranking by local contrast and crop phase, per-date anomaly maps, persistence across dates, field-boundary mask, layers ranked by visibility, check against your known sites |
| **Candidates** | Keeping track of what you found | Verification dossiers that link each anomaly to its evidence, area and status; GeoJSON export |

- **Resolution check**: warns when a target is smaller than the data can resolve.

Scores are investigation priorities, not archaeological probabilities.

# Bring your own data

Every screen opens on **Upload your files**; you can also point to files already on your computer (no copy, useful for multi-GB tiles). Uploads up to 4 GB.

- **Terrain**: DTM/DSM as GeoTIFF, ASCII grid or zip; LAS/LAZ point clouds, gridded to a DTM from their ground points.
- **Images**: one multiband file per date, or one file per band (`…_B04.jp2`, `…_SR_B4.TIF`). Presets for Sentinel-2, Landsat 4–9, PlanetScope 4/8-band, drone multispectral and RGB orthophotos, plus a band editor. Dates are read from file names and can be edited.
- **Known sites**: your own list (CSV with lon/lat or x/y, GeoJSON, GeoPackage, zipped Shapefile, KML), used as ground truth for every layer (AUC against random controls). A sample catalogue is included only as an example.

**Download from a public source** is the second option:

| Source | Coverage | Access in AIrchGIS |
|---|---|---|
| Copernicus DEM GLO-30 | Global, 30 m | Automatic, no account |
| OpenTopography | Global DEMs, national LiDAR | Automatic with your API key (kept in `~/.airchgis/config.json`) |
| Sentinel-2, Landsat (Google Earth Engine) | Global, from 2016 / 1984 | Processed in Earth Engine, with rainfall and land-cover weighting |
| Copernicus Data Space, Planetary Computer, USGS EarthExplorer | Global | Link and expected format; download, then upload |
| National LiDAR: England, Netherlands, Denmark, France, Spain, Slovenia, Italy, USA… | National, 0.25–2 m | Link and expected format |

# Enhance & best view

On the Terrain screen, load your terrain model (step 1), keep the recommended tool **Improve and find the best view** (step 2), type the width of the features you are looking for and press the button. The other relief views (hillshade, slope, sky-view factor, openness, local relief model…) are in the same tool list, each with its main setting; everything else is under **Advanced**. AIrchGIS then:

1. **Cleans the terrain**: removes periodic banding (flight lines), isolated spikes and pits, fills small holes inside the survey, and reduces noise while keeping edges. A table shows each measure before and after; the original is not changed.
2. **Ranks the relief views**: computes up to 19 views (hillshades, slope, sky-view factor, openness, local relief model and multi-scale relief model, with radii matched to your width) and ranks them by a visibility score: how much features of that width stand out from the noise and from the broad landscape. With a list of known sites it also shows the AUC of each view.
3. **Shows the best one** with a one-line explanation and a before/after switch, ready to download as GeoTIFF or to save as a candidate. Measures and the re-runnable script are under **Details**.

Under **Advanced** you can run single steps, see all views, build a **fused view** (a blend of the four best views; if it is not clearer than the best single view, AIrchGIS says so and keeps the best view), and remove isolated points from a LAS/LAZ point cloud. Display contrast (adaptive histogram equalization) is labelled as display only; there is no super-resolution.

On the Field marks screen, **Image quality** scores each date and can mask clouds, shadows and no data before the analysis, and **Enhance & best view** ranks the anomaly layers by the same visibility score.

# Scripts and provenance

Every step runs through `airchgis/gis/tools.py` and is logged with its parameters, input SHA-256, software versions and backend. The log downloads as a Python script that repeats the analysis. QGIS Processing is used through `qgis_process` when installed; otherwise rvt-py and rasterio.

```python
from airchgis.gis import ProvenanceLog, run_tool

log = ProvenanceLog("My survey")
run_tool("clean_terrain", log=log, input="dtm.tif", output="dtm_clean.tif")
run_tool("best_view", log=log, input="dtm_clean.tif", output_dir="views/", target_feature_width_m=5)
log.save_scripts("outputs/")
```

# 3D export for research

On the Terrain screen, under **3D view and 3D export**, **Export 3D for research** writes a georeferenced point cloud (LAZ/LAS and PLY), a terrain mesh (glTF `.glb`) and a JSON sidecar (source, CRS, bounds, resolution, date, relief visualization, vertical exaggeration), zipped for archiving on Zenodo. The files open in QGIS 3D, CloudCompare and Blender. LAZ needs `pip install lazrs`; without it the cloud is written as LAS.

# Quick start

macOS (double-click, or from a terminal):

```bash
./start_airchgis.command
```

Linux and Windows:

```bash
python -m venv .venv_airchgis
source .venv_airchgis/bin/activate    # Windows: .venv_airchgis\Scripts\activate
pip install -r requirements.txt
streamlit run airchgis_app.py
```

The app opens at http://localhost:8501. QGIS and a Google Earth Engine project are optional.

# How the field-marks engine works

The ranking does not reward the images with the most variance: field boundaries and different crops produce that, not buried structures. Each date is scored on:

1. **Local contrast**: deviation of each index from its neighbourhood (60 m by default, the scale of a wall or ditch).
2. **Crop phase**: vegetation, bare soil or mixed. Crop marks need a growing crop, soil marks a ploughed field; the *target mark* option decides which dates are combined.
3. **Antecedent dryness** *(Earth Engine only)*: rainfall of the 30 days before each scene against the 1991–2020 ERA5-Land mean.

Anomalies are computed date by date and aggregated afterwards (a median composite would erase transient marks): vegetation deficit and excess, soil marks, linear marks (gradient coherence), persistence and multi-year recurrence. With three or more dates, pixels whose seasonal curve changes shape across a neighbour are masked as field boundaries; a buried feature only shifts the curve, so it is kept.

<p align="center">
  <img src="docs/assets/screenshot-field-marks.jpg" alt="Field marks screen, upload first" width="760">
</p>

# Project structure

```text
.
├── airchgis_app.py            # entry point
├── start_airchgis.command     # macOS launcher (creates .venv_airchgis)
├── airchgis/
│   ├── app.py                 # shell and navigation
│   ├── rvt_web.py             # Terrain screen, 3D Cloud, 3D research export
│   ├── data_input.py          # loaders: rasters, LAS/LAZ, multispectral scenes, site lists
│   ├── input_ui.py            # shared "upload or local path" input
│   ├── sources.py             # public data sources and downloads
│   ├── spectral/              # local field-marks engine and screen
│   ├── cropmarks_engine.py    # Earth Engine engine (Sentinel-2, Landsat)
│   ├── enhance/               # cleaning, display enhancement, best view, fused view
│   ├── gis/                   # tool registry, QGIS backend, guardrails, provenance, workflows
│   ├── terrain/export3d.py    # LAZ/LAS, PLY, glTF export with metadata
│   ├── candidate_store.py     # verification dossiers
│   ├── benchmark.py           # metrics against known sites
│   └── data/                  # example catalogue, gazetteer, calibration regions
├── RVT/                       # RVT engine, 3D viewer, legacy desktop GUI
├── Crop marks Tool/           # standalone Earth Engine launcher
├── docs/                      # method notes, benchmarks, assets
├── scripts/                   # benchmark and data-preparation scripts
└── tests/
```

Method notes: [`docs/PHASE0_RESOLVABILITY.md`](docs/PHASE0_RESOLVABILITY.md), [`docs/PHASE_A.md`](docs/PHASE_A.md), [`docs/AIRCHGIS_STRUCTURE.md`](docs/AIRCHGIS_STRUCTURE.md).
