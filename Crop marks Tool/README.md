# AIrch · Crop Marks (standalone)

> Note: this tool is part of the single `AIrch` app.
> Recommended start from the repository root:
>
> ```bash
> ./start_airch.command
> ```
>
> The instructions below still apply to the standalone launcher.

A local Python/Streamlit tool for automated screening of crop marks and soil marks on Sentinel-2 imagery, following a multitemporal pipeline with spectral indices, Tasselled Cap and PCA.

The tool does not confirm archaeological sites. It is for preliminary screening: it highlights candidate anomalies that must be checked against historical orthophotos, Google Earth, local data, field survey, drone or geophysics.

## What it does

- Shows an interactive map where you draw a rectangle or polygon as the study area.
- Loads Sentinel-2 L2A imagery from Google Earth Engine, with cloud and shadow masking from the SCL band.
- Computes RGB composites, spectral indices, Tasselled Cap brightness/greenness/wetness and PCA.
- Ranks the acquisitions by a spectral-contrast score and shows the layers on the map.
- Exports a multiband GeoTIFF directly or to Google Drive.

## Generated layers

Composites: natural RGB (B4, B3, B2), false-colour infrared (B8, B4, B3), healthy vegetation (B8, B11, B2).

Indices: NDVI, GNDVI, DVI, GDVI, GRVI, Simple Ratio, EVI, MCARI, SAVI, NDMI, NDWI, MSI, Crop_band, Soil_band.

Tasselled Cap: TCT_brightness, TCT_greenness, TCT_wetness. PCA: PC1-PC6.

Candidate anomalies: vegetation deficit and excess, linear marks, soil marks, persistence, multi-year recurrence.

## Requirements

- Python 3.10 or later.
- An active Google Earth Engine account.
- A Google Cloud / Earth Engine project, if your account requires one.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
earthengine authenticate
```

## Run

```bash
streamlit run s2_cropmarks_gui.py
```

Open the local link Streamlit prints, usually `http://localhost:8501`.

## Use

1. Draw a rectangle or polygon on the map.
2. Set the time range and the maximum cloud cover.
3. Choose how many best dates to combine.
4. Press `Run analysis`.
5. Inspect the generated layers on the results map.
6. Download the GeoTIFF or use the Google Drive export.

## Recommended settings

- A small area, e.g. a few km².
- Maximum cloud cover: 5-15%.
- Several years rather than a single season.
- Best dates to combine: 3-5.

For crop marks in Mediterranean farmland, try windows that include spring, early summer, September, November and December. The right date depends on crop, rainfall, moisture and vegetation stress.

## Important notes

Sentinel-2 has limited resolution: the main bands are 10 m, red-edge and SWIR 20 m. The tool does not see small walls or structures directly; it looks for large, repeated or geometrically coherent anomalies.

PCA results change with area, period and crops. Do not read every edge or anomaly as archaeological.

If the direct download fails, the area is probably too large: reduce the AOI or use the Google Drive export.
