import base64
import hashlib
import importlib.util
import io
import json
import math
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import folium
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from folium.plugins import Draw, MeasureControl
from PIL import Image, ImageDraw
from streamlit_folium import st_folium
from xml.sax.saxutils import escape as xml_escape

from .paths import RVT_DIR


RVT_UPLOAD_DIR = RVT_DIR / ".streamlit_uploads"
RVT_OUTPUT_DIR = RVT_DIR / "output_rvt_gui"
WEB_3D_LAS_MAX_POINTS = 500_000
WEB_3D_BROWSER_MAX_SIDE = 950


def render_rvt_web():
    core = load_rvt_core()
    init_rvt_state(core)

    controls, viewer = st.columns([0.28, 0.72], gap="large")
    with controls:
        params = render_rvt_controls(core)

    with viewer:
        if params["source_mode"] == "DTM from map" and not params["source_payload"].get("generated_dtm"):
            render_public_terrain_sources()
            st.markdown("**Italy: regional DTM, cut from the map**")
            render_regional_dtm_selector(core)
            return

        data = current_rvt_data(core, params)
        if data is None or not data.loaded:
            msg = getattr(data, "error", None) if data is not None else None
            st.warning(msg or "No RVT data loaded.")
            return

        render_rvt_viewer(core, data, params)


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


def init_rvt_state(core):
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

    places = core.list_database_places(RVT_DIR)
    if "as_rvt_place" not in st.session_state:
        st.session_state.as_rvt_place = places[0] if places else ""


def render_rvt_controls(core):
    source_mode = st.radio(
        "Source",
        ["Upload", "DTM from map", "Database"],
        format_func={
            "Upload": "Upload your files",
            "DTM from map": "Download from a public source",
            "Database": "Example data",
        }.get,
        key="as_rvt_source_mode",
        horizontal=True,
    )

    source_payload = {}
    if source_mode == "Database":
        places = core.list_database_places(RVT_DIR)
        if places:
            if st.session_state.as_rvt_place not in places:
                st.session_state.as_rvt_place = places[0]
            source_payload["place"] = st.selectbox(
                "Place",
                places,
                key="as_rvt_place",
            )
        else:
            st.warning("RVT database is empty.")
            source_payload["place"] = ""

    elif source_mode == "Upload":
        source_payload["uploads"] = render_upload_controls(core)

    else:
        generated = st.session_state.as_rvt_generated_dtm
        source_payload["generated_dtm"] = generated
        if generated:
            st.caption(Path(generated).name)
            if st.button("New area", width="stretch"):
                st.session_state.as_rvt_generated_dtm = None
                st.session_state.as_rvt_data_sig = None
                st.rerun()

    mode = st.selectbox("Base", core.BASE_IMAGE_OPTIONS, index=1, key="as_rvt_base_mode")

    preset_cols = st.columns(2)
    with preset_cols[0]:
        if st.button("Preset Arch", width="stretch"):
            apply_archaeology_preset(core)
            st.rerun()
    with preset_cols[1]:
        if st.button("Preset Rect/Ditches", width="stretch"):
            apply_rectangles_preset(core)
            st.rerun()

    method_values = available_methods(core)
    dataset_values = ["DTM", "DSM_First", "DSM_Last", "nDSM", "First-Last", "Original"]
    waiting_for_map_dtm = source_mode == "DTM from map" and not source_payload.get("generated_dtm")

    if waiting_for_map_dtm:
        st.session_state.as_rvt_dataset = "DTM"
        dataset = "DTM"
        method = st.session_state.as_rvt_method
        if method not in method_values:
            method = "Hillshade" if "Hillshade" in method_values else method_values[0]
            st.session_state.as_rvt_method = method
    else:
        dataset = st.radio("Dataset", dataset_values, key="as_rvt_dataset", horizontal=False)
        method = st.selectbox("RVT method", method_values, key="as_rvt_method")

    is_original = dataset == "Original"
    azimuth = st.slider("Azimuth", 0.0, 360.0, key="as_rvt_azimuth", disabled=is_original)
    altitude = st.slider("Altitude", 0.0, 90.0, key="as_rvt_altitude", disabled=is_original)
    z_factor = st.slider("Z-factor", 0.1, 10.0, key="as_rvt_z_factor", disabled=is_original)
    radius = st.slider("Radius", 1.0, 200.0, key="as_rvt_radius", disabled=is_original)
    n_dir = st.slider("Directions", 4, 64, key="as_rvt_n_dir", disabled=is_original)
    p_low = st.slider("Stretch low (p)", 0.0, 20.0, key="as_rvt_p_low", disabled=is_original)
    p_high = st.slider("Stretch high (p)", 80.0, 100.0, key="as_rvt_p_high", disabled=is_original)
    invert = st.checkbox("Invert", key="as_rvt_invert", disabled=is_original)

    basemap_years = ["Current"] + cached_wayback_years(core)
    basemap_year = st.selectbox("Original", basemap_years, key="as_rvt_basemap_year")
    overlay_opacity = float(st.session_state.as_rvt_overlay_opacity)

    return {
        "source_mode": source_mode,
        "source_payload": source_payload,
        "base_mode": mode,
        "dataset": dataset,
        "method": method,
        "azimuth": azimuth,
        "altitude": altitude,
        "z_factor": z_factor,
        "radius": radius,
        "n_dir": n_dir,
        "p_low": p_low,
        "p_high": p_high,
        "invert": invert,
        "basemap_on": overlay_opacity < 1.0,
        "basemap_mix": 1.0 - overlay_opacity,
        "overlay_opacity": overlay_opacity,
        "basemap_year": basemap_year,
    }


