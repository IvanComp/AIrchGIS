import base64
import hashlib
import importlib.util
import io
import json
import logging
import math
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw
from xml.sax.saxutils import escape as xml_escape

from .paths import RVT_DIR


RVT_UPLOAD_DIR = RVT_DIR / ".streamlit_uploads"
RVT_OUTPUT_DIR = RVT_DIR / "output_rvt_gui"
WEB_3D_LAS_MAX_POINTS = 500_000
WEB_3D_BROWSER_MAX_SIDE = 1400


PERSISTENT_KEYS = ("as_rvt_source_mode", "as_rvt_place", "as_rvt_tool", "as_rvt_azimuth", "as_rvt_radius", "as_rvt_dataset",
                   "as_rvt_altitude", "as_rvt_z_factor", "as_rvt_n_dir", "as_rvt_p_low", "as_rvt_p_high", "as_rvt_invert",
                   "as_rvt_base_mode", "as_rvt_basemap_year", "as_rvt_overlay_opacity", "as_enh_t_width")


def keep_settings(keys):

    saved = st.session_state.setdefault("_as_saved_settings", {})
    for k in keys:
        if k not in st.session_state and k in saved:
            st.session_state[k] = saved[k]


def save_settings(keys):
    saved = st.session_state.setdefault("_as_saved_settings", {})
    for k in keys:
        if k in st.session_state:
            saved[k] = st.session_state[k]


def render_rvt_web():
    keep_settings(PERSISTENT_KEYS)
    init_rvt_state()
    wb = st.session_state.get("as_wb")
    if wb is None:
        render_start_page()
    else:
        core = load_rvt_core()
        if "as_rvt_place" not in st.session_state:
            places = core.list_database_places(RVT_DIR)
            st.session_state.as_rvt_place = places[0] if places else ""
        render_workbench(core, wb)


def render_start_page():

    _, mid, _ = st.columns([0.12, 0.76, 0.12])
    with mid, st.container(key="home_layout"):
        with st.container(key="terrain_upload"):
            st.session_state.as_rvt_source_mode = source_mode = "Upload"
            uploads = render_upload_controls()
            example_path = st.session_state.pop("as_use_case_path", None)
            if example_path:
                uploads = {"DTM": [example_path]}
            st.markdown(
                '<ol class="as-upload-steps" aria-label="Research workflow">'
                '<li><span class="as-step-number" aria-hidden="true">01</span>'
                '<h3>Upload a digital terrain model</h3><p>Load a terrain raster or a LiDAR point cloud to open the map.</p></li>'
                '<li><span class="as-step-number" aria-hidden="true">02</span>'
                '<h3>Preprocessing and visualization</h3><p>Set the processing parameters, generate relief views and combine layers.</p></li>'
                '<li><span class="as-step-number" aria-hidden="true">03</span>'
                '<h3>Export, compare and<br>discover</h3><p>Compare layers on the map and export GeoTIFFs, figures or 3D data.</p></li></ol>',
                unsafe_allow_html=True,
            )
        from . import ui

        ui.render_reference_links()
        payload = {"uploads": uploads}
        if not uploads.get("DTM"):
            return
        params = {"source_mode": source_mode, "source_payload": payload, "base_mode": "Original"}
        core = load_rvt_core()
        data = current_rvt_data(core, params)
        if data is None or not data.loaded or data.dtm is None:
            msg = getattr(data, "error", None) if data is not None else None
            if msg and ("too big" in msg or "Unable to allocate" in msg or "MemoryError" in msg):
                msg = "The terrain is too large to open at once on this computer. Load fewer tiles, or a smaller area."
            st.warning(msg or "The terrain data could not be loaded.")
            return
        if data.profile is None or data.profile.get("transform") is None or data.crs is None:
            st.warning("This file has no coordinate system or georeference, so it cannot be placed on the map.")
            return
        name = Path((uploads.get("DTM") or [payload.get("generated_dtm") or "terrain"])[0]).stem
        from airchgis.workbench import Workbench, handle_event

        source = st.session_state.get("as_prep_source") or {"kind": "raster"}
        wb = Workbench(data.dtm, data.profile["transform"], data.crs, data.profile, name=clean_name(name),
                       log=st.session_state.get("as_prep_log") if source.get("kind") == "points" else None,
                       source=source, notes=st.session_state.get("as_prep_notes"))
        from airchgis.use_cases import CASES

        case = next((c for c in CASES if example_path and str(c["path"]) == example_path), None)
        wb.use_case = {k: case[k] for k in ("label", "summary", "terrain", "references") if k in case} if case else None
        if source.get("kind") == "points":
            wb.prep["source_steps"] = source.get("steps", [])
            wb.prep["grid"] = {"method": "tin", "cell_m": 0.0, "ground_only": True, "remove_outliers": True}
        with st.spinner("Preparing the terrain..."):
            handle_event(wb, {"action": "prepare", "fill_voids": True, "cell_m": 0.0, "nonce": "initial-prepare"}, core=core)
        st.session_state.as_wb = wb
        st.session_state.as_wb_data = data
        st.rerun()


def workbench_tools(core):
    views = []
    methods = available_methods(core)
    methods = [m for m in methods if m != "Raw"] + (["Raw"] if "Raw" in methods else [])
    for m in methods:
        param = None
        if m in ("Hillshade", "Anisotropic Sky-View Factor"):
            param = {"key": "azimuth", "label": "Light direction (°)", "min": 0, "max": 360, "step": 5, "value": 315}
        elif m in RADIUS_TOOLS:
            param = {"key": "radius", "label": "Search radius (pixels)", "min": 1, "max": 200, "step": 1, "value": 10}
        views.append({"id": m, "name": m, "help": TOOL_HELP.get(m, ""), "param": param})
    descriptions = {
        "original": "Terrain surface without additional relief enhancement.",
        "cloud1": "Terrain samples rendered as points.",
        "cloud2": "Continuous surface with wireframe and point overlays.",
        "cloud3": "Enhanced local relief at a %g m scale. Displayed elevations are modified to emphasize small terrain "
                  "forms." % core.CLOUD_PREPROCESS_PROFILES.get("cloud3", {}).get("relief_sigma_m", 18.0),
        "ai_relief": "Terrain coloured by the Unusual relief (AI) score, with priority areas outlined. The analysis "
                     "runs automatically on first use. Priorities to check, not sites.",
    }
    profiles = [{"id": key, "name": core.CLOUD_PREPROCESS_PROFILES[key]["label"], "description": description}
                for key, description in descriptions.items() if key in core.CLOUD_PREPROCESS_PROFILES]
    return {"views": views, "cloud_profiles": profiles}


def relief_params(method, value):
    params = {"method": method, "dataset": "DTM", "azimuth": 315.0, "altitude": 35.0, "z_factor": 1.0, "radius": 10.0,
              "n_dir": 16, "p_low": 2.0, "p_high": 98.0, "invert": False}
    if value is not None:
        if method in ("Hillshade", "Anisotropic Sky-View Factor"):
            params["azimuth"] = float(value)
        elif method in RADIUS_TOOLS:
            params["radius"] = float(value)
    return params


def render_workbench(core, wb):

    from airchgis.map.workbench_component import map_workbench
    from airchgis.workbench import handle_event

    data = st.session_state.get("as_wb_data")
    args = wb.map_args(workbench_tools(core))
    args["use_case"] = getattr(wb, "use_case", None)
    args["basemap"] = satellite_template(core, "Current")
    nav_event = st.session_state.pop("as_wb_nav_event", None)
    open_from_map = bool(nav_event and nav_event.get("action") == "view3d")
    if open_from_map:
        args["open3d_request"] = nav_event["nonce"]
    event = map_workbench(args, key="as_map_workbench", height=780)
    if open_from_map:
        return
    event = nav_event or event
    if not event or event.get("nonce") == st.session_state.get("as_wb_last_nonce"):
        return
    st.session_state.as_wb_last_nonce = event.get("nonce")

    def compute(method, value):
        params = relief_params(method, value)
        raw = core.as_float32(core.compute_method(method, wb.dem, float(wb.res), params["azimuth"], params["altitude"],
                                                  params["z_factor"], params["radius"], int(params["n_dir"])))
        if np.ndim(raw) == 3 or core.is_rgb_method(method):
            return raw, core.normalize_rgb01(raw)
        return raw, None

    def view3d():
        cloud_key = event.get("cloud_key", wb.cloud_key)
        if cloud_key not in core.CLOUD_PREPROCESS_PROFILES:
            raise ValueError("Unknown terrain rendering mode.")
        from types import SimpleNamespace

        terrain = SimpleNamespace(dtm=wb.dem, profile=wb.profile, crs=wb.crs)
        prev = getattr(wb, "ai3d", None) or {}
        wb.ai3d = {"show": bool(event.get("ai_show", prev.get("show", True))),
                   "adaptive_ve": False}
        html_path, _las, _meta = build_3d_cloud(core, terrain, {"source_mode": "Upload", "source_payload": {}}, cloud_key,
                                                ai=getattr(wb, "ai_result", None), show_ai=wb.ai3d["show"],
                                                adaptive_ve=wb.ai3d["adaptive_ve"])
        html = Path(html_path).read_text(encoding="utf-8")
        Path(html_path).unlink(missing_ok=True)
        Path(_las).unlink(missing_ok=True)
        capture = (Path(__file__).with_name("terrain") / "viewer_capture.js").read_text(encoding="utf-8")
        html = html.replace("      renderer.render(scene, camera);", "      renderInteractive();")
        html = html.replace("    function animate() {", capture + "\n    function animate() {", 1)
        wb.cloud_key = cloud_key


        hide = "<style>a.toolbar-btn[download],.analysis-mode-btn{display:none!important}</style>"
        return html.replace("</head>", hide + "</head>", 1) if "</head>" in html else hide + html

    with st.spinner("Working..."):
        result = handle_event(wb, event, compute=compute, core=core, view3d=view3d)
    if result == "reload":
        for k in ("as_wb", "as_wb_data", "as_rvt_data", "as_rvt_data_sig", "as_rvt_generated_dtm"):
            st.session_state[k] = None
        for k in list(st.session_state.keys()):
            if str(k).startswith("_as_uploaded_"):
                st.session_state[k] = []
    st.rerun()


