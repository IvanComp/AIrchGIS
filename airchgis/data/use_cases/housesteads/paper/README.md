# Housesteads Roman Fort, Northumberland, UK

## Archaeological context

Housesteads is a documented Roman fort on Hadrian's Wall. Rushworth's two-volume report (2009) provides excavation and survey evidence: Volume 1 covers structures and discussion; Volume 2 covers finds. English Heritage supplies site history and source links. Use published plans to establish a reference before assessing individual AI suggestions.

## Use in the paper

Compare the known fort layout and its surrounding terrain across relief views. Assess correspondence with independently documented features, rather than treating the fact that a well-known site was selected as a detection result.

## Dataset

Environment Agency LIDAR Composite DTM, native 1 m grid, EPSG:27700, 1000 × 1000 cells. The 1 km² extract spans E 378400–379400 and N 568250–569250. The exact WCS request is in ../provenance.json. Attribution: Contains public sector information licensed under the Open Government Licence v3.0. © Environment Agency.

## Contents

- `../*.tif` and `../provenance.json`: supplied terrain and original data provenance; the DTM is not duplicated here.
- `references.bib`: bibliography ready to import into the manuscript.
- `local_sources/`: full source documents, extracted text when available and original Italian archives. These research copies are excluded from Git; `sources.json` records their origin and checksums.
- `terrain_metadata.json`: measured grid properties, input checksum, figure settings and software versions.
- `figures/terrain_comparison.png` and `.pdf`: elevation and two directional hillshades, with a separate caption.

## Reproduce the figures

From the AIrchGIS repository root:

```sh
.venv_airchgis/bin/python docs/evaluation/prepare_use_case_paper.py --case housesteads
```

The figure preparation reuses the app's metric reprojection, then runs RVT hillshade at azimuths 315° and 45°, solar altitude 35°, vertical factor 1. The figures use a fixed hillshade range 0–1. They are illustrative panels, not screenshots of AI Relief and not a benchmark. The source rasters remain unchanged. Rerunning requires the existing AIrchGIS environment plus Matplotlib.

## Evidence to collect for the manuscript

Save the app version and settings with any AI Relief export; record feature width, exclusions, relief type, camera and Vertical Boost for 3D figures. Compare AI suggestions against independently established archaeological evidence. Terrain form alone cannot date a feature or establish its function. Do not label anomaly outlines as excavated structures without separate supporting evidence.

## Evaluation status

No Housesteads archaeological ground truth or quantitative evaluation is supplied here. Older English results in `docs/evaluation/` concern Betterton and must not be attributed to Housesteads. The app retains the legacy identifier `england_1` for this active case.
