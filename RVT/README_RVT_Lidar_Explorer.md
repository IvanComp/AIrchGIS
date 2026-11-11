# AIrch · LiDAR Explorer (RVT) — README

> Note: RVT is now part of the single `AIrch` app.
> Recommended start from the repository root:
>
> ```bash
> ./start_airch.command
> ```
>
> The desktop GUI described here still works and can be started directly with `python core.py`.

`core.py` provides a Python GUI to explore and export RVT transformations of LiDAR data downloaded as a triplet:
- DTM
- DSM first return
- DSM last return

The script shows a live preview and exports the current result as a georeferenced GeoTIFF.
It also includes a DTM-from-map generator based on the local regional GeoTIFF `data/regional_dtm/HRDTM5m_Umbria_Marche_Abruzzo.tif`: you draw a rectangle on a zoomable web map and the tool creates a clipped DTM for Marche, Abruzzo and Umbria, then loads it into the quick session.

## 1) Requirements

- macOS
- Python 3.10+ (3.11 or 3.12 recommended)
- Folders with the rasters (GeoTIFF/ASC) for DTM, DSMfirst, DSMlast
- The RVT package from pip: `rvt-py`

Note: `relief-visualization-toolbox` is not a pip package. The right package is `rvt-py`.

## 2) Folder structure

```
project/
  core.py
  data/
    regional_dtm/
      HRDTM5m_Umbria_Marche_Abruzzo.tif
  image/
    DTM/
    DSMfirst/
    DSMlast/
```

Inside each folder you can:
- put the `.tif/.tiff/.asc` files directly, or
- unzip the archives and keep any subfolders (the script searches recursively).

Only rasters are used; shapefiles and other files can stay in the folders.

## 3) File-name conventions (triplet matching)

The script builds a "triplet" per tile from the common base name.

Supported examples:
- `xxx_DTM.tif`
- `xxx_DSMFirst.tif`
- `xxx_DSMLast.tif`

Also accepted: `_DSM_First`, `_DSM_Last`, `_dsm-first`, `_dsm-last`

The "base name" is the part before the suffix (e.g. `xxx`). If your files follow none of these conventions, rename them:
- DTM → `BASE_DTM.tif`
- DSM first → `BASE_DSMFirst.tif`
- DSM last → `BASE_DSMLast.tif`

## 4) Virtual environment (recommended)

This avoids conflicts (e.g. an upgrade to `numpy` 2.x).

```bash
mkdir -p ~/venvs
python3 -m venv ~/venvs/rvt
source ~/venvs/rvt/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install "numpy<2" "scipy<1.14" rasterio matplotlib rvt-py

python -c "import rvt.vis, rasterio, numpy, matplotlib; print('OK', numpy.__version__)"
```

Leave the environment with `deactivate`.

## 5) Workflow

1) Pick an area on the portal and download the 3 zips (DTM, DSM First, DSM Last).
2) Unzip them.
3) Copy the rasters into `image/DTM/`, `image/DSMfirst/`, `image/DSMlast/`.
4) Activate the environment: `source ~/venvs/rvt/bin/activate`
5) Go to the project folder: `cd /path/to/project`
6) Start the GUI: `python core.py`

## 5.1) Generate a DTM from the regional map

The `DTM from map` button in the `Quick session` section opens a zoomable Leaflet map of the area covered by the regional raster for Marche, Abruzzo and Umbria, with satellite imagery as the base layer.

1) press `DTM from map`;
2) draw a rectangle and zoom to the area you want;
3) press `Generate DTM and load`;
4) the GeoTIFF is written to `generated_dtm/DTM/` at the native 5 m x 5 m resolution and loaded as the DTM of the quick session.

The source raster is never modified.

## 6) GUI features

Left panel:
- tile (triplet) selection
- dataset: `DTM`, `DSMfirst`, `DSMlast`, `nDSM` (DSMfirst − DTM), `First-Last` (DSMfirst − DSMlast)
- RVT method (depending on what `rvt.vis` provides): Raw, Hillshade, Slope, Sky-View Factor, Local Relief Model, Positive/Negative Openness
- parameters (azimuth/altitude/z-factor/radius/directions) and percentile stretch
- GeoTIFF export of the current result
- basic batch pipeline

Right panel: grayscale preview updated whenever method, parameters or dataset change.

## 7) Output

- Manual export ("Export current GeoTIFF"): `output_rvt_gui/<TILE_KEY>/... .tif`
- Basic batch pipeline: `output_rvt_batch/<TILE_KEY>/`
  - `1_DTM_Hillshade.tif` (if available)
  - `2_DTM_SkyViewFactor.tif` (if available)
  - `3_nDSM.tif`
  - `4_FirstMinusLast.tif`

Outputs are float32 GeoTIFFs with the same georeferencing profile as the input.

## 8) Troubleshooting (macOS)

**Tkinter / GUI does not start.** The python.org "framework" build usually includes Tkinter. If you see `_tkinter not found`, use a Python build with Tk enabled.

**RVT errors on some methods.** `rvt-py` exposes its functions in `rvt.vis`. The script only shows the methods that exist in the installed version.

**Huge rasters / slowness.** Use a smaller tile or downsample externally (GDAL/QGIS) for fast iterations.