@st.cache_resource(show_spinner=False)
def load_rvt_core():
    rvt_path = str(RVT_DIR)
    if rvt_path not in sys.path:
        sys.path.insert(0, rvt_path)
    spec = importlib.util.spec_from_file_location("airchgis_rvt_core", RVT_DIR / "core.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("RVT/core.py not found.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def init_rvt_state():
    defaults = {
        "as_rvt_data": None,
        "as_rvt_data_sig": None,
        "as_rvt_generated_dtm": None,
        "as_rvt_report_items": [],
        "as_rvt_last_rgb": None,
        "as_rvt_last_rvt_rgb": None,
        "as_rvt_last_out": None,
        "as_rvt_last_status": "",
        "as_rvt_dataset": "DTM",
        "as_rvt_method": "Hillshade",
        "as_rvt_azimuth": 315.0,
        "as_rvt_altitude": 45.0,
        "as_rvt_z_factor": 1.0,
        "as_rvt_radius": 10.0,
        "as_rvt_n_dir": 16,
        "as_rvt_p_low": 2.0,
        "as_rvt_p_high": 98.0,
        "as_rvt_invert": False,
        "as_rvt_basemap_on": False,
        "as_rvt_basemap_mix": 0.35,
        "as_rvt_basemap_year": "Current",
        "as_rvt_overlay_opacity": 1.0,
        "as_rvt_image_tool": "coordinate",
        "as_rvt_last_click_info": None,
        "as_rvt_dtm_map_view": "Current satellite",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not st.session_state.get("as_rvt_default_method_applied"):
        st.session_state.as_rvt_method = "Hillshade"
        st.session_state.as_rvt_default_method_applied = True


BEST_VIEW_TOOL = "Improve and find the best view"
TOOL_HELP = {
    BEST_VIEW_TOOL: "Recommended: cleans the terrain and picks the clearest view for the size of your features.",
    "Raw": "The elevations as they are.",
    "Hillshade": "Shaded relief lit by a low sun; a single light direction can hide features parallel to it.",
    "Multi-Hillshade": "Shaded relief from many light directions at once.",
    "Slope": "Steepness; shows banks, terraces and the edges of mounds and ditches.",
    "Sky-View Factor": "How much sky each point sees: hollows dark, ridges bright, no light direction.",
    "Anisotropic Sky-View Factor": "Sky-view factor weighted towards one direction.",
    "Positive Openness": "Highlights convex micro-relief such as banks and walls.",
    "Simple Local Relief Model": "Removes the large landscape and keeps small bumps and hollows.",
    "Multi-Scale Relief Model": "Local relief at several scales in one image.",
    "Multi-Scale Topographic Position": "Colour image of relief position at local, middle and broad scale.",
    "Sky Illumination": "Shading under a diffuse sky.",
    "Local Dominance": "How much each point rises above its surroundings; good for low mounds.",
    "e3MSTP (RGB)": "Colour blend of several visualizations for archaeology.",
}
RADIUS_TOOLS = {"Sky-View Factor", "Anisotropic Sky-View Factor", "Positive Openness", "Simple Local Relief Model",
                "Multi-Scale Relief Model", "Local Dominance"}
SOURCE_LABELS = {"Upload": "Your files", "DTM from map": "Public source (download)"}


def _slider(label, lo, hi, state_key, **kw):

    value = st.slider(label, lo, hi, value=type(lo)(st.session_state[state_key]), key=f"{state_key}__w", **kw)
    st.session_state[state_key] = value
    return value


def render_rvt_controls(core):
    st.markdown("**1 · Load data**")
    source_mode = "Upload"
    st.session_state.as_rvt_source_mode = source_mode
    source_payload = {"uploads": render_upload_controls(core)}

    method_values = available_methods(core)
    waiting_for_map_dtm = source_mode == "DTM from map" and not source_payload.get("generated_dtm")

    st.markdown("**2 · Choose a tool**")
    tools = [BEST_VIEW_TOOL] + method_values
    if st.session_state.get("as_rvt_tool") not in tools:
        st.session_state.as_rvt_tool = BEST_VIEW_TOOL
    tool = st.selectbox("Tool", tools, key="as_rvt_tool", label_visibility="collapsed")
    st.caption(TOOL_HELP.get(tool, ""))
    method = tool if tool != BEST_VIEW_TOOL else (st.session_state.as_rvt_method if st.session_state.as_rvt_method in method_values else "Hillshade")
    st.session_state.as_rvt_method_used = method
    if tool in ("Hillshade", "Anisotropic Sky-View Factor"):
        _slider("Light direction (degrees from north)", 0.0, 360.0, "as_rvt_azimuth")
    if tool in RADIUS_TOOLS:
        _slider("Search radius (pixels)", 1.0, 200.0, "as_rvt_radius",
                help="About the size of the features you are looking for, in pixels.")

    with st.expander("Advanced"):
        st.session_state.as_rvt_dataset = "DTM"
        st.slider("Sun height (degrees)", 0.0, 90.0, key="as_rvt_altitude")
        st.slider("Vertical exaggeration", 0.1, 10.0, key="as_rvt_z_factor")
        st.slider("Search directions", 4, 64, key="as_rvt_n_dir")
        st.slider("Contrast: dark cut (percentile)", 0.0, 20.0, key="as_rvt_p_low")
        st.slider("Contrast: bright cut (percentile)", 80.0, 100.0, key="as_rvt_p_high")
        st.checkbox("Invert colours", key="as_rvt_invert")
        mode = st.selectbox("Pre-smoothing of the input", core.BASE_IMAGE_OPTIONS, index=1, key="as_rvt_base_mode")
        preset_cols = st.columns(2)
        preset_cols[0].button("Preset: earthworks", width="stretch", on_click=apply_archaeology_preset, args=(core,),
                              help="Settings that suit banks, mounds and terraces.")
        preset_cols[1].button("Preset: ditches", width="stretch", on_click=apply_rectangles_preset, args=(core,),
                              help="Settings that suit ditches and rectangular enclosures.")
        basemap_years = ["Current"] + cached_wayback_years(core)
        basemap_year = st.selectbox("Satellite image year", basemap_years, key="as_rvt_basemap_year")
    dataset = st.session_state.as_rvt_dataset
    overlay_opacity = float(st.session_state.as_rvt_overlay_opacity)

    return {
        "source_mode": source_mode,
        "source_payload": source_payload,
        "base_mode": mode,
        "tool": tool,
        "dataset": dataset,
        "method": method,
        "azimuth": float(st.session_state.as_rvt_azimuth),
        "altitude": float(st.session_state.as_rvt_altitude),
        "z_factor": float(st.session_state.as_rvt_z_factor),
        "radius": float(st.session_state.as_rvt_radius),
        "n_dir": int(st.session_state.as_rvt_n_dir),
        "p_low": float(st.session_state.as_rvt_p_low),
        "p_high": float(st.session_state.as_rvt_p_high),
        "invert": bool(st.session_state.as_rvt_invert),
        "basemap_on": overlay_opacity < 1.0,
        "basemap_mix": 1.0 - overlay_opacity,
        "overlay_opacity": overlay_opacity,
        "basemap_year": basemap_year,
    }


def render_upload_controls(core=None):
    from airchgis import data_input as di
    from airchgis.input_ui import render_file_input

    uploads = {}

    def load_group(key, label):
        exts = {".tif", ".tiff", ".asc", ".zip"} | ({".las", ".laz"} if key == "DTM" else set())
        paths = render_file_input(label, exts, f"as_rvt_in_{key}", f"terrain_{key}")
        out = []
        for p in paths:
            try:
                if p.suffix.lower() == ".zip":
                    zip_core = core if core is not None else load_rvt_core()
                    out.extend(extract_zip_rasters(zip_core, p, key))
                elif p.suffix.lower() in di.POINT_CLOUD_EXTS:
                    # point cloud -> DTM with the default pre-processing (ground class, outliers, density, TIN)
                    tif = di.UPLOAD_DIR / "dtm_from_point_cloud" / f"{p.stem}_tin_auto.tif"
                    cached = st.session_state.get("as_prep_source")
                    if not (cached and cached.get("path") == str(p) and tif.exists()):
                        from airchgis.gis.provenance import ProvenanceLog
                        from airchgis.gis.tools import run_tool

                        log = ProvenanceLog(f"AIrchGIS · {p.stem}")
                        with st.spinner(f"Making a terrain model from {p.name}..."):
                            r = run_tool("grid_point_cloud", log=log, input=str(p), output=str(tif))
                        st.session_state.as_prep_log = log
                        st.session_state.as_prep_source = {"kind": "points", "path": str(p), "steps": r["outputs"]["steps"]}
                    out.append(str(tif))
                else:
                    out.append(str(p))
            except Exception as exc:
                st.error(f"{p.name}: cannot be read ({exc}).")
        if not any(Path(p).suffix.lower() in di.POINT_CLOUD_EXTS for p in paths):
            st.session_state.as_prep_source = None
        uploads[key] = out

    load_group("DTM", "Upload a terrain model or LiDAR point cloud")
    if uploads.get("DTM"):
        keep, notes, error = usable_rasters(uploads["DTM"])
        if error:
            st.error(error)
            keep = []
        if len(keep) > 1:
            notes = [f"{len(keep)} tiles in the same coordinate system joined into one terrain."] + notes
        st.session_state.as_prep_notes = notes
        uploads["DTM"] = keep
    uploads.setdefault("DSM_First", [])  # surface models are not offered in the interface
    uploads.setdefault("DSM_Last", [])
    return uploads


PREP_SUFFIXES = ("_prep", "_prep1", "_prep2", "_prep3")
MAX_MOSAIC_BYTES = 1.5e9


def usable_rasters(paths):

    import rasterio
    from rasterio.warp import transform_bounds

    notes = []
    files = [Path(p) for p in paths if not Path(p).stem.endswith(PREP_SUFFIXES)]
    if len(files) < len(paths):
        notes.append(f"{len(paths) - len(files)} smoothed copies (*_prep*) left out.")
    keep, crs0, bounds, res = [], None, None, None
    for p in files:
        try:
            with rasterio.open(p) as src:
                crs, b, r = src.crs, src.bounds, min(abs(src.res[0]), abs(src.res[1]))
        except Exception as exc:
            notes.append(f"{p.name}: cannot be read ({exc}).")
            continue
        if crs0 is None:
            crs0 = crs
        elif crs != crs0:
            notes.append(f"{p.name} left out: its coordinate system ({crs}) differs from the first file ({crs0}).")
            continue
        keep.append(str(p))
        bounds = b if bounds is None else (min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3]))
        res = r if res is None else min(res, r)
    error = None
    if keep and res:
        cells = ((bounds[2] - bounds[0]) / res) * ((bounds[3] - bounds[1]) / res)
        if cells * 4 > MAX_MOSAIC_BYTES:
            error = (f"These files together make a terrain of about {cells / 1e6:,.0f} million cells, too large to open at "
                     "once on this computer. Load fewer tiles, or a smaller area.")
    return keep, notes, error