def render_upload_controls(core):
    from airchgis import data_input as di
    from airchgis.input_ui import render_file_input

    st.caption("Your own terrain data, from any country and in any coordinate system. DSM First/Last are optional.")
    uploads = {}
    specs = [
        ("DTM", "DTM (GeoTIFF, ASCII grid, zip) or point cloud (LAS/LAZ)"),
        ("DSM_First", "DSM First (optional)"),
        ("DSM_Last", "DSM Last (optional)"),
    ]
    for key, label in specs:
        exts = {".tif", ".tiff", ".asc", ".zip"} | ({".las", ".laz"} if key == "DTM" else set())
        with st.expander(label, expanded=key == "DTM"):
            paths = render_file_input(label, exts, f"as_rvt_in_{key}", f"terrain_{key}")
            if key == "DTM" and any(p.suffix.lower() in di.POINT_CLOUD_EXTS for p in paths):
                res = st.number_input("DTM cell size from the point cloud (m)", 0.1, 10.0, 1.0, 0.1, key="as_rvt_las_res")
            out = []
            for p in paths:
                try:
                    if p.suffix.lower() == ".zip":
                        out.extend(extract_zip_rasters(core, p, key))
                    elif p.suffix.lower() in di.POINT_CLOUD_EXTS:
                        tif = di.UPLOAD_DIR / "dtm_from_point_cloud" / f"{p.stem}_{res:g}m.tif"
                        if not tif.exists():
                            with st.spinner(f"Gridding {p.name} into a DTM..."):
                                di.rasterize_point_cloud(p, tif, resolution=res)
                        out.append(str(tif))
                    else:
                        out.append(str(p))
                    info = di.describe_raster(out[-1])
                    st.caption(f"{p.name}: {di.plain_description(info)}")
                except Exception as exc:
                    st.error(f"{p.name}: cannot be read ({exc}).")
            uploads[key] = out
    return uploads


def extract_zip_rasters(core, path, dataset_key):
    extract_dir = Path(path).with_suffix("")
    marker = extract_dir / ".unzipped"
    if not marker.exists():
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(extract_dir)
        marker.write_text("ok", encoding="utf-8")
    return [str(p) for p in core.list_rasters(extract_dir)]


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
    st.session_state.as_rvt_dataset = "DTM"
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
    available = dataset_options(data)
    if params["dataset"] not in available:
        st.info("Dataset not available for this source.")
        params = dict(params)
        params["dataset"] = available[0] if available else "DTM"

    try:
        if params["dataset"] == "Original":
            rgb, raw_out, status = compose_current_view(core, data, params)
        else:
            with st.spinner("Computing RVT..."):
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

    action_tabs = st.tabs(["Enhance & best view", "3D view", "Export"])
    with action_tabs[0]:
        render_enhance(data, params)
    with action_tabs[1]:
        render_3d_cloud(core, data, params)
    with action_tabs[2]:
        render_exports(core, data, params, rgb, raw_out)


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
    tool_cols = st.columns([0.08, 0.08, 0.32, 0.52], vertical_alignment="center")
    with tool_cols[0]:
        if st.button(
            "📍",
            key="as_rvt_coordinate_tool_button",
            help="Coordinates",
            type="primary" if st.session_state.as_rvt_image_tool == "coordinate" else "secondary",
            width="stretch",
        ):
            st.session_state.as_rvt_image_tool = "coordinate"
            st.rerun()
    with tool_cols[1]:
        if st.button(
            "📏",
            key="as_rvt_measure_tool_button",
            help="Measure",
            type="primary" if st.session_state.as_rvt_image_tool == "measure" else "secondary",
            width="stretch",
        ):
            st.session_state.as_rvt_image_tool = "measure"
            st.rerun()
    with tool_cols[2]:
        st.slider(
            "RVT opacity over Original",
            0.0,
            1.0,
            key="as_rvt_overlay_opacity",
            help="1 shows only RVT, 0 shows only the underlying original image.",
        )

    render_view_map(core, data, rgb, params)

    info = st.session_state.get("as_rvt_last_click_info")
    if info:
        elevation = info.get("elevation")
        elevation_text = "" if elevation is None else f" | quota {elevation:.2f} m"
        st.code(
            f"{info['dms']} | lat {info['lat']:.8f}, lon {info['lon']:.8f}"
            f" | riga {info['row']}, colonna {info['col']}{elevation_text}",
            language=None,
        )


