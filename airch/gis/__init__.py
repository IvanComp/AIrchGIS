"""GIS tool layer: QGIS Processing (or rvt-py/rasterio) exposed as callable tools.

The assistant never computes results itself: it chooses tools from the
registry in :mod:`airch.gis.tools`, every run is recorded by
:mod:`airch.gis.provenance`, and :mod:`airch.gis.guardrails` stops analyses
the sensor cannot support.
"""

from airch.gis.provenance import ProvenanceLog
from airch.gis.tools import REGISTRY, ToolError, run_tool, tool_specs

__all__ = ["REGISTRY", "ProvenanceLog", "ToolError", "run_tool", "tool_specs"]
