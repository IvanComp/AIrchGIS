# Castello di Montedoglio, Sansepolcro, Italy

## Archaeological context

Vigotti (2021) reconstructs the castle and its estates from inventories dated 1432–1434. The ruined castle stands on a hill overlooking the Tiber near Sansepolcro and the present reservoir. The supplied PDF is the bibliographic authority for the title and page range, 181–202.

## Use in the paper

Examine hilltop morphology and possible terraces or enclosure-like forms while distinguishing the castle setting from reservoir margins, water surfaces and survey artefacts. Documentary descriptions support the historical setting; they do not independently validate every terrain anomaly.

## Dataset

Two adjacent supplied PST2 / LIDAR_2014 DTM tiles, mosaicked without resampling into 2000 × 1000 cells. Native EPSG:4326 spacing is 0.00001°; metric analysis requires reprojection. Original NoData is retained. The archive did not supply usable licence metadata; do not infer a redistribution licence from public access.

## Contents

- `../*.tif` and `../provenance.json`: supplied terrain and original data provenance; the DTM is not duplicated here.
- `references.bib`: bibliography ready to import into the manuscript.
- `local_sources/`: full source documents, extracted text when available and original Italian archives. These research copies are excluded from Git; `sources.json` records their origin and checksums.
- `terrain_metadata.json`: measured grid properties, input checksum, figure settings and software versions.
- `figures/terrain_comparison.png` and `.pdf`: elevation and two directional hillshades, with a separate caption.

## Reproduce the figures

From the AIrchGIS repository root:

```sh
.venv_airchgis/bin/python docs/evaluation/prepare_use_case_paper.py --case castello_montedoglio
```

The figure preparation reuses the app's metric reprojection, then runs RVT hillshade at azimuths 315° and 45°, solar altitude 35°, vertical factor 1. The figures use a fixed hillshade range 0–1. They are illustrative panels, not screenshots of AI Relief and not a benchmark. The source rasters remain unchanged. Rerunning requires the existing AIrchGIS environment plus Matplotlib.

## Evidence to collect for the manuscript

Save the app version and settings with any AI Relief export; record feature width, exclusions, relief type, camera and Vertical Boost for 3D figures. Compare AI suggestions against independently established archaeological evidence. Terrain form alone cannot date a feature or establish its function. Do not label anomaly outlines as excavated structures without separate supporting evidence.

## Archived development material

`development/` contains the existing manually specified target outline and before/after development snapshot for this case. It is explicitly not independent evaluation, and it was not recomputed for this collection. See its README before citing any number.