def extract_zip_rasters(core, path, dataset_key):
    extract_dir = Path(path).with_suffix("")
    marker = extract_dir / ".unzipped"
    if not marker.exists():
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(extract_dir)
        marker.write_text("ok", encoding="utf-8")
    return [str(p) for p in core.list_rasters(extract_dir) if not p.stem.endswith(PREP_SUFFIXES)]


def render_public_terrain_sources():
    from airchgis import data_input as di
    from airchgis import sources
    from airchgis.spectral.screen import render_provider_table

    st.markdown("**Public terrain sources**")
    with st.expander("What each source covers and how to get it"):
        render_provider_table("terrain")
    st.caption("Automatic download of a global surface model for an area (lon/lat, WGS84). For LiDAR, download from the "
               "national portal and use the upload tab.")
    c = st.columns(4)
    west = c[0].number_input("West", -180.0, 180.0, 13.40, 0.01, format="%.4f", key="as_rvt_dl_w")
    south = c[1].number_input("South", -90.0, 90.0, 42.00, 0.01, format="%.4f", key="as_rvt_dl_s")
    east = c[2].number_input("East", -180.0, 180.0, 13.50, 0.01, format="%.4f", key="as_rvt_dl_e")
    north = c[3].number_input("North", -90.0, 90.0, 42.08, 0.01, format="%.4f", key="as_rvt_dl_n")
    src = st.selectbox("Source", ["Copernicus DEM GLO-30 (no account)", "OpenTopography (your API key)"], key="as_rvt_dl_src")
    dem = None
    if src.startswith("OpenTopography"):
        dem = st.selectbox("Dataset", list(sources.OPENTOPO_DEMS), format_func=sources.OPENTOPO_DEMS.get, key="as_rvt_dl_dem")
        if not sources.has_secret("opentopography_api_key"):
            key = st.text_input("OpenTopography API key", type="password", key="as_rvt_dl_key",
                                help="Stored only in your user folder (~/.airchgis/config.json), never in the project.")
            if key and st.button("Save key", key="as_rvt_dl_save"):
                sources.save_config_value("opentopography_api_key", key.strip())
                st.rerun()
    if st.button("Download DEM", type="primary", key="as_rvt_dl_go"):
        if east <= west or north <= south:
            st.error("East must be greater than West and North greater than South.")
            return
        out = di.UPLOAD_DIR / "downloads" / f"{'cop30' if dem is None else dem}_{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}.tif"
        try:
            with st.spinner("Downloading..."):
                if dem is None:
                    sources.download_cop_dem((west, south, east, north), out)
                else:
                    sources.download_opentopography((west, south, east, north), out, dem=dem)
            st.session_state.as_rvt_generated_dtm = str(out)
            st.session_state.as_rvt_data_sig = None
            st.rerun()
        except Exception as exc:
            st.error(f"Download not completed: {exc}")


def render_regional_dtm_selector(core):
    src = core.regional_dtm_source_path(RVT_DIR)
    if not src.exists():
        st.warning("Regional DTM not found.")
        return

    try:
        bounds = core.raster_bounds_lonlat(src)
    except Exception as exc:
        st.error(str(exc))
        return

    method_values = available_methods(core)
    if st.session_state.as_rvt_method not in method_values:
        st.session_state.as_rvt_method = "Hillshade" if "Hillshade" in method_values else method_values[0]
    selector_cols = st.columns([0.56, 0.44], gap="medium")
    with selector_cols[0]:
        st.selectbox(
            "Map type to generate from the DTM",
            method_values,
            key="as_rvt_method",
        )
    with selector_cols[1]:
        map_view = st.selectbox(
            "Map display",
            ["Current satellite", "Towns and roads"],
            key="as_rvt_dtm_map_view",
        )

    import folium
    from folium.plugins import Draw
    from streamlit_folium import st_folium

    center = [(bounds[1] + bounds[3]) / 2.0, (bounds[0] + bounds[2]) / 2.0]
    fmap = folium.Map(location=center, zoom_start=8, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=core.ARCGIS_CURRENT_TILE_TEMPLATE,
        attr="Esri",
        name="Current satellite",
        show=map_view == "Current satellite",
    ).add_to(fmap)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Towns and roads",
        show=map_view == "Towns and roads",
    ).add_to(fmap)
    folium.Rectangle(
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        color="#10b981",
        fill=False,
        weight=2,
        tooltip="DTM coverage",
    ).add_to(fmap)
    Draw(
        export=False,
        draw_options={
            "polyline": False,
            "polygon": False,
            "rectangle": True,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        },
        edit_options={"edit": True},
    ).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    map_key = "city" if map_view == "Towns and roads" else "satellite"
    draw = st_folium(
        fmap,
        width=1200,
        height=720,
        key=f"as_rvt_regional_map_{map_key}",
        returned_objects=["all_drawings"],
    )

    if st.button("Generate DTM and show map", type="primary", width="stretch"):
        drawings = draw.get("all_drawings") or []
        if not drawings:
            st.error("Draw a rectangle on the map.")
        else:
            coords = drawings[-1]["geometry"]["coordinates"][0]
            lon = [pt[0] for pt in coords]
            lat = [pt[1] for pt in coords]
            selected_bounds = [min(lon), min(lat), max(lon), max(lat)]
            with st.spinner("Generating DTM..."):
                out_path, _meta = core.create_regional_dtm_crop(RVT_DIR, selected_bounds)
            st.session_state.as_rvt_generated_dtm = str(out_path)
            st.session_state.as_rvt_data_sig = None
            st.rerun()


