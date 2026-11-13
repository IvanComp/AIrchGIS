# Third-party notices

AIrchGIS uses [RVT_py — Relief Visualization Toolbox in Python](https://github.com/EarthObservation/RVT_py), developed in collaboration between ZRC SAZU and the University of Ljubljana, as its relief-visualization library. The `rvt-py` package provides the `rvt.vis` and `rvt.blend` modules called by AIrchGIS. RVT_py is distributed under the [Apache License 2.0](https://github.com/EarthObservation/RVT_py/blob/master/LICENSE). Scientific attribution and recommended citations are listed in the upstream [References section](https://github.com/EarthObservation/RVT_py#references).

The map interface in `airchgis/map/detectorlab_map.js`, `airchgis/map/component/workbench.js` and `airchgis/map/component/detectorlab_map.css` is adapted from [DetectorLab](https://github.com/IvanComp/DetectorLab), under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

The adaptation retains the satellite base, terrain relief, place labels, measurement tools, UTM coordinates, Google Earth links and layer controls. AIrchGIS adds terrain raster layers, elevation readouts and controls connected to its analysis tools. DetectorLab's historical maps, Roman roads and prediction layer are omitted.

GeoNames data attribution is stored in generated gazetteer metadata and displayed in the application. The source data are distributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
