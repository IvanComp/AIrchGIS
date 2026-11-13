<h1 align="center">
  <img src="airchgis/assets/logo.svg" alt="" width="64" height="64" align="absmiddle">&nbsp; AIrchGIS
</h1>
<p align="center"><b>AI-assisted archaeological GIS</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Streamlit-1.58-FF4B4B?logo=streamlit&logoColor=white" alt="Streamlit 1.58">
  <img src="https://img.shields.io/badge/QGIS-optional%20backend-589632?logo=qgis&logoColor=white" alt="QGIS optional backend">
  <img src="https://img.shields.io/badge/LiDAR-RVT%20%C2%B7%20LAS%2FLAZ-8a6d3b" alt="LiDAR">
  <img src="https://img.shields.io/badge/3D%20export-LAZ%20%C2%B7%20PLY%20%C2%B7%20glTF-c99a26" alt="3D export">
  <img src="https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-555" alt="Platforms">
</p>

AIrchGIS is a local research application for examining digital terrain models and LiDAR point clouds. Its relief-visualization engine is based on **[RVT_py — Relief Visualization Toolbox in Python](https://github.com/EarthObservation/RVT_py)**. Upload terrain data, generate relief visualizations, compare layers on a map and export results as GeoTIFF, 3D data or figures for papers. A resolution check assesses whether the data can resolve features of the requested width.

<p align="center">
  <img src="docs/assets/screenshot-upload.png" alt="AIrchGIS upload screen and three-stage research workflow" width="900">
</p>

# Table of contents

- [Built on RVT_py](#built-on-rvt_py)
- [What it does](#what-it-does)
- [Research workflow](#research-workflow)
- [Bring your own data](#bring-your-own-data)
- [Guide and use cases](#guide-and-use-cases)
- [Tools on the map](#tools-on-the-map)
- [Scripts and provenance](#scripts-and-provenance)
- [3D export for research](#3d-export-for-research)
- [Quick start](#quick-start)
- [Project structure](#project-structure)

# Built on RVT_py

**RVT_py provides the underlying relief-visualization algorithms used by AIrchGIS.** The [Relief Visualization Toolbox in Python](https://github.com/EarthObservation/RVT_py) is developed in collaboration between ZRC SAZU and the University of Ljubljana for visualizing elevation models, including high-resolution LiDAR terrain.

AIrchGIS calls RVT_py through `RVT/core.py`, using `rvt.vis` for methods such as hillshade, slope, sky-view factor, openness and local relief models, and `rvt.blend` for supported composite visualizations. The Python dependency is distributed as `rvt-py`.

| Component | Role in AIrchGIS |
|---|---|
| **RVT_py** | Implementations of the relief visualizations and supported RVT composites |
| **AIrchGIS** | File upload, point-cloud gridding, coordinate handling, interactive map and layer comparison, feature-width-based fusion, resolution checks, provenance and research exports |

The Python API also provides a feature-width-based fused view in `airchgis/enhance/fuse.py` and combines relief layers generated with RVT_py. This is separate from the RVT composites available through `rvt.blend` and is not exposed in the current map interface.

RVT_py is distributed under the [Apache License 2.0](https://github.com/EarthObservation/RVT_py/blob/master/LICENSE). Research using its methods should acknowledge RVT_py and cite the relevant publications listed in its [References section](https://github.com/EarthObservation/RVT_py#references).

# What it does

| Screen | For | What you get |
|---|---|---|
| **Terrain (LiDAR)** | Earthworks, mounds, ditches, terraces under vegetation | Relief visualizations (hillshade, sky-view factor, openness, local relief model, MSRM…), layer comparison on a map, interactive 3D view, GeoTIFF/PNG and 3D export |

- **Resolution check**: warns when a target is smaller than the data can resolve.
- **Map**: after upload everything happens on a MapLibre map in the style of DetectorLab: tools and layers in the right panel, satellite base, 3D relief, distance measure, UTM coordinates with the terrain elevation, Google Earth link.
- **Guide**: **How it Works?** opens a guide with a contents index, numbered sections, a relief-method reference table and practical questions.

Terrain anomalies require interpretation alongside other evidence; AIrchGIS does not confirm archaeological sites.

# Research workflow

The start page presents three stages:

1. **Upload a digital terrain model**: load a terrain raster or LiDAR point cloud.
2. **Preprocessing and visualization**: prepare the terrain, set visualization parameters and generate relief views.
3. **Export, compare and discover**: compare layers and save results for further analysis or publication.

The interface uses a brown and gold palette, Cinzel headings and a numbered workflow joined by an animated light sweep. The logo shows shaded terrain inside a magnifying glass. Animations respect the system's reduced-motion setting.

# Bring your own data

Use **Upload a terrain model or LiDAR point cloud** on the start page. Multiple files are supported, up to 4 GB per file.

| Input | Preparation |
|---|---|
| GeoTIFF or ASCII grid | Requires georeferencing and a coordinate system to appear on the map |
| ZIP archive of raster tiles | Raster files are extracted and checked before loading |
| LAS/LAZ point cloud | Gridded at the selected cell size using classified ground points when available; otherwise all points are used |

Terrain in geographic coordinates is reprojected to a metric UTM coordinate system. The map opens automatically after loading with a **Hillshade (315°)** layer already applied. For large datasets, available memory may require fewer tiles or a smaller area.

The start page uses file upload. Public-source download helpers remain in the codebase but are not exposed in the current interface.

# Guide and use cases

**How it Works?** opens the AIrchGIS guide. Its layout follows DetectorLab's Useful Information page, with an index and sections covering input, preprocessing, relief methods, data quality, map controls, exports and practical limitations. **Back to the tool** returns to the workbench or upload screen.

**Source Code v1.0.0**, beside the guide button, opens the [GitHub repository](https://github.com/IvanComp/AIrchGIS).

The separate **Use cases** group contains three disabled placeholders:

- 🇮🇹 **Colle San Mauro, L'Aquila, Italy**
- 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **TODO, TODO, UK**
- 🇷🇴 **TODO, TODO, Romania**

These buttons do not load example datasets yet.

# Tools on the map

The start page only asks for a terrain model or point cloud. Once it is loaded, the map opens with **Layers** first in the right panel, followed by **Relief Visualization Toolbox**, in the style of the DetectorLab map:

1. **Relief types**: choose a view (hillshade, slope, sky-view factor, openness, local relief model, MSRM…) and its main setting, then **Add to the map**. Hillshade and anisotropic sky-view factor use a **Light direction (°)** slider with a live degree readout. Applying a new type replaces the previous relief and any contrast version; Layers contains a single **Relief view** alongside Place and Base map.
2. **3D Analysis**: the button at the top right opens the terrain viewer and its Export panel, which provides a high-quality image (PDF or PNG, 300 dpi by default) with the top layer draped on the terrain, and open 3D data (LAZ/LAS, PLY, glTF) for QGIS, CloudCompare or Blender.

Layers can be switched on and off, faded, shown with stronger contrast (display only) or removed. Single-band result layers can be downloaded as GeoTIFF. Layers opens and closes as one section. Place, Base map and the current relief view have visibility switches and opacity sliders, displayed directly inside the section. Disabling Base map also disables Place. The arrow on the panel edge hides or restores the panel. **Home** (house icon in the top bar) goes back to the start page. Terrain models in longitude/latitude are reprojected to their UTM zone, so that all sizes are in metres. There is no super-resolution.

Terrain cleaning (banding, spikes and pits, voids, noise) and the automatic best view are available in scripts through `airchgis/gis/tools.py` (`clean_terrain`, `best_view`); they are not in the interface for now.

# Scripts and provenance

The Python tool API in `airchgis/gis/tools.py` supports provenance logs containing parameters, input SHA-256, software versions and backend details. Scripts can be generated programmatically with `ProvenanceLog.save_scripts()`. The current map interface has no Details card or script-download button. QGIS Processing is available through `qgis_process` for supported tools; native backends use rvt-py and rasterio.

```python
from airchgis.gis import ProvenanceLog, run_tool

log = ProvenanceLog("My survey")
run_tool("relief_view", log=log, input="dtm.tif", output="svf.tif", method="Sky-View Factor", radius_px=10)
run_tool("relief_view", log=log, input="dtm.tif", output="lrm.tif", method="Simple Local Relief Model", radius_px=20)
run_tool("fuse_layers", log=log, input="dtm.tif", layers=["svf.tif", "lrm.tif"], output="fused.tif", target_feature_width_m=5)
log.save_scripts("outputs/")
```

# 3D export for research

**3D Analysis** includes the original terrain rendering modes: **Original** (surface), **Cloud 1** (points), **Cloud 2** (surface with wireframe and points), and **Cloud 3** (enhanced local relief). Select a mode in **Terrain rendering** to rebuild the interactive view. Cloud 3 changes displayed elevations to emphasize small terrain forms. NoData and large boundary-connected zero-fill regions are omitted from the interactive surface; the initial framing uses the remaining terrain footprint. These display masks leave the source files unchanged. Rendering modes affect the viewer; figure and open-data exports use the source terrain.

In **3D Analysis** (top right), the **Export** panel contains the image settings and both download actions. **Download high-quality image** saves the terrain in 3D as a PDF (default, 300 dpi, 190 mm wide, for a paper figure) or PNG, with the top layer draped on it, a scale bar and a north arrow; camera, size and resolution are under *Image options*. **Download open 3D data** writes a georeferenced point cloud (LAZ/LAS and PLY), a terrain mesh (glTF `.glb`) and a JSON sidecar (source, CRS, bounds, resolution, date, relief visualization, vertical exaggeration), zipped for archiving on Zenodo. The files open in QGIS 3D, CloudCompare and Blender. LAZ needs `pip install lazrs`; without it the cloud is written as LAS.

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

The app opens at [localhost:8501](http://localhost:8501). QGIS is optional.

Terrain processing runs locally. Basemap imagery, geographic labels and global terrain tiles require internet access. Opening Google Earth shares the selected coordinates with that service.

# Project structure

```text
.
├── airchgis_app.py            # entry point
├── start_airchgis.command     # macOS launcher (creates .venv_airchgis)
├── airchgis/
│   ├── app.py                 # shell and navigation
│   ├── rvt_web.py             # Terrain screen, 3D view, 3D figure and research export
│   ├── help_page.py           # How it Works? guide content and navigation
│   ├── help_page.css          # guide layout, index, cards and FAQ
│   ├── ui.py                  # shared theme, navigation and upload styling
│   ├── assets/logo.svg        # animated terrain logo
│   ├── workbench.py           # map events, analysis state and exports
│   ├── map/                   # MapLibre map (interface adapted from DetectorLab, Apache-2.0)
│   ├── data_input.py          # loaders: rasters, LAS/LAZ, site lists
│   ├── input_ui.py            # shared upload input
│   ├── sources.py             # public data sources and downloads
│   ├── enhance/               # fused view and display contrast (cleaning and best view: scripts only)
│   ├── gis/                   # tool registry, QGIS backend, guardrails, provenance, workflows
│   ├── terrain/               # 3D research export (LAZ/LAS, PLY, glTF) and 3D figures (PDF/PNG)
│   ├── benchmark.py           # metrics against known sites
│   └── data/                  # example catalogue, gazetteer, calibration regions
├── RVT/                       # RVT engine, 3D viewer, legacy desktop GUI
├── docs/                      # method notes, benchmarks, assets
├── scripts/                   # benchmark and data-preparation scripts
└── tests/
```

Third-party attribution: [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

Method notes: [`docs/PHASE0_RESOLVABILITY.md`](docs/PHASE0_RESOLVABILITY.md), [`docs/PHASE_A.md`](docs/PHASE_A.md), [`docs/AIRCHGIS_STRUCTURE.md`](docs/AIRCHGIS_STRUCTURE.md).