def save_uploaded_rasters(core, files, dataset_key):
    if not files:
        return []
    out = []
    dest = RVT_UPLOAD_DIR / dataset_key
    dest.mkdir(parents=True, exist_ok=True)
    for uploaded in files:
        raw = uploaded.getvalue()
        digest = hashlib.sha1(raw).hexdigest()[:12]
        clean_name = Path(uploaded.name).name
        path = dest / f"{digest}_{clean_name}"
        if not path.exists() or path.stat().st_size != len(raw):
            path.write_bytes(raw)
        if path.suffix.lower() == ".zip":
            extract_dir = dest / path.stem
            marker = extract_dir / ".unzipped"
            if not marker.exists():
                if extract_dir.exists():
                    for item in extract_dir.rglob("*"):
                        if item.is_file():
                            item.unlink()
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(path, "r") as zf:
                    zf.extractall(extract_dir)
                marker.write_text(digest, encoding="utf-8")
            out.extend(core.list_rasters(extract_dir))
        elif path.suffix.lower() in core.EXTS:
            out.append(path)
    return [str(p) for p in out]


def current_rvt_data(core, params):
    sig = data_signature(params)
    if st.session_state.as_rvt_data is not None and st.session_state.as_rvt_data_sig == sig:
        return st.session_state.as_rvt_data

    with st.spinner("Loading RVT..."):
        data = load_input_data(core, params)
    st.session_state.as_rvt_data = data
    st.session_state.as_rvt_data_sig = sig
    st.session_state.as_rvt_last_rgb = None
    st.session_state.as_rvt_last_rvt_rgb = None
    st.session_state.as_rvt_last_out = None
    return data


def data_signature(params):
    payload = params["source_payload"]
    source_mode = params["source_mode"]
    if source_mode == "Database":
        source = payload.get("place") or ""
    elif source_mode == "Upload":
        source = json.dumps(payload.get("uploads") or {}, sort_keys=True)
    else:
        source = payload.get("generated_dtm") or ""
    return (
        source_mode,
        source,
        params["base_mode"],
    )


def load_input_data(core, params):
    data = core.InputData(RVT_DIR)
    mode = params["base_mode"]
    profile_key = core.BASE_IMAGE_TO_PROFILE.get(mode)
    use_preprocessed = profile_key is not None
    profile = core.PREPRO_PROFILES.get(profile_key or "prep1", core.PREPRO_PROFILES["prep1"])

    source_mode = params["source_mode"]
    payload = params["source_payload"]

    try:
        if source_mode == "Database":
            place = payload.get("place") or ""
            if use_preprocessed and place:
                ensure_database_preprocessed(core, place, profile)
            data.load(place_name=place, use_preprocessed=use_preprocessed, preprocessed_suffix=profile["suffix"])
        elif source_mode == "Upload":
            uploads = payload.get("uploads") or {}
            if use_preprocessed:
                ensure_preprocessed_groups(core, [uploads.get("DTM"), uploads.get("DSM_First"), uploads.get("DSM_Last")], profile)
            data.load_from_paths(
                uploads.get("DTM") or [],
                uploads.get("DSM_First") or [],
                uploads.get("DSM_Last") or [],
                use_preprocessed=use_preprocessed,
                preprocessed_suffix=profile["suffix"],
            )
        else:
            generated = payload.get("generated_dtm")
            paths = [generated] if generated else []
            if use_preprocessed:
                ensure_preprocessed_groups(core, [paths], profile)
            data.load_from_paths(paths, [], [], use_preprocessed=use_preprocessed, preprocessed_suffix=profile["suffix"])
    except Exception as exc:
        data.loaded = False
        data.error = str(exc)
    return data


def ensure_database_preprocessed(core, place, profile):
    db_root = core.get_database_root(RVT_DIR)
    if db_root is None:
        return
    base = db_root / place
    core.prepare_inputs_place(base)
    groups = [
        core.select_rasters(base / "DTM", prefer_preprocessed=False),
        core.select_rasters_from_candidates(base, core.FIRST_DIR_CANDIDATES, prefer_preprocessed=False),
        core.select_rasters_from_candidates(base, core.LAST_DIR_CANDIDATES, prefer_preprocessed=False),
    ]
    ensure_preprocessed_groups(core, groups, profile)


def ensure_preprocessed_groups(core, src_groups, profile):
    for group in src_groups:
        items = [Path(p).expanduser().resolve() for p in (group or []) if p]
        for src in items:
            fresh, dst = core.has_fresh_preprocessed(RVT_DIR, src, suffix=profile["suffix"])
            if fresh:
                continue
            core.preprocess_raster_file(
                src,
                dst,
                fill_dist=profile["fill_dist"],
                fill_smooth_iter=profile["fill_smooth_iter"],
                sigma=profile["sigma"],
            )


def render_rvt_viewer(core, data, params):
    st.markdown("**3 · Result**")
    if params["tool"] == BEST_VIEW_TOOL:
        render_enhance(data, params)
    else:
        available = dataset_options(data)
        if params["dataset"] not in available:
            params = dict(params)
            params["dataset"] = available[0] if available else "DTM"
        try:
            with st.spinner("Computing..."):
                rgb, raw_out, status = compose_current_view(core, data, params)
            st.session_state.as_rvt_last_rgb = rgb
            if rgb is not None and params["dataset"] != "Original":
                st.session_state.as_rvt_last_rvt_rgb = rgb
            st.session_state.as_rvt_last_out = raw_out
            st.session_state.as_rvt_last_status = status
        except Exception as exc:
            st.error(str(exc))
            return
        render_view_toolbar(core, data, rgb, params)
        st.caption(f"{params['method']} of the {params['dataset']}. {TOOL_HELP.get(params['method'], '')}")
        render_exports(core, data, params, rgb, raw_out)
    with st.expander("3D view and 3D export"):
        render_3d_cloud(core, data, params)


_DATASET_ATTR = {"DTM": "dtm", "DSM_First": "dsmf", "DSM_Last": "dsml", "nDSM": "ndsm", "First-Last": "diff"}


def render_enhance(data, params):
    from airchgis.enhance.screen import render_terrain_enhance

    dataset = params["dataset"] if params["dataset"] in _DATASET_ATTR else "DTM"
    dem = get_dataset_array(data, dataset)

    def apply(cleaned):
        setattr(data, _DATASET_ATTR[dataset], cleaned.astype(np.float32))
        st.session_state.as_rvt_last_rgb = None
        st.session_state.as_rvt_last_rvt_rgb = None
        st.session_state.as_rvt_last_out = None

    render_terrain_enhance(dem, float(data.res), data.profile, data.crs, label=dataset, on_apply=apply)


def render_view_toolbar(core, data, rgb, params):
    render_view_map(core, data, rgb, params)


def terrain_map_layers(data, rgb, name, description):

    from airchgis.map.view import elevation_grid, georeference

    transform = (data.profile or {}).get("transform")
    if transform is None or data.crs is None:
        return [], None
    from airchgis.enhance.metrics import zero_nodata

    layers = []
    dem = zero_nodata(data.dtm)[0] if data.dtm is not None else None
    if rgb is not None:
        rgb = np.array(rgb, dtype=np.float32)
        if dem is not None and rgb.shape[:2] == dem.shape:
            rgb[~np.isfinite(dem)] = np.nan
        layers.append(georeference(rgb, transform, data.crs, "relief", name, description,
                                   opacity=float(st.session_state.get("as_rvt_overlay_opacity", 1.0))))
    elevation = None
    if dem is not None:
        try:
            elevation = elevation_grid(dem, transform, data.crs)
        except Exception:
            elevation = None
    return layers, elevation


def render_view_map(core, data, rgb, params):
    from airchgis.map.view import render_map

    overlay = st.session_state.get("as_rvt_last_rvt_rgb") if params["dataset"] == "Original" else rgb
    try:
        layers, elevation = terrain_map_layers(data, overlay, f"{params['method']} ({params['dataset']})",
                                               TOOL_HELP.get(params["method"], ""))
    except Exception as exc:
        st.warning(f"The map could not place this raster ({exc}); showing the image instead.")
        if overlay is not None:
            st.image(rgb_to_image(overlay), width="stretch")
        return
    if not layers and overlay is not None:
        st.image(rgb_to_image(overlay), width="stretch")
        return
    render_map(layers, basemap_tiles=satellite_template(core, params["basemap_year"]), elevation=elevation, height=640)


