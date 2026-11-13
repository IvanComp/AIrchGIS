"""Field-marks screen for the user's own images (upload first, no Earth Engine)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from airchgis import data_input as di
from airchgis import sources
from airchgis.enhance.multispectral import mask_scene
from airchgis.enhance.screen import render_scene_quality
from airchgis.gis.guardrails import check_resolvability
from airchgis.input_ui import render_file_input
from airchgis.spectral import local_engine as le

OUT_DIR = di.WORKSPACE_DIR / "outputs" / "field_marks"
TARGETS = ["Automatic", "Crop marks", "Soil marks"]


def _band_editor(preset_name, first_info):
    preset = di.BAND_PRESETS[preset_name]
    auto = di.roles_from_descriptions(first_info.get("band_descriptions", [])) if first_info else {}
    defaults = auto or preset["positions"]
    n = first_info["bands"] if first_info else 12
    st.caption("Which band is which? 0 = not available." + (" Read from the file's band names." if auto else ""))
    cols = st.columns(len(di.ROLES))
    positions = {}
    for col, role in zip(cols, di.ROLES):
        positions[role] = col.number_input(role.upper() if role != "rededge" else "RED EDGE", 0, max(n, 1),
                                           int(defaults.get(role, 0) if defaults.get(role, 0) <= n else 0),
                                           key=f"as_fm_band_{role}_{preset_name}")
    return {k: v for k, v in positions.items() if v}


def _load_scenes(paths, preset_name, positions, scale, offset, dates):
    preset = di.BAND_PRESETS[preset_name]
    single = [p for p in paths if di.describe_raster(p)["bands"] == 1]
    multi = [p for p in paths if p not in single]
    scenes = [di.load_scene(p, positions, scale, offset, scene_date=dates.get(str(p))) for p in multi]
    if single:
        tokens = preset.get("tokens") or {"blue": "B02", "green": "B03", "red": "B04", "rededge": "B05", "nir": "B08", "swir1": "B11"}
        for g in di.group_single_band_files(single, tokens):
            scenes.append(di.load_single_band_scene(g["files"], scale, offset, scene_date=g["date"]))
    return scenes


def _overlay(layer, transform, crs, cmap="magma", diverging=False):
    """Colour a layer and reproject it to lon/lat for the map."""
    import matplotlib
    from PIL import Image
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    a = np.asarray(layer, dtype=np.float32)
    h, w = a.shape
    dst_t, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h, transform.c, transform.f + h * transform.e,
                                                transform.c + w * transform.a, transform.f)
    dst = np.full((dh, dw), np.nan, dtype=np.float32)
    reproject(a, dst, src_transform=transform, src_crs=crs, dst_transform=dst_t, dst_crs="EPSG:4326",
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.nearest)
    finite = dst[np.isfinite(dst)]
    lo, hi = (np.percentile(finite, 2), np.percentile(finite, 98)) if finite.size else (0, 1)
    norm = np.clip((dst - lo) / max(hi - lo, 1e-9), 0, 1)
    rgba = (matplotlib.colormaps[cmap](np.nan_to_num(norm)) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isfinite(dst), 200, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG")
    west, north = dst_t.c, dst_t.f
    east, south = west + dw * dst_t.a, north + dh * dst_t.e
    return buf.getvalue(), [[south, west], [north, east]]


FM_KEYS = ("as_fm_images_paths", "as_fm_preset", "as_fm_target", "as_fm_width", "as_fm_scale", "as_fm_offset",
           "as_fm_radius", "as_fm_threshold", "as_enh_q_mask", "as_fm_sites_paths")


def render_field_marks_upload(show_example_sites=None):
    from airchgis.rvt_web import keep_settings, save_settings

    keep_settings(FM_KEYS)
    try:
        _render_field_marks_upload(show_example_sites)
    finally:
        save_settings(FM_KEYS)


def _render_field_marks_upload(show_example_sites=None):
    st.markdown("**1 · Load images**")
    paths = render_file_input("Images of the same area: satellite, drone or aerial (GeoTIFF, JP2). Several dates work better than one.",
                              {".tif", ".tiff", ".jp2", ".vrt"}, "as_fm_images", "field_marks")
    if not paths:
        return

    infos = []
    for p in paths:
        try:
            infos.append(di.describe_raster(p))
        except Exception as exc:
            st.error(f"{p.name}: cannot be read ({exc}).")
    if not infos:
        return
    first = next((i for i in infos if i["bands"] > 1), infos[0])
    st.caption(f"{len(infos)} image(s). First: {di.plain_description(first)}")
    if any(i.get("crs") is None for i in infos):
        st.warning("Some files have no coordinate system: they cannot be placed on the map.")
    preset_name = st.selectbox("Sensor", list(di.BAND_PRESETS), key="as_fm_preset",
                               help="Tells AIrchGIS which band is red, near infrared and so on.")

    st.markdown("**2 · Choose what to look for**")
    gsd = first["pixel_size_m"] or di.BAND_PRESETS[preset_name]["gsd_m"] or 10.0
    c1, c2 = st.columns(2)
    target = c1.selectbox("Marks", TARGETS, key="as_fm_target",
                          help="Crop marks need a growing crop; soil marks need bare, ploughed fields. Automatic picks per date.")
    width = c2.number_input("Width of the features you are looking for (m)", 0.5, 500.0, float(max(20.0, 2 * gsd)), key="as_fm_width")

    with st.expander("Advanced: bands, scale, dates, thresholds"):
        a1, a2 = st.columns(2)
        scale = a1.number_input("Value scale", value=1.0, format="%.6f", key="as_fm_scale",
                                help="Reflectance = value × scale + offset (e.g. Landsat Collection 2: 0.0000275 and -0.2).")
        offset = a2.number_input("Offset", value=0.0, format="%.4f", key="as_fm_offset")
        positions = _band_editor(preset_name, first if first["bands"] > 1 else None)
        dates_df = pd.DataFrame([{"file": Path(i["path"]).name, "date": di.parse_date(Path(i["path"]).name), "path": i["path"]} for i in infos])
        edited = st.data_editor(dates_df, column_config={"path": None, "date": st.column_config.DateColumn("date (from file name; edit if wrong)")},
                                disabled=["file"], hide_index=True, key="as_fm_dates", width="stretch")
        b1, b2 = st.columns(2)
        radius = b1.number_input("Neighbourhood (m)", float(max(gsd * 2, 1.0)), 2000.0, float(max(60.0, 4 * gsd)), key="as_fm_radius",
                                 help="Area each pixel is compared with.")
        threshold = b2.number_input("Anomaly threshold", 0.8, 3.0, 1.5, 0.05, key="as_fm_threshold",
                                    help="How much a pixel must differ from its neighbourhood to count.")
        mask_clouds = st.checkbox("Mask clouds, shadows and no data before the analysis", value=True, key="as_enh_q_mask")
    dates = {r["path"]: (r["date"] if isinstance(r["date"], date) else None) for r in edited.to_dict("records")}

    with st.expander("Known sites (optional)"):
        site_paths = render_file_input("Known sites (CSV with lon/lat, GeoJSON, GeoPackage, zipped Shapefile, KML)", di.SITE_EXTS,
                                       "as_fm_sites", "sites", multiple=False)
    sites = []
    if site_paths:
        try:
            sites = di.read_sites(site_paths[0])
        except Exception as exc:
            st.error(f"Site list not readable: {exc}")

    render_scene_quality(lambda: _load_scenes([Path(i["path"]) for i in infos], preset_name, positions, scale, offset, dates))

    verdict = check_resolvability(width, sensor="sentinel-2" if gsd >= 2 else "lidar", gsd_m=gsd, n_dates=max(1, len(infos)))
    if verdict.verdict == "refuse":
        st.error(f"These images ({gsd:.1f} m pixels) cannot show features {width:g} m wide. {verdict.message}")
    elif verdict.verdict == "warn":
        st.warning(verdict.message)

    if st.button("Find the marks", type="primary", disabled=verdict.verdict == "refuse", key="as_fm_run"):
        with st.spinner("Computing indices and anomalies..."):
            try:
                scenes = _load_scenes([Path(i["path"]) for i in infos], preset_name, positions, scale, offset, dates)
                if mask_clouds:
                    for sc in scenes:
                        mask_scene(sc)
                st.session_state.as_fm_result = le.run_local_analysis(scenes, radius_m=radius, threshold=threshold, target=target)
                st.session_state.as_fm_sites_loaded = sites
                st.session_state.as_fm_width_used = float(width)
                st.session_state.pop("as_fm_layer", None)
            except Exception as exc:
                st.session_state.as_fm_result = None
                st.error(f"Analysis not completed: {exc}")

    result = st.session_state.get("as_fm_result")
    if result is not None:
        render_local_result(result, st.session_state.get("as_fm_sites_loaded") or [], show_example_sites,
                            width=st.session_state.get("as_fm_width_used", width))


def render_local_result(result, sites, show_example_sites=None, width=20.0):
    from airchgis.enhance import bestview
    from airchgis.enhance.screen import one_sentence

    st.markdown("**3 · Result**")
    names = list(result.layers)
    ranked = bestview.rank_layers({k: v for k, v in result.layers.items() if k != "Field boundaries"}, result.gsd_m, width)
    order = [r["name"] for r in ranked["ranking"]]
    if order:
        st.success(one_sentence(ranked["ranking"], width) + " Scores are priorities to check, not probabilities.")
    default = order[0] if order else ("Persistence" if "Persistence" in names else names[0])
    layer = st.selectbox("Layer", names, index=names.index(default), key="as_fm_layer")
    cmap = "viridis" if layer.startswith(("NDVI", "SAVI", "VARI")) else ("Greys" if layer == "Field boundaries" else "magma")
    png, bounds = _overlay(result.layers[layer], result.transform, result.crs, cmap)
    center = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2]
    fmap = folium.Map(location=center, zoom_start=14, tiles=None, control_scale=True)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     attr="Esri", name="Satellite").add_to(fmap)
    import base64

    folium.raster_layers.ImageOverlay("data:image/png;base64," + base64.b64encode(png).decode(), bounds=bounds,
                                      name=layer, opacity=0.8).add_to(fmap)
    for s in sites:
        folium.CircleMarker([s.lat, s.lon], radius=5, color="#ffd166", fill=True, tooltip=s.name).add_to(fmap)
    if show_example_sites:
        show_example_sites(fmap, [bounds[0][1], bounds[0][0], bounds[1][1], bounds[1][0]])
    fmap.fit_bounds(bounds)
    folium.LayerControl(collapsed=True).add_to(fmap)
    st_folium(fmap, width=1200, height=600, key=f"as_fm_map_{layer}", returned_objects=[])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"field_marks_{date.today():%Y%m%d}.tif"
    if st.button("Prepare download (GeoTIFF, all layers)", key="as_fm_export"):
        le.write_layers(result, out)
        st.session_state.as_fm_export_path = str(out)
    p = st.session_state.get("as_fm_export_path")
    if p and Path(p).exists():
        st.download_button("Download GeoTIFF", Path(p).read_bytes(), file_name=Path(p).name, key="as_fm_dl")

    from airchgis.enhance.screen import extent_geometry, render_save_candidate

    first_layer = next(iter(result.layers.values()))
    if result.crs is not None:
        render_save_candidate(extent_geometry(result.transform, result.crs, first_layer.shape),
                              {"screen": "Field marks", "layer": layer, "dates": len(result.table), "ranking": result.table},
                              f"Field marks – {layer}", "as_fm")

    with st.expander("Details"):
        for note in result.notes:
            st.caption("· " + note)
        st.markdown("Dates, ranked by local contrast")
        st.dataframe(pd.DataFrame(result.table), hide_index=True, width="stretch")
        st.markdown("Layers, ranked by visibility")
        st.dataframe(pd.DataFrame([{"layer": x["name"], "visibility": round(x["score"], 2)} for x in ranked["ranking"]]),
                     hide_index=True, width="stretch")
        if sites and result.crs is not None:
            rows = []
            for n in names:
                if n == "Field boundaries":
                    continue
                r = le.sample_sites_auc(result.layers[n], result.transform, result.crs, sites)
                rows.append({"layer": n, "sites inside": r["sites_inside"], "AUC": None if r["auc"] is None else round(r["auc"], 2)})
            st.markdown("Check against your known sites (AUC 0.5 = chance; a small, non-random sample)")
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        c1, c2 = st.columns(2)
        c1.image(_png_layer(result.layers[layer]), caption=layer, width="stretch")
        c2.image(_png_layer(result.layers[layer], enhance="clahe"), caption=f"{layer}, stronger contrast (display only)", width="stretch")


def _png_layer(arr, enhance=None):
    from airchgis.enhance.screen import _png

    return _png(arr, "magma", enhance=enhance)


def render_provider_table(kind):
    rows = [{"Source": p.name, "Coverage": p.coverage, "Resolution": p.resolution, "Licence": p.licence,
             "Access": {"automatic": "automatic", "api key": "automatic with your API key", "earth engine": "Google Earth Engine",
                        "manual": "download, then upload"}[p.access],
             "Format": p.format, "Link": p.url} for p in sources.providers(kind)]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Link": st.column_config.LinkColumn("Link")})
