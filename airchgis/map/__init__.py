"""Map view in the style of DetectorLab (MapLibre GL, satellite base, 3D terrain, layer panel).

The interface (controls, layer cards, measure and UTM tools) is adapted from DetectorLab
(https://github.com/IvanComp/DetectorLab, Apache License 2.0); the historical maps, Roman roads
and prediction-model layers of that project are not included.
"""

from airchgis.map.view import MapLayer, georeference, map_html, render_map  # noqa: F401
