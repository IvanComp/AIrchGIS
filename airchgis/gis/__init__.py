"""GIS tool layer: QGIS Processing (or rvt-py/rasterio) exposed as callable tools.

The assistant never computes results itself: it chooses tools from the
registry in :mod:`airchgis.gis.tools`, every run is recorded by
:mod:`airchgis.gis.provenance`, and :mod:`airchgis.gis.guardrails` stops analyses
the sensor cannot support.
"""

from airchgis.gis.provenance import ProvenanceLog
from airchgis.gis.tools import REGISTRY, ToolError, run_tool, tool_specs

__all__ = ["REGISTRY", "ProvenanceLog", "ToolError", "run_tool", "tool_specs"]
