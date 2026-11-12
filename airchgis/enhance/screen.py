"""Streamlit panels: "Enhance & best view" on the Terrain and Field marks screens.

Every action goes through :func:`airchgis.gis.tools.run_tool`, so it is
recorded in the session's provenance log and can be replayed as a script.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from airchgis import data_input as di
from airchgis.enhance import bestview, contrast, metrics, multispectral
from airchgis.gis.provenance import ProvenanceLog
from airchgis.gis.tools import ToolError, run_tool
from airchgis.input_ui import render_file_input

OUT_DIR = di.WORKSPACE_DIR / "outputs" / "enhance"

STEP_LABELS = {"destripe": "Remove banding", "despike": "Remove spikes and pits", "fill_voids": "Fill small voids",
               "denoise": "Reduce noise (edge-preserving)"}
METRIC_LABELS = {"noise_sigma": "Noise (elevation units)", "stripe_energy": "Banding (share of fine detail)",
                 "spike_fraction": "Spikes and pits (share of pixels)", "void_fraction": "Voids (share of pixels)"}


def session_log() -> ProvenanceLog:
    if st.session_state.get("as_provenance_log") is None:
        st.session_state.as_provenance_log = ProvenanceLog("AIrchGIS session")
    return st.session_state.as_provenance_log


def _png(arr, cmap="gray", enhance=None):
    import matplotlib
    from PIL import Image

    a = np.asarray(arr, dtype=np.float64)
    if enhance:
        a, _ = contrast.enhance(a, enhance)
    finite = a[np.isfinite(a)]
    lo, hi = (np.percentile(finite, [2, 98]) if finite.size else (0, 1))
    norm = np.clip((a - lo) / max(hi - lo, 1e-12), 0, 1)
    rgba = (matplotlib.colormaps[cmap](np.nan_to_num(norm)) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isfinite(a), 255, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG")
    return buf.getvalue()


def _hillshade(dem, res):
    import rvt.vis

    f, mask = metrics.finite_fill(dem)
    h = rvt.vis.hillshade(f.astype(np.float32), res, res, sun_azimuth=315, sun_elevation=35, ve_factor=2)
    h = np.asarray(h, dtype=np.float32)
    h[mask] = np.nan
    return h


def _read(path):
    import rasterio

    with rasterio.open(path) as src:
        a = src.read(1).astype(np.float32)
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
    return a


def _write_input(arr, profile, crs, name):
    import rasterio

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.tif"
    prof = dict(profile)
    prof.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, crs=crs or prof.get("crs"), compress="deflate",
                height=arr.shape[0], width=arr.shape[1])
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(np.where(np.isfinite(arr), arr, -9999.0).astype(np.float32), 1)
    return path


def _download(path, label, key):
    p = Path(path)
    if p.exists():
        st.download_button(label, p.read_bytes(), file_name=p.name, key=key)


def render_provenance_download(key):
    log = session_log()
    if not log.steps:
        return
    st.download_button("Download the steps as a Python script (re-runnable)", log.to_python().encode(),
                       file_name=f"airchgis_steps_{datetime.now():%Y%m%d_%H%M}.py", key=key)


# ---------------------------------------------------------------- Terrain
def render_terrain_enhance(dem, res, profile, crs, label="DTM", on_apply=None, key="as_enh_t"):
    """Clean the loaded terrain, find the best visualization and build a fused view."""
    if dem is None or profile is None or profile.get("transform") is None:
        st.info("Load a georeferenced terrain model first.")
        return
    st.caption("Clean the data, let AIrchGIS compare many visualizations, and blend the best ones. "
               "Every step is measured and recorded.")
    dem, n_zero = metrics.zero_nodata(dem)
    if n_zero:
        st.caption(f"{n_zero} pixels with elevation exactly 0 are treated as no data (fill outside the survey).")
    tag = f"{key}_{abs(hash((dem.shape, float(np.nanmean(dem)) if np.isfinite(dem).any() else 0))) % 10**8}"
    src_path = st.session_state.get(f"{tag}_src")
    if not src_path or not Path(src_path).exists():
        src_path = str(_write_input(np.asarray(dem, dtype=np.float32), profile, crs, f"{label}_{tag}"))
        st.session_state[f"{tag}_src"] = src_path

    # 1. Clean
    st.markdown("**1 · Clean**")
    steps = st.multiselect("Steps", list(STEP_LABELS), default=list(STEP_LABELS), format_func=STEP_LABELS.get, key=f"{key}_steps")
    if st.button("Measure and clean", key=f"{key}_clean_go", disabled=not steps):
        with st.spinner("Cleaning..."):
            try:
                r = run_tool("clean_terrain", log=session_log(), input=src_path, output=str(OUT_DIR / f"{label}_{tag}_clean.tif"), steps=steps)
                st.session_state[f"{tag}_clean"] = r["outputs"]
            except ToolError as exc:
                st.error(str(exc))
    cleaned = st.session_state.get(f"{tag}_clean")
    current_path = src_path
    if cleaned:
        q = cleaned["quality"]
        rows = [{"measure": METRIC_LABELS[k], "before": q["before"][k], "after": q["after"][k]} for k in METRIC_LABELS]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"before": st.column_config.NumberColumn(format="%.4g"),
                                    "after": st.column_config.NumberColumn(format="%.4g")})
        for note in cleaned["summary"]:
            st.caption("· " + note)
        clean_arr = _read(cleaned["output"])
        c1, c2 = st.columns(2)
        c1.image(_png(_hillshade(dem, res)), caption="Before (hillshade)", width="stretch")
        c2.image(_png(_hillshade(clean_arr, res)), caption="After (hillshade)", width="stretch")
        b1, b2 = st.columns(2)
        with b1:
            _download(cleaned["output"], "Download cleaned GeoTIFF", f"{key}_clean_dl")
        if on_apply is not None and b2.button("Use the cleaned surface in all views", key=f"{key}_apply"):
            on_apply(clean_arr)
            st.rerun()
        if st.checkbox("Use the cleaned surface below", value=True, key=f"{key}_use_clean"):
            current_path = cleaned["output"]

    # 2. Best view
    st.markdown("**2 · Best view**")
    c1, c2 = st.columns([0.4, 0.6])
    width = c1.number_input("Width of the features sought (m)", 0.1, 1000.0, float(max(2.0 * res, 4.0)), key=f"{key}_width")
    with c2:
        site_paths = render_file_input("Known sites (optional)", di.SITE_EXTS, f"{key}_sites", "sites", multiple=False)
    sites = str(site_paths[0]) if site_paths else None
    quick = st.toggle("Quick look (fewer candidates)", value=dem.size > 4_000_000, key=f"{key}_quick")
    if st.button("Find the best view", type="primary", key=f"{key}_bv_go"):
        with st.spinner("Computing and scoring visualizations..."):
            try:
                r = run_tool("best_view", log=session_log(), input=current_path, output_dir=str(OUT_DIR / f"{tag}_bestview"),
                             target_feature_width_m=float(width), sites=sites, quick=bool(quick))
                st.session_state[f"{tag}_bv"] = r
            except ToolError as exc:
                st.error(str(exc))
    bv = st.session_state.get(f"{tag}_bv")
    if bv:
        if bv["status"] == "refused":
            st.error(bv["message"])
        else:
            if bv.get("message"):
                st.warning(bv["message"])
            out = bv["outputs"]
            st.success(out["explanation"])
            table = pd.DataFrame([{"rank": i + 1, "visualization": x["name"], "visibility": round(x["score"], 2),
                                   **({"AUC at your sites": None if x.get("auc") is None else round(x["auc"], 2)} if sites else {})}
                                  for i, x in enumerate(out["ranking"])])
            st.dataframe(table, hide_index=True, width="stretch", height=260)
            st.caption(f"Scored on the {out['scored_on']}. Visibility = contrast of features of the chosen width "
                       "against both the noise in flat areas and the broad landscape relief; higher is clearer.")
            disp = st.radio("Display", ["Plain", "Adaptive contrast (CLAHE)"], horizontal=True, key=f"{key}_bv_disp")
            st.image(_png(_read(out["output"]), enhance="clahe" if disp != "Plain" else None), caption=out["best"], width="stretch")
            _download(out["output"], "Download best view GeoTIFF", f"{key}_bv_dl")

    # 3. Fused view
    st.markdown("**3 · Fused view**")
    c1, c2 = st.columns(2)
    n_layers = c1.slider("Layers to blend", 2, 6, 4, key=f"{key}_fuse_n")
    method = c2.selectbox("Blend", ["optimized", "pca"], format_func={"optimized": "Weights optimized for visibility",
                                                                      "pca": "First principal component"}.get, key=f"{key}_fuse_m")
    if st.button("Build fused view", key=f"{key}_fuse_go"):
        with st.spinner("Blending..."):
            try:
                r = run_tool("fused_view", log=session_log(), input=current_path, output=str(OUT_DIR / f"{tag}_fused_{method}.tif"),
                             target_feature_width_m=float(width), method=method, n_layers=int(n_layers), sites=sites)
                st.session_state[f"{tag}_fused"] = r
            except ToolError as exc:
                st.error(str(exc))
    fz = st.session_state.get(f"{tag}_fused")
    if fz:
        if fz["status"] == "refused":
            st.error(fz["message"])
        else:
            out = fz["outputs"]
            st.info(out["note"] + (f" AUC at your sites: {out['auc']:.2f}." if out.get("auc") is not None else ""))
            st.image(_png(_read(out["output"])), caption="Fused view", width="stretch")
            _download(out["output"], "Download fused view GeoTIFF", f"{key}_fuse_dl")
    render_provenance_download(f"{key}_prov")


# ---------------------------------------------------------------- Field marks
def render_scene_quality(load_scenes, key="as_enh_q"):
    """Quality of the loaded dates on request; returns True when clouds and shadows should be masked."""
    with st.expander("Image quality · clouds, shadows, haze and band problems, per date"):
        if st.button("Check image quality", key=f"{key}_go"):
            try:
                st.session_state[f"{key}_rows"] = multispectral.quality_table(load_scenes())
            except Exception as exc:
                st.error(f"Image quality not available: {exc}")
        rows = st.session_state.get(f"{key}_rows")
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Spectral screening rules (or the Sentinel-2 SCL band when present), not a cloud model.")
    return st.checkbox("Mask clouds, shadows and no-data before the analysis", value=True, key=f"{key}_mask")


def render_field_marks_enhance(result, sites=None, key="as_enh_fm"):
    """Rank the computed layers by visibility and show the best one with adaptive contrast."""
    with st.expander("Enhance & best view", expanded=False):
        width = st.number_input("Width of the features sought (m)", 0.5, 2000.0, float(max(2 * result.gsd_m, 20.0)), key=f"{key}_width")
        layers = {k: v for k, v in result.layers.items() if k != "Field boundaries"}
        px = None
        if sites and result.crs is not None:
            from pyproj import Transformer

            tr = Transformer.from_crs("EPSG:4326", result.crs, always_xy=True)
            inv = ~result.transform
            px = []
            for s in sites:
                x, y = tr.transform(s.lon, s.lat)
                c, r = inv * (x, y)
                px.append((r, c))
        r = bestview.rank_layers(layers, result.gsd_m, width, site_pixels=px)
        if not r["ranking"]:
            st.info("No layer to rank.")
            return
        st.success(r["explanation"])
        st.dataframe(pd.DataFrame([{"layer": x["name"], "visibility": round(x["score"], 2),
                                    **({"AUC at your sites": None if x.get("auc") is None else round(x["auc"], 2)} if px else {})}
                                   for x in r["ranking"]]), hide_index=True, width="stretch")
        top = r["ranking"][0]["name"]
        c1, c2 = st.columns(2)
        c1.image(_png(layers[top], "magma"), caption=f"{top}", width="stretch")
        c2.image(_png(layers[top], "magma", enhance="clahe"), caption=f"{top}, adaptive contrast (display only)", width="stretch")
