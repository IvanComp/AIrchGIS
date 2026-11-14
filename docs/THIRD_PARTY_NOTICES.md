# Third-party notices

AIrchGIS uses [RVT_py — Relief Visualization Toolbox in Python](https://github.com/EarthObservation/RVT_py), developed in collaboration between ZRC SAZU and the University of Ljubljana, as its relief-visualization library. The `rvt-py` package provides the `rvt.vis` and `rvt.blend` modules called by AIrchGIS. RVT_py is distributed under the [Apache License 2.0](https://github.com/EarthObservation/RVT_py/blob/master/LICENSE). Scientific attribution and recommended citations are listed in the upstream [References section](https://github.com/EarthObservation/RVT_py#references).

The map interface in `airchgis/map/detectorlab_map.js`, `airchgis/map/component/workbench.js` and `airchgis/map/component/detectorlab_map.css` is adapted from [DetectorLab](https://github.com/IvanComp/DetectorLab), under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

The adaptation retains the satellite base, terrain relief, place labels, measurement tools, UTM coordinates, Google Earth links and layer controls. AIrchGIS adds terrain raster layers, elevation readouts and controls connected to its analysis tools. DetectorLab's historical maps, Roman roads and prediction layer are omitted.

GeoNames data attribution is stored in generated gazetteer metadata and displayed in the application. The source data are distributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The full RVT workspace uses `rvt.vis`, `rvt.blend`, `rvt.blend_func`, `rvt.default` and `rvt.tile` from upstream commit `bab109c409fedf77ccec7de5fd84c48b791df3d2`. The six bundled configuration files under `airchgis/data/rvt/settings/` are copied from that commit. The upstream Apache 2.0 license is retained at `airchgis/data/rvt/LICENSE`.

AIrchGIS applies local runtime corrections in `airchgis/rvt_runtime.py` for hillshade dimensions with precomputed gradients NumPy array scaling, and the band count for tiled MSTP. Public operation signatures are retained. These changes are documented in `docs/RVT_API_COVERAGE.md` and are not represented as upstream modifications.

The three bundled Vaassen test rasters in `airchgis/data/use_cases/vaassen/` derive from the [AHN4 DTM published by Rijkswaterstaat through PDOK](https://data.overheid.nl/dataset/47567-actueel-hoogtebestand-nederland--ahn--dtm), licensed CC0-1.0. The 0.5 m file retains native grid values; the 1 m and 5 m files average valid native cells. Source URL, processing, coordinates and checksums are in the bundled `provenance.json`. They are not separate surveys.

The English reference raster in `airchgis/data/use_cases/england/` is from the Environment Agency LIDAR Composite DTM, native 1 m resolution. Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). © Environment Agency. The bundled provenance file records its original WCS request, bounding box and checksum.