def image_data_url(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def dataset_options(data):
    out = []
    if data.loaded and data.dtm is not None:
        out.extend(["DTM", "Original"])
    if data.loaded and data.dsmf is not None:
        out.append("DSM_First")
    if data.loaded and data.dsml is not None:
        out.append("DSM_Last")
    if data.loaded and data.ndsm is not None:
        out.append("nDSM")
    if data.loaded and data.diff is not None:
        out.append("First-Last")
    order = ["DTM", "DSM_First", "DSM_Last", "nDSM", "First-Last", "Original"]
    return [name for name in order if name in out]


def available_methods(core):
    methods = ["Raw"]
    if hasattr(core.rvt.vis, "hillshade"):
        methods.append("Hillshade")
    if hasattr(core.rvt.vis, "multi_hillshade"):
        methods.append("Multi-Hillshade")
    if hasattr(core.rvt.vis, "slope") or hasattr(core.rvt.vis, "slope_aspect"):
        methods.append("Slope")
    if hasattr(core.rvt.vis, "sky_view_factor"):
        methods.extend(["Sky-View Factor", "Anisotropic Sky-View Factor", "Positive Openness"])
    if hasattr(core.rvt.vis, "slrm") or hasattr(core.rvt.vis, "local_relief_model"):
        methods.append("Simple Local Relief Model")
    if hasattr(core.rvt.vis, "msrm"):
        methods.append("Multi-Scale Relief Model")
    if hasattr(core.rvt.vis, "mstp"):
        methods.append("Multi-Scale Topographic Position")
    if hasattr(core.rvt.vis, "sky_illumination"):
        methods.append("Sky Illumination")
    if hasattr(core.rvt.vis, "local_dominance"):
        methods.append("Local Dominance")
    if hasattr(core.rvt.blend, "e3mstp"):
        methods.append("e3MSTP (RGB)")
    return methods


@st.cache_data(show_spinner=False, ttl=3600)
def cached_wayback_years(_core):
    layers = _core.load_wayback_layers()
    years = []
    seen = set()
    for item in layers:
        year = item.get("year")
        if year and year not in seen:
            years.append(year)
            seen.add(year)
    return years


@st.cache_data(show_spinner=False, ttl=3600)
def cached_wayback_layers(_core):
    return _core.load_wayback_layers()


def get_dataset_array(data, dataset):
    if dataset == "DTM":
        return data.dtm
    if dataset == "DSM_First":
        return data.dsmf
    if dataset == "DSM_Last":
        return data.dsml
    if dataset == "nDSM":
        return data.ndsm
    if dataset == "First-Last":
        return data.diff
    return None


def compose_current_view(core, data, params):
    dataset = params["dataset"]
    if dataset == "Original":
        return None, None, f"Original | Satellite {params['basemap_year']}"

    dem = get_dataset_array(data, dataset)
    if dem is None:
        raise RuntimeError("Dataset not available.")

    out = compute_raw_method(core, data, dem, params)
    if out.ndim == 3 or core.is_rgb_method(params["method"]):
        rgb = core.normalize_rgb01(out)
        return rgb, out, f"{dataset} | {params['method']} | RGB"

    disp = stretch_for_display(core, out, params)
    cmap = core.mpl.colormaps.get_cmap("gray_r" if params["invert"] else "gray").copy()
    rgba = cmap(np.nan_to_num(disp, nan=0.0))
    over_rgb = np.asarray(rgba[:, :, :3], dtype=np.float32)
    over_rgb[~np.isfinite(disp)] = 0.0

    finite = np.isfinite(out)
    if finite.any():
        status = f"{dataset} | {params['method']} | min {float(np.nanmin(out)):.4f} | max {float(np.nanmax(out)):.4f}"
    else:
        status = f"{dataset} | {params['method']}"
    return over_rgb, out, status


def compute_raw_method(core, data, dem, params):
    return core.as_float32(
        core.compute_method(
            params["method"],
            dem,
            float(data.res),
            float(params["azimuth"]),
            float(params["altitude"]),
            float(params["z_factor"]),
            float(params["radius"]),
            int(params["n_dir"]),
        )
    )


def stretch_for_display(core, arr, params):
    p_low = float(params["p_low"])
    p_high = float(params["p_high"])
    if p_high <= p_low:
        p_low, p_high = 2.0, 98.0
    return core.stretch01(core.as_float32(arr), p_low, p_high)


def satellite_for_data(core, data, params, width, height):
    bounds_ll = bounds_lonlat(core, data)
    if bounds_ll is None:
        return None
    template = satellite_template(core, params["basemap_year"])
    for zoom in core.SAT_ZOOMS_TRY:
        img = core.build_satellite_rgb(bounds_ll, zoom, tile_template=template)
        if img is None:
            continue
        img = img.resize((width, height), resample=Image.BILINEAR)
        return np.asarray(img, dtype=np.float32) / 255.0
    return None


def satellite_template(core, year):
    if year and year != "Current":
        for item in cached_wayback_layers(core):
            if item.get("year") == year:
                return item.get("template", core.ARCGIS_CURRENT_TILE_TEMPLATE)
    return core.ARCGIS_CURRENT_TILE_TEMPLATE


def bounds_lonlat(core, data):
    if data.bounds is None:
        return None
    if data.crs is not None and data.crs.to_string() != "EPSG:4326":
        try:
            b = core.rasterio.warp.transform_bounds(data.crs, "EPSG:4326", *data.bounds, densify_pts=21)
            return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
        except Exception:
            return data.bounds
    return data.bounds


def rgb_to_image(rgb):
    arr = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    return Image.fromarray((arr * 255.0).astype(np.uint8), mode="RGB")


def render_exports(core, data, params, rgb, raw_out):
    if params["dataset"] == "Original" or raw_out is None:
        return
    if st.button("Prepare download (GeoTIFF)", key="as_rvt_export_tiff_go"):
        st.session_state.as_rvt_export_tiff = str(export_tiff(core, data, params, raw_out))
    value = st.session_state.get("as_rvt_export_tiff")
    if value and Path(value).exists():
        st.download_button("Download GeoTIFF", Path(value).read_bytes(), file_name=Path(value).name, mime="image/tiff",
                           key="as_rvt_export_tiff_dl")
    with st.expander("Details"):
        st.caption(st.session_state.get("as_rvt_last_status", ""))
        if st.button("Prepare PNG image", key="as_rvt_export_png_go", disabled=rgb is None):
            st.session_state.as_rvt_export_png = str(export_png(core, params, rgb))
        png = st.session_state.get("as_rvt_export_png")
        if png and Path(png).exists():
            st.download_button("Download PNG", Path(png).read_bytes(), file_name=Path(png).name, mime="image/png",
                               key="as_rvt_export_png_dl")


def export_tiff(core, data, params, raw_out):
    if params["dataset"] == "Original":
        raise RuntimeError("TIFF export not available on Original.")
    out = raw_out
    if out is None:
        dem = get_dataset_array(data, params["dataset"])
        out = compute_raw_method(core, data, dem, params)
    out_dir = RVT_OUTPUT_DIR / "streamlit_tiff"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{current_place_label(params)}__{params['dataset']}__{clean_name(params['method'])}__{ts}.tif"
    path = out_dir / fname
    core.save_geotiff(path, out, data.profile)
    return path


def export_png(core, params, rgb):
    img = rgb_to_image(rgb)
    h, w = np.asarray(rgb).shape[:2]
    long_side = max(h, w)
    scale = 1
    if long_side < 1600:
        scale = 2
    if long_side < 900:
        scale = 3
    if scale > 1:
        img = img.resize((w * scale, h * scale), resample=Image.LANCZOS)
    out_dir = RVT_OUTPUT_DIR / "export_hq_png"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{current_place_label(params)}__{params['dataset']}__{clean_name(params['method'])}__HQ__{ts}.png"
    path = out_dir / fname
    img.save(path, format="PNG", optimize=True)
    return path


def run_batch(core, data):
    out_root = RVT_DIR / "output_rvt_batch"
    out_root.mkdir(parents=True, exist_ok=True)
    log_path = out_root / "batch_log.txt"
    logs = []
    try:
        res = float(data.res)
        if data.dtm is None or data.dsmf is None or data.dsml is None:
            raise RuntimeError("Incomplete inputs for batch.")
        if hasattr(core.rvt.vis, "hillshade"):
            hs = core.compute_method("Hillshade", data.dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
            core.save_geotiff(out_root / "1_DTM_Hillshade.tif", hs, data.profile)
        if hasattr(core.rvt.vis, "sky_view_factor"):
            svf = core.compute_method("Sky-View Factor", data.dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
            core.save_geotiff(out_root / "2_DTM_SkyViewFactor.tif", svf, data.profile)
        core.save_geotiff(out_root / "3_nDSM.tif", data.dsmf - data.dtm, data.profile)
        core.save_geotiff(out_root / "4_FirstMinusLast.tif", data.dsmf - data.dsml, data.profile)
        logs.append("Batch OK")
    except Exception as exc:
        logs.append(f"{type(exc).__name__}: {exc}")
    log_path.write_text("\n".join(logs), encoding="utf-8")
    return log_path


def render_method_grid(core, data, params):
    if params["dataset"] == "Original":
        st.info("Select a dataset other than Original.")
        return
    if st.button("Build method grid", type="primary", width="stretch"):
        with st.spinner("Computing method grid..."):
            path = build_method_grid(core, data, params)
        st.session_state.as_rvt_grid_path = str(path)

    grid_path = st.session_state.get("as_rvt_grid_path")
    if grid_path and Path(grid_path).exists():
        st.image(str(grid_path), width="stretch")
        st.download_button("Download grid", Path(grid_path).read_bytes(), file_name=Path(grid_path).name, mime="image/png")


def build_method_grid(core, data, params):
    dem = get_dataset_array(data, params["dataset"])
    if dem is None:
        raise RuntimeError("Dataset not available.")
    images = []
    thumb = 420
    for method in available_methods(core):
        try:
            local_params = dict(params)
            local_params["method"] = method
            out = compute_raw_method(core, data, dem, local_params)
            if out.ndim == 3 or core.is_rgb_method(method):
                rgb = core.normalize_rgb01(out)
            else:
                disp = stretch_for_display(core, out, params)
                cmap = core.mpl.colormaps.get_cmap("gray_r" if params["invert"] else "gray").copy()
                rgb = cmap(np.nan_to_num(disp, nan=0.0))[:, :, :3]
            images.append((method, rgb_to_image(rgb).resize((thumb, thumb), resample=Image.BILINEAR)))
        except Exception:
            continue
    if not images:
        raise RuntimeError("No computable method.")

    cols = int(math.ceil(math.sqrt(len(images))))
    rows = int(math.ceil(len(images) / cols))
    title_h = 44
    grid = Image.new("RGB", (cols * thumb, rows * (thumb + title_h)), "black")
    draw = ImageDraw.Draw(grid)
    for idx, (name, img) in enumerate(images):
        x = (idx % cols) * thumb
        y = (idx // cols) * (thumb + title_h)
        draw.text((x + 12, y + 12), name, fill="white")
        grid.paste(img, (x, y + title_h))
    out_dir = RVT_OUTPUT_DIR / "method_grid"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{current_place_label(params)}__method_grid__{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    grid.save(path, "PNG", optimize=True)
    return path


def render_3d_cloud(core, data, params):
    cloud_options = list(core.CLOUD_PREPROCESS_PROFILES.keys())
    cloud_key = st.selectbox(
        "Cloud",
        cloud_options,
        format_func=lambda key: core.CLOUD_PREPROCESS_PROFILES[key]["label"],
        key="as_rvt_cloud_key",
    )
    if st.button("Build 3D Cloud", type="primary", width="stretch"):
        with st.spinner("Preparing 3D Cloud..."):
            html_path, las_path, cloud_meta = build_3d_cloud(core, data, params, cloud_key)
        st.session_state.as_rvt_cloud_html = str(html_path)
        st.session_state.as_rvt_cloud_las = str(las_path)
        st.session_state.as_rvt_cloud_meta = cloud_meta

    html_path = st.session_state.get("as_rvt_cloud_html")
    if html_path and Path(html_path).exists():
        html = Path(html_path).read_text(encoding="utf-8")
        components.html(html, height=760, scrolling=True)
        las_path = st.session_state.get("as_rvt_cloud_las")
        if las_path and Path(las_path).exists():
            meta = st.session_state.get("as_rvt_cloud_meta") or {}
            total_points = int(meta.get("total_points") or 0)
            exported_points = int(meta.get("preview_points") or 0)
            if total_points and exported_points and exported_points < total_points:
                st.caption(f"Sampled .LAS: {exported_points:,} points of {total_points:,}.")
            st.download_button("Download .LAS", Path(las_path).read_bytes(), file_name=Path(las_path).name)

    render_3d_figure_export(data, params)
    render_research_export(data, params)


def render_3d_figure_export(data, params):

    from airchgis.enhance.screen import OUT_DIR, _write_input, session_log
    from airchgis.gis.tools import ToolError, run_tool

    st.markdown("**High-quality image for a paper (PDF or PNG)**")
    c1, c2 = st.columns([0.4, 0.6], vertical_alignment="bottom")
    fmt = c1.radio("Format", ["PDF", "PNG"], horizontal=True, key="as_rvt_fig_fmt")
    with st.expander("Advanced: camera, size, scale bar"):
        a1, a2, a3 = st.columns(3)
        azimuth = a1.slider("Camera direction (degrees)", -180.0, 180.0, -44.0, key="as_rvt_fig_az",
                            help="-44 = from the south-east, as in the 3D viewer at start.")
        elevation = a2.slider("Camera height (degrees)", 5.0, 90.0, 29.0, key="as_rvt_fig_el")
        ve = a3.number_input("Vertical exaggeration (0 = as in the 3D viewer)", 0.0, 20.0, 0.0, 0.1, key="as_rvt_fig_ve")
        b1, b2 = st.columns(2)
        dpi = b1.selectbox("Resolution (dpi)", [300, 600, 150], key="as_rvt_fig_dpi")
        width_mm = b2.number_input("Width (mm; 190 = full page, 90 = one column)", 40.0, 500.0, 190.0, 5.0, key="as_rvt_fig_w")
        d1, d2 = st.columns(2)
        scale_bar = d1.checkbox("Scale bar", True, key="as_rvt_fig_sb")
        north = d2.checkbox("North arrow", True, key="as_rvt_fig_na")
        caption = st.text_input("Caption (empty = source file, CRS and vertical exaggeration)", "", key="as_rvt_fig_cap")
    if c2.button("Download high-quality image", type="primary", key="as_rvt_fig_go"):
        try:
            from airchgis.enhance.metrics import zero_nodata

            dtm, profile, crs = current_loaded_dtm_surface(data)
            dtm, _ = zero_nodata(dtm)
            label = current_place_label(params)
            dem_path = _write_input(np.asarray(dtm, dtype=np.float32), profile, crs, f"{label}_figure_dtm")
            drape_path = None
            last = st.session_state.get("as_rvt_last_out")
            if params.get("tool") != BEST_VIEW_TOOL and last is not None and np.ndim(last) == 2 and np.shape(last) == np.shape(dtm):
                drape_path = str(_write_input(np.asarray(last, dtype=np.float32), profile, crs, f"{label}_figure_drape"))
            out = OUT_DIR / f"{label}_3D_{datetime.now():%Y%m%d_%H%M%S}.{fmt.lower()}"
            kw = dict(input=str(dem_path), output=str(out), azimuth=float(azimuth), elevation=float(elevation),
                      dpi=int(dpi), width_mm=float(width_mm), scale_bar=bool(scale_bar), north_arrow=bool(north))
            if drape_path:
                kw["drape"] = drape_path
            if ve > 0:
                kw["vertical_exaggeration"] = float(ve)
            if caption.strip():
                kw["caption"] = caption.strip()
            with st.spinner("Rendering the image..."):
                r = run_tool("export_3d_figure", log=session_log(), **kw)
            st.session_state.as_rvt_fig = r["outputs"]
        except (ToolError, RuntimeError) as exc:
            st.error(str(exc))
    fig = st.session_state.get("as_rvt_fig")
    if fig and Path(fig["output"]).exists():
        st.download_button(f"Save {Path(fig['output']).name}", Path(fig["output"]).read_bytes(), file_name=Path(fig["output"]).name,
                           mime="application/pdf" if fig["format"] == "pdf" else "image/png", key="as_rvt_fig_dl")
        st.caption(fig["note"])


def render_research_export(data, params):
    with st.expander("Export 3D for research"):
        st.caption(
            "Georeferenced point cloud (LAZ/LAS, PLY), terrain mesh (glTF .glb) and a JSON metadata file "
            "(source, CRS, date, visualization, vertical exaggeration). Opens in QGIS 3D, CloudCompare and Blender; "
            "the .zip can be archived on Zenodo to get a DOI."
        )
        col1, col2 = st.columns(2)
        exaggeration = col1.number_input("Vertical exaggeration", 0.1, 20.0, 1.0, 0.5, key="as_rvt_export3d_ve")
        acquisition = col2.text_input("Acquisition date (optional)", key="as_rvt_export3d_date")
        source = st.text_input("Data source and licence (optional)", key="as_rvt_export3d_source")
        if st.button("Build research package", key="as_rvt_export3d_go"):
            from airchgis.terrain.export3d import export_terrain_3d, zip_package

            dtm, profile, crs = current_loaded_dtm_surface(data)
            stem = f"{current_place_label(params)}__3D__{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            out_dir = RVT_OUTPUT_DIR / "3d_research" / stem
            with st.spinner("Exporting 3D data..."):
                meta = export_terrain_3d(
                    dtm, profile["transform"], crs, out_dir, stem=stem, nodata=profile.get("nodata"),
                    vertical_exaggeration=float(exaggeration), visualization="DTM (no relief visualization)",
                    source=source or ", ".join(str(p) for p in (data.src_dtm_paths or [])) or None,
                    acquisition_date=acquisition or None,
                )
                st.session_state.as_rvt_export3d_zip = str(zip_package(meta, out_dir.with_suffix(".zip")))
        zip_path = st.session_state.get("as_rvt_export3d_zip")
        if zip_path and Path(zip_path).exists():
            st.download_button("Download research package (.zip)", Path(zip_path).read_bytes(), file_name=Path(zip_path).name,
                               key="as_rvt_export3d_dl")


def build_3d_cloud(core, data, params, cloud_key, ai=None, show_ai=False, adaptive_ve=False):
    dtm, profile, crs = current_loaded_dtm_surface(data)
    out_dir = RVT_OUTPUT_DIR / "3d_cloud"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{current_place_label(params)}__3DCloud__{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    las_path = out_dir / f"{stem}.las"
    html_path = out_dir / f"{stem}__{cloud_key}.html"
    las_meta = core.export_lads_las(
        dtm,
        profile,
        crs,
        las_path,
        target_crs=core.LADS_TARGET_CRS,
        cloud_preprocess_key="original",
        max_points=WEB_3D_LAS_MAX_POINTS,
    )
    terrain_grid = core.build_browser_terrain_grid(
        dtm,
        profile,
        crs,
        target_crs=core.LADS_TARGET_CRS,
        max_side=min(core.LADS_BROWSER_MAX_SIDE, WEB_3D_BROWSER_MAX_SIDE),
        cloud_preprocess_key=cloud_key,
        ai=ai,
        show_ai=show_ai,
        adaptive_ve=adaptive_ve,
    )
    from airchgis.terrain.imagery import ATTRIBUTION, drape_imagery

    try:
        terrain_grid["basemap_colors"] = drape_imagery(profile, crs, dtm.shape, terrain_grid,
                                                       satellite_template(core, "Current"))
        terrain_grid["basemap_attribution"] = ATTRIBUTION
    except Exception as exc:
        logging.getLogger(__name__).warning("3D satellite imagery unavailable: %s", exc)
    core.write_browser_cloud_viewer(
        html_path,
        terrain_grid,
        las_href=quote(las_path.name),
        variant_options=[],
        current_variant_key="original",
        cloud_preprocess_options=[],
        current_cloud_preprocess_key=cloud_key,
    )
    return html_path, las_path, {
        "total_points": int(las_meta.get("total_points") or 0),
        "preview_points": int(las_meta.get("preview_points") or 0),
        "sample_step": int(las_meta.get("sample_step") or 1),
    }


def current_loaded_dtm_surface(data):
    if data.dtm is None:
        raise RuntimeError("DTM not loaded.")
    if data.profile is None or data.profile.get("transform") is None:
        raise RuntimeError("Georeferenced DTM profile not available.")
    if data.crs is None:
        raise RuntimeError("DTM CRS not available.")
    return data.dtm, data.profile, data.crs


def load_original_dtm_surface(core, data):
    src_paths = data.src_original_dtm_paths or data.src_dtm_paths
    if not src_paths:
        raise RuntimeError("Original DTM source not available.")
    paths = [Path(p).expanduser().resolve() for p in src_paths if p]
    dtm, _res, profile, _nodata, bounds, crs = core.load_raster_source(paths)
    if data.area_geojson_path:
        dummy = np.zeros_like(dtm, dtype=np.float32)
        tile = {
            "DTM": dtm,
            "DSM_First": dummy,
            "DSM_Last": dummy,
            "nDSM": dummy,
            "First-Last": dummy,
            "profile": profile,
            "bounds": bounds,
            "crs": crs,
        }
        tile = core.clip_tile_to_geojson(tile, Path(data.area_geojson_path).expanduser().resolve())
        dtm = tile["DTM"]
        profile = tile["profile"]
        crs = tile["crs"]
    return dtm, profile, crs


def render_report(core, data, params, rgb):
    if rgb is None:
        st.info("The image report is available on RVT layers. In Original you can still use coordinates and measuring on the map.")
        with st.expander("Coordinates and measuring"):
            render_measure_tools(core, data)
        return

    st.session_state.as_rvt_report_items = st.session_state.get("as_rvt_report_items") or []
    with st.form("as_rvt_report_form", clear_on_submit=False):
        name = st.text_input("Place name", key="as_rvt_report_name")
        notes = st.text_area("Note", key="as_rvt_report_notes", height=90)
        max_row = int(data.dtm.shape[0] - 1)
        max_col = int(data.dtm.shape[1] - 1)
        last_click = st.session_state.get("as_rvt_last_click_info") or {}
        default_row = min(max(int(last_click.get("row", max_row // 2)), 0), max_row)
        default_col = min(max(int(last_click.get("col", max_col // 2)), 0), max_col)
        c1, c2 = st.columns(2)
        with c1:
            row = st.number_input("Row", min_value=0, max_value=max_row, value=default_row, step=1)
        with c2:
            col = st.number_input("Column", min_value=0, max_value=max_col, value=default_col, step=1)
        submitted = st.form_submit_button("Add point")

    if submitted:
        if not name.strip():
            st.error("Enter the place name.")
        else:
            item = build_report_item(core, data, params, rgb, int(row), int(col), name.strip(), notes.strip())
            st.session_state.as_rvt_report_items.append(item)
            st.rerun()

    items = st.session_state.as_rvt_report_items
    if items:
        st.dataframe(
            [{"n": i + 1, "nome": item["name"], "coordinate": item["coords_dms"], "scenario": f"{item['dataset']} | {item['method']}"} for i, item in enumerate(items)],
            hide_index=True,
            width="stretch",
        )
        remove_idx = st.number_input("Remove point", min_value=1, max_value=len(items), value=1, step=1)
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("Remove selected", width="stretch"):
                del items[int(remove_idx) - 1]
                st.rerun()
        with col_b:
            if st.button("Clear all", width="stretch"):
                items.clear()
                st.rerun()
        with col_c:
            if st.button("Generate PDF", width="stretch"):
                path = generate_report_pdf(core, params, items)
                st.session_state.as_rvt_report_pdf = str(path)
        if st.button("Export KML", width="stretch"):
            path = export_report_kml(core, params, items)
            st.session_state.as_rvt_report_kml = str(path)

    for key, label, mime in [
        ("as_rvt_report_pdf", "Download PDF", "application/pdf"),
        ("as_rvt_report_kml", "Download KML", "application/vnd.google-earth.kml+xml"),
    ]:
        path = st.session_state.get(key)
        if path and Path(path).exists():
            st.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, mime=mime)

    with st.expander("Coordinates and measuring"):
        render_measure_tools(core, data)


def render_measure_tools(core, data):
    max_row = int(data.dtm.shape[0] - 1)
    max_col = int(data.dtm.shape[1] - 1)
    cols = st.columns(4)
    with cols[0]:
        r1 = st.number_input("Row A", min_value=0, max_value=max_row, value=max_row // 3, step=1)
    with cols[1]:
        c1 = st.number_input("Col A", min_value=0, max_value=max_col, value=max_col // 3, step=1)
    with cols[2]:
        r2 = st.number_input("Row B", min_value=0, max_value=max_row, value=(max_row * 2) // 3, step=1)
    with cols[3]:
        c2 = st.number_input("Col B", min_value=0, max_value=max_col, value=(max_col * 2) // 3, step=1)
    p1 = pixel_geo(core, data, int(r1), int(c1))
    p2 = pixel_geo(core, data, int(r2), int(c2))
    dist = math.hypot(float(p1["x"]) - float(p2["x"]), float(p1["y"]) - float(p2["y"]))
    st.write(f"A: {p1['dms']} | B: {p2['dms']} | Distance: {dist:.2f} m")


def build_report_item(core, data, params, rgb, row, col, name, notes):
    coords = pixel_geo(core, data, row, col)
    current_img = capture_report_crop(core, rgb, col, row)
    try:
        original_rgb = satellite_for_data(core, data, {"basemap_year": params["basemap_year"]}, data.dtm.shape[1], data.dtm.shape[0])
        if original_rgb is None:
            original_rgb = rgb
    except Exception:
        original_rgb = rgb
    original_img = capture_report_crop(core, original_rgb, col, row)
    return {
        "name": name,
        "notes": notes,
        "coords_dms": coords["dms"],
        "lat": coords["lat"],
        "lon": coords["lon"],
        "current_crop_img": current_img,
        "original_crop_img": original_img,
        "dataset": params["dataset"],
        "method": params["method"],
        "place": current_place_label(params),
        "original_year": params["basemap_year"],
    }


def pixel_geo(core, data, row, col):
    x, y = core.rasterio.transform.xy(data.profile["transform"], int(row), int(col), offset="center")
    lon = float(x)
    lat = float(y)
    if data.crs is not None and data.crs.to_string() != "EPSG:4326":
        lon_vals, lat_vals = core.rasterio.warp.transform(data.crs, "EPSG:4326", [x], [y])
        lon = float(lon_vals[0])
        lat = float(lat_vals[0])
    lat_dms = core.decimal_to_dms(lat, "N", "S")
    lon_dms = core.decimal_to_dms(lon, "E", "W")
    return {"x": float(x), "y": float(y), "lat": lat, "lon": lon, "dms": f"{lat_dms}  {lon_dms}", "row": int(row), "col": int(col)}


def click_info(core, data, click):
    try:
        lat = float(click["lat"])
        lon = float(click["lng"])
    except Exception:
        return None

    x = lon
    y = lat
    if data.crs is not None and data.crs.to_string() != "EPSG:4326":
        try:
            xs, ys = core.rasterio.warp.transform("EPSG:4326", data.crs, [lon], [lat])
            x = float(xs[0])
            y = float(ys[0])
        except Exception:
            return None

    try:
        row, col = core.rasterio.transform.rowcol(data.profile["transform"], x, y)
    except Exception:
        return None

    row = int(row)
    col = int(col)
    if data.dtm is None or row < 0 or col < 0 or row >= data.dtm.shape[0] or col >= data.dtm.shape[1]:
        return None

    info = pixel_geo(core, data, row, col)
    value = float(data.dtm[row, col])
    info["elevation"] = value if np.isfinite(value) else None
    return info


def capture_report_crop(core, rgb01, col, row):
    arr = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
    h, w = arr.shape[:2]
    radius = core.REPORT_CROP_RADIUS_PX
    x0 = max(0, col - radius)
    x1 = min(w, col + radius + 1)
    y0 = max(0, row - radius)
    y1 = min(h, row + radius + 1)
    crop = (arr[y0:y1, x0:x1, :3] * 255.0).astype(np.uint8)
    img = Image.fromarray(crop, mode="RGB").resize((core.REPORT_CROP_OUTPUT_SIZE, core.REPORT_CROP_OUTPUT_SIZE), resample=Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    cx = (col - x0) / max(1, x1 - x0)
    cy = (row - y0) / max(1, y1 - y0)
    px = int(round(cx * core.REPORT_CROP_OUTPUT_SIZE))
    py = int(round(cy * core.REPORT_CROP_OUTPUT_SIZE))
    r = 18
    draw.ellipse((px - r, py - r, px + r, py + r), outline=(255, 40, 40), width=4)
    draw.line((px - 28, py, px - 8, py), fill=(255, 40, 40), width=3)
    draw.line((px + 8, py, px + 28, py), fill=(255, 40, 40), width=3)
    draw.line((px, py - 28, px, py - 8), fill=(255, 40, 40), width=3)
    draw.line((px, py + 8, px, py + 28), fill=(255, 40, 40), width=3)
    return img


def generate_report_pdf(core, params, items):
    pages = [build_report_page(core, item, idx + 1, len(items)).convert("RGB") for idx, item in enumerate(items)]
    out_dir = RVT_OUTPUT_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"exploration_report__{current_place_label(params)}__{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=150.0)
    return path


def build_report_page(core, item, index, total):
    page = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(page)
    title_font = core.load_pdf_font(44)
    section_font = core.load_pdf_font(34)
    text_font = core.load_pdf_font(26)

    draw.rectangle((70, 70, 1584, 2269), outline=(30, 30, 30), width=3)
    draw.text((110, 110), f"Exploration report  {index}/{total}", fill=(20, 20, 20), font=title_font)
    draw.text((110, 190), f"Place: {item['name']}", fill=(20, 20, 20), font=section_font)
    draw.text((110, 250), f"Coordinates: {item['coords_dms']}", fill=(20, 20, 20), font=text_font)
    draw.text((110, 295), f"Scenario: {item['place']} | {item['dataset']} | {item['method']} | Original {item.get('original_year', 'Current')}", fill=(20, 20, 20), font=text_font)

    left_x = 110
    right_x = 824
    img_y = 420
    label_y = 370
    draw.text((left_x, label_y), "Original", fill=(20, 20, 20), font=section_font)
    draw.text((right_x, label_y), "Current filter", fill=(20, 20, 20), font=section_font)
    page.paste(item["original_crop_img"], (left_x, img_y))
    page.paste(item["current_crop_img"], (right_x, img_y))
    draw.rectangle((left_x, img_y, left_x + item["original_crop_img"].width, img_y + item["original_crop_img"].height), outline=(40, 40, 40), width=2)
    draw.rectangle((right_x, img_y, right_x + item["current_crop_img"].width, img_y + item["current_crop_img"].height), outline=(40, 40, 40), width=2)

    note_y = 1180
    draw.text((110, note_y), "Note", fill=(20, 20, 20), font=section_font)
    box = (110, note_y + 40, 1544, 2140)
    draw.rectangle(box, outline=(80, 80, 80), width=2)
    lines = core.wrap_text_lines(draw, item.get("notes") or "-", text_font, box[2] - box[0] - 30)
    y = box[1] + 18
    for line in lines:
        draw.text((box[0] + 15, y), line, fill=(30, 30, 30), font=text_font)
        y += 38
        if y > box[3] - 35:
            break
    return page


def export_report_kml(core, params, items):
    out_dir = RVT_OUTPUT_DIR / "maps"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"poi_mymaps__{current_place_label(params)}__{datetime.now().strftime('%Y%m%d_%H%M%S')}.kml"
    doc_name = xml_escape(f"Points of interest - {current_place_label(params)}")
    placemarks = []
    for idx, item in enumerate(items, start=1):
        name = xml_escape(item.get("name") or f"Point {idx}")
        notes = item.get("notes") or "-"
        coords_dms = item.get("coords_dms") or "-"
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
        maps_url = core.google_maps_point_url(lat, lon)
        description = xml_escape(
            "\n".join(
                [
                    f"Coordinates: {coords_dms}",
                    f"Lat/Lon: {lat:.8f}, {lon:.8f}",
                    f"Scenario: {item.get('place')} | {item.get('dataset')} | {item.get('method')}",
                    f"Google Maps: {maps_url}",
                    "",
                    f"Note: {notes}",
                ]
            )
        )
        placemarks.append(
            f"""
    <Placemark>
      <name>{name}</name>
      <styleUrl>#poi-red</styleUrl>
      <description>{description}</description>
      <Point>
        <coordinates>{lon:.8f},{lat:.8f},0</coordinates>
      </Point>
    </Placemark>""".rstrip()
        )
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{doc_name}</name>
    <Style id="poi-red">
      <IconStyle>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle>
        <scale>1.0</scale>
      </LabelStyle>
    </Style>
{chr(10).join(placemarks)}
  </Document>
</kml>
"""
    path.write_text(kml, encoding="utf-8")
    return path


def apply_archaeology_preset(core):
    methods = available_methods(core)
    preferred = ["Hillshade", "Simple Local Relief Model", "Sky-View Factor", "Multi-Hillshade"]
    st.session_state.as_rvt_dataset = "DTM"
    st.session_state.as_rvt_method = next((m for m in preferred if m in methods), methods[0])
    st.session_state.as_rvt_tool = st.session_state.as_rvt_method
    for k in ("as_rvt_azimuth__w", "as_rvt_radius__w"):
        st.session_state.pop(k, None)
    st.session_state.as_rvt_basemap_on = False
    st.session_state.as_rvt_invert = False
    st.session_state.as_rvt_azimuth = 315.0
    st.session_state.as_rvt_altitude = 24.0
    st.session_state.as_rvt_z_factor = 1.8
    st.session_state.as_rvt_radius = 20.0
    st.session_state.as_rvt_n_dir = 32
    st.session_state.as_rvt_p_low = 0.8
    st.session_state.as_rvt_p_high = 99.5


def apply_rectangles_preset(core):
    methods = available_methods(core)
    preferred = ["Sky-View Factor", "Anisotropic Sky-View Factor", "Simple Local Relief Model", "Hillshade", "Multi-Hillshade"]
    st.session_state.as_rvt_dataset = "DTM"
    st.session_state.as_rvt_method = next((m for m in preferred if m in methods), methods[0])
    st.session_state.as_rvt_tool = st.session_state.as_rvt_method
    for k in ("as_rvt_azimuth__w", "as_rvt_radius__w"):
        st.session_state.pop(k, None)
    st.session_state.as_rvt_basemap_on = False
    st.session_state.as_rvt_invert = False
    st.session_state.as_rvt_azimuth = 330.0
    st.session_state.as_rvt_altitude = 18.0
    st.session_state.as_rvt_z_factor = 2.2
    st.session_state.as_rvt_radius = 24.0
    st.session_state.as_rvt_n_dir = 32
    st.session_state.as_rvt_p_low = 0.2
    st.session_state.as_rvt_p_high = 99.8


def current_place_label(params):
    mode = params.get("source_mode")
    payload = params.get("source_payload") or {}
    if mode == "Database":
        label = payload.get("place") or "database"
    elif mode == "DTM from map":
        path = payload.get("generated_dtm") or "dtm_da_mappa"
        label = Path(path).stem
    else:
        uploads = payload.get("uploads") or {}
        dtm = uploads.get("DTM") or []
        label = Path(dtm[0]).stem if dtm else "upload"
    return clean_name(label)


def clean_name(value):
    text = str(value or "rvt").replace(" ", "_").replace("-", "_")
    return "".join(ch for ch in text if ch.isalnum() or ch in "._").strip("._") or "rvt"