def render_view_map(core, data, rgb, params):
    bounds = bounds_lonlat(core, data)
    if bounds is None:
        if rgb is None:
            st.warning("Original map not available for this area.")
        else:
            st.image(rgb_to_image(rgb), width="stretch")
        return

    left, bottom, right, top = bounds
    center = [(bottom + top) / 2.0, (left + right) / 2.0]
    fmap = folium.Map(location=center, zoom_start=16, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=satellite_template(core, params["basemap_year"]),
        attr="Esri",
        name=f"Original {params['basemap_year']}",
        show=True,
    ).add_to(fmap)
    overlay_rgb = st.session_state.get("as_rvt_last_rvt_rgb") if params["dataset"] == "Original" else rgb
    overlay_opacity = max(0.0, min(1.0, float(params["overlay_opacity"])))
    if overlay_rgb is not None and overlay_opacity > 0.0:
        folium.raster_layers.ImageOverlay(
            image=image_data_url(rgb_to_image(overlay_rgb)),
            bounds=[[bottom, left], [top, right]],
            name="RVT",
            opacity=overlay_opacity,
            interactive=False,
        ).add_to(fmap)
    folium.FitBounds([[bottom, left], [top, right]]).add_to(fmap)

    info = st.session_state.get("as_rvt_last_click_info")
    if info:
        folium.CircleMarker(
            location=[info["lat"], info["lon"]],
            radius=6,
            color="#ff3030",
            fill=True,
            fill_color="#ff3030",
            fill_opacity=0.9,
            tooltip=info["dms"],
        ).add_to(fmap)

    if st.session_state.as_rvt_image_tool == "measure":
        MeasureControl(
            position="topleft",
            primary_length_unit="meters",
            secondary_length_unit="kilometers",
            primary_area_unit="sqmeters",
            secondary_area_unit="hectares",
            active_color="#ffdf4d",
            completed_color="#ff3030",
        ).add_to(fmap)

    folium.LayerControl(collapsed=True).add_to(fmap)
    result = st_folium(
        fmap,
        width=1200,
        height=720,
        key=f"as_rvt_view_map_{st.session_state.as_rvt_image_tool}_{params['dataset']}_{params['basemap_year']}_{int(overlay_opacity * 100)}",
        returned_objects=["last_clicked"],
    )
    click = result.get("last_clicked") if result else None
    if click:
        info = click_info(core, data, click)
        if info:
            st.session_state.as_rvt_last_click_info = info


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
    st.caption("Save the current view. For the cleaned terrain, the best view and the fused view, use the Enhance & best view tab.")
    cols = st.columns(2)
    with cols[0]:
        if st.button("Save as GeoTIFF", width="stretch", disabled=params["dataset"] == "Original"):
            path = export_tiff(core, data, params, raw_out)
            st.session_state.as_rvt_export_tiff = str(path)
    with cols[1]:
        if st.button("Save as PNG image", width="stretch", disabled=rgb is None):
            path = export_png(core, params, rgb)
            st.session_state.as_rvt_export_png = str(path)

    for state_key, label, mime in [
        ("as_rvt_export_tiff", "Download TIFF", "image/tiff"),
        ("as_rvt_export_png", "Download PNG", "image/png"),
    ]:
        value = st.session_state.get(state_key)
        if value and Path(value).exists():
            st.download_button(label, Path(value).read_bytes(), file_name=Path(value).name, mime=mime)
            st.caption(value)

    if st.session_state.get("as_rvt_batch_log"):
        st.caption(st.session_state.as_rvt_batch_log)


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

    render_research_export(data, params)


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


def build_3d_cloud(core, data, params, cloud_key):
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
    )
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
