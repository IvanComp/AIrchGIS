"""Streamlit component for the map workbench (two-way: the map sends tool events, Python sends layers)."""

from __future__ import annotations

from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parent / "component"
_component = None


def map_workbench(args: dict, key: str = "as_map_workbench", height: int = 780):
    """Show the map with ``args`` (layers, tools, message, details, download...); returns the last event or None."""
    global _component
    import streamlit.components.v1 as components

    if _component is None:
        _component = components.declare_component("airchgis_map", path=str(COMPONENT_DIR))
    return _component(args=dict(args, height=height), key=key, default=None)
