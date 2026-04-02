import argparse
import base64
import math
import struct
from html import escape
from pathlib import Path

import numpy as np
import rasterio
import rasterio.transform
import rasterio.warp
from matplotlib.figure import Figure
from matplotlib import colormaps

try:
    import laspy
except Exception:
    laspy = None

try:
    import pyproj
except Exception:
    pyproj = None

LADS_TARGET_CRS = "EPSG:32632"
LADS_MAX_POINTS = 85000
LADS_BROWSER_MAX_SIDE = 1400
LADS_Z_EXAGGERATION = 2.5


def _as_crs_text(crs):
    if crs is None:
        return "sconosciuto"
    try:
        return crs.to_string()
    except Exception:
        return str(crs)


def _sanitize_surface_for_lads(dtm):
    arr = np.asarray(dtm, dtype=np.float32).copy()
    finite = np.isfinite(arr)
    if finite.sum() < 16:
        return arr
    vals = arr[finite]
    lo = float(np.nanmin(vals))
    eps = max(1e-4, abs(lo) * 1e-6)
    q10 = float(np.nanpercentile(vals, 10.0))
    q25 = float(np.nanpercentile(vals, 25.0))
    q50 = float(np.nanpercentile(vals, 50.0))
    if q10 <= lo + eps and q25 <= lo + eps and (q50 - lo) >= 80.0:
        arr[np.abs(arr - lo) <= eps] = np.nan
    return arr


def build_lads_point_cloud(dtm, profile, src_crs, target_crs=LADS_TARGET_CRS, max_points=LADS_MAX_POINTS):
    arr = _sanitize_surface_for_lads(dtm)
    if arr.ndim != 2:
        raise RuntimeError("Il DTM LADS deve essere mono-banda.")
    if profile is None or profile.get("transform") is None:
        raise RuntimeError("Transform georiferito non disponibile per LADS.")
    if src_crs is None:
        raise RuntimeError("CRS del raster non disponibile per LADS.")

    valid = np.isfinite(arr)
    total_points = int(valid.sum())
    if total_points <= 0:
        raise RuntimeError("Il DTM non contiene celle valide.")

    rows, cols = np.where(valid)
    step = 1
    if max_points is not None and int(max_points) > 0:
        step = max(1, int(math.ceil(total_points / float(max_points))))
    if step > 1:
        rows = rows[::step]
        cols = cols[::step]

    xs, ys = rasterio.transform.xy(profile["transform"], rows.tolist(), cols.tolist(), offset="center")
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    zs = arr[rows, cols].astype(np.float32)

    dst_crs = target_crs or src_crs
    if _as_crs_text(src_crs) != _as_crs_text(dst_crs):
        tx, ty = rasterio.warp.transform(src_crs, dst_crs, xs.tolist(), ys.tolist())
        xs = np.asarray(tx, dtype=np.float64)
        ys = np.asarray(ty, dtype=np.float64)

    origin_x = float(np.nanmin(xs))
    origin_y = float(np.nanmin(ys))
    x_local = (xs - origin_x).astype(np.float32)
    y_local = (ys - origin_y).astype(np.float32)

    return {
        "x": x_local,
        "y": y_local,
        "z": zs,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "source_crs": _as_crs_text(src_crs),
        "target_crs": _as_crs_text(dst_crs),
        "total_points": total_points,
        "preview_points": int(zs.size),
        "sample_step": step,
    }


def build_lads_figure(cloud, title="LADS 3D"):
    fig = Figure(figsize=(10.5, 8.0), dpi=120)
    fig.patch.set_facecolor("black")
    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("black")

    x = np.asarray(cloud["x"], dtype=np.float32)
    y = np.asarray(cloud["y"], dtype=np.float32)
    z = np.asarray(cloud["z"], dtype=np.float32)

    point_size = 0.8 if z.size > 50000 else 1.6
    ax.scatter(x, y, z, c=z, cmap="terrain", s=point_size, marker=".", linewidths=0, alpha=0.95)

    x_span = max(1.0, float(np.nanmax(x) - np.nanmin(x)))
    y_span = max(1.0, float(np.nanmax(y) - np.nanmin(y)))
    z_span = max(1.0, float(np.nanmax(z) - np.nanmin(z)))
    try:
        ax.set_box_aspect((x_span, y_span, z_span * float(LADS_Z_EXAGGERATION)))
    except Exception:
        pass

    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    y_min = float(np.nanmin(y))
    y_max = float(np.nanmax(y))
    z_min = float(np.nanmin(z))
    z_max = float(np.nanmax(z))
    x_pad = max(1.0, x_span * 0.03)
    y_pad = max(1.0, y_span * 0.03)
    z_pad = max(1.0, z_span * 0.06)
    ax.set_xlim3d(x_min - x_pad, x_max + x_pad)
    ax.set_ylim3d(y_min - y_pad, y_max + y_pad)
    ax.set_zlim3d(z_min - z_pad, z_max + z_pad)

    ax.view_init(elev=34, azim=-63)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    ax.set_axis_off()
    for axis in (getattr(ax, "xaxis", None), getattr(ax, "yaxis", None), getattr(ax, "zaxis", None)):
        if axis is None:
            continue
        try:
            axis.pane.set_visible(False)
        except Exception:
            pass
        try:
            axis.line.set_color((0.0, 0.0, 0.0, 0.0))
        except Exception:
            pass
    return fig


def _terrain_colors_u8(z_values):
    z = np.asarray(z_values, dtype=np.float32)
    orig_shape = z.shape
    z = z.reshape(-1)
    finite = np.isfinite(z)
    if not finite.any():
        return np.zeros(orig_shape + (3,), dtype=np.uint8)
    lo = float(np.nanpercentile(z, 2.0))
    hi = float(np.nanpercentile(z, 98.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = float(np.nanmin(z))
        hi = float(np.nanmax(z))
    denom = max(1e-6, hi - lo)
    norm = np.clip((z - lo) / denom, 0.0, 1.0)
    rgb = colormaps["turbo"](norm)[:, :3]
    return np.round(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8).reshape(orig_shape + (3,))


def _mean_abs_step(arr, axis):
    values = np.asarray(arr, dtype=np.float32)
    if values.ndim != 2 or values.shape[axis] <= 1:
        return 1.0
    diffs = np.diff(values, axis=axis)
    diffs = np.abs(diffs[np.isfinite(diffs)])
    if diffs.size == 0:
        return 1.0
    step = float(np.nanmedian(diffs))
    return step if np.isfinite(step) and step > 1e-6 else 1.0


def _height_shaded_colors_u8(z_values, valid_mask, dx=1.0, dy=1.0):
    z = np.asarray(z_values, dtype=np.float32)
    valid = np.asarray(valid_mask, dtype=bool)
    if z.ndim != 2:
        return _terrain_colors_u8(z)
    if not valid.any():
        return np.zeros(z.shape + (3,), dtype=np.uint8)

    lo = float(np.nanpercentile(z[valid], 2.0))
    hi = float(np.nanpercentile(z[valid], 98.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = float(np.nanmin(z[valid]))
        hi = float(np.nanmax(z[valid]))
    denom = max(1e-6, hi - lo)
    norm = np.clip((z - lo) / denom, 0.0, 1.0)
    base_rgb = colormaps["RdYlGn_r"](norm)[..., :3]

    fill = np.array(z, copy=True)
    fill[~valid] = np.nan
    fill_value = float(np.nanmedian(fill[valid]))
    fill[~valid] = fill_value

    try:
        gy, gx = np.gradient(fill, max(1e-6, float(dy)), max(1e-6, float(dx)))
    except Exception:
        gy, gx = np.gradient(fill)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azimuth = math.radians(315.0)
    altitude = math.radians(42.0)
    shade = (
        np.sin(altitude) * np.sin(slope)
        + np.cos(altitude) * np.cos(slope) * np.cos(azimuth - aspect)
    )
    shade = np.clip((shade + 1.0) * 0.5, 0.0, 1.0)
    shade = 0.45 + 0.70 * shade

    rgb = np.clip(base_rgb * shade[..., None], 0.0, 1.0)
    rgb[~valid] = 0.0
    return np.round(rgb * 255.0).astype(np.uint8)


def _adaptive_z_scale(x_span, y_span, z_span):
    xy_span = max(1.0, float(max(x_span, y_span)))
    z_span = max(1e-6, float(z_span))
    target_ratio = 0.42
    scale = target_ratio * xy_span / z_span
    return float(np.clip(scale, 0.45, float(LADS_Z_EXAGGERATION)))


def _align_xy_to_principal_axes(x, y, valid_mask):
    x_arr = np.asarray(x, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.float32)
    valid = np.asarray(valid_mask, dtype=bool)
    if not valid.any():
        return x_arr, y_arr

    pts = np.column_stack([x_arr[valid].astype(np.float64), y_arr[valid].astype(np.float64)])
    center = np.nanmean(pts, axis=0)
    centered = pts - center
    if centered.shape[0] < 3:
        xr = x_arr - float(center[0])
        yr = y_arr - float(center[1])
        return xr.astype(np.float32), yr.astype(np.float32)

    cov = np.cov(centered, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    basis = eigvecs[:, order]
    if np.linalg.det(basis) < 0:
        basis[:, 1] *= -1.0

    flat = np.column_stack([x_arr.reshape(-1).astype(np.float64), y_arr.reshape(-1).astype(np.float64)])
    rotated = (flat - center) @ basis
    xr = rotated[:, 0].reshape(x_arr.shape)
    yr = rotated[:, 1].reshape(y_arr.shape)
    return xr.astype(np.float32), yr.astype(np.float32)


def _encode_f32_triplets_base64(a, b, c):
    interleaved = np.column_stack(
        [
            np.asarray(a, dtype=np.float32),
            np.asarray(b, dtype=np.float32),
            np.asarray(c, dtype=np.float32),
        ]
    ).astype(np.float32, copy=False)
    return base64.b64encode(interleaved.tobytes(order="C")).decode("ascii")


def _encode_u8_triplets_base64(rgb):
    arr = np.asarray(rgb, dtype=np.uint8)
    return base64.b64encode(arr.tobytes(order="C")).decode("ascii")


def _encode_u8_base64(arr):
    return base64.b64encode(np.asarray(arr, dtype=np.uint8).tobytes(order="C")).decode("ascii")


def build_browser_terrain_grid(dtm, profile, src_crs, target_crs=LADS_TARGET_CRS, max_side=LADS_BROWSER_MAX_SIDE):
    arr = _sanitize_surface_for_lads(dtm)
    if arr.ndim != 2:
        raise RuntimeError("Il DTM browser deve essere mono-banda.")
    if profile is None or profile.get("transform") is None:
        raise RuntimeError("Transform georiferito non disponibile per il browser 3D.")
    if src_crs is None:
        raise RuntimeError("CRS del raster non disponibile per il browser 3D.")

    h, w = arr.shape
    if h <= 1 or w <= 1:
        raise RuntimeError("Raster troppo piccolo per il viewer 3D.")
    step = max(1, int(math.ceil(max(h, w) / float(max_side))))
    rows = np.arange(0, h, step, dtype=np.int32)
    cols = np.arange(0, w, step, dtype=np.int32)
    if rows[-1] != h - 1:
        rows = np.append(rows, h - 1)
    if cols[-1] != w - 1:
        cols = np.append(cols, w - 1)

    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    z = arr[np.ix_(rows, cols)].astype(np.float32)
    valid = np.isfinite(z)
    if not valid.any():
        raise RuntimeError("Nessuna cella valida per il viewer 3D.")

    xs, ys = rasterio.transform.xy(profile["transform"], rr.ravel().tolist(), cc.ravel().tolist(), offset="center")
    x = np.asarray(xs, dtype=np.float64).reshape(z.shape)
    y = np.asarray(ys, dtype=np.float64).reshape(z.shape)

    dst_crs = target_crs or src_crs
    if _as_crs_text(src_crs) != _as_crs_text(dst_crs):
        tx, ty = rasterio.warp.transform(src_crs, dst_crs, x.ravel().tolist(), y.ravel().tolist())
        x = np.asarray(tx, dtype=np.float64).reshape(z.shape)
        y = np.asarray(ty, dtype=np.float64).reshape(z.shape)

    origin_x = float(np.nanmin(x[valid]))
    origin_y = float(np.nanmin(y[valid]))
    x, y = _align_xy_to_principal_axes(x, y, valid)
    x = (x - float(np.nanmin(x[valid]))).astype(np.float32)
    y = (y - float(np.nanmin(y[valid]))).astype(np.float32)
    z_fill = np.where(valid, z, np.nanmin(z[valid])).astype(np.float32)
    dx = _mean_abs_step(x, axis=1)
    dy = _mean_abs_step(y, axis=0)
    colors = _height_shaded_colors_u8(z_fill, valid, dx=dx, dy=dy)
    colors[~valid] = 0
    x_span = float(np.nanmax(x[valid]) - np.nanmin(x[valid]))
    y_span = float(np.nanmax(y[valid]) - np.nanmin(y[valid]))
    z_span = float(np.nanmax(z[valid]) - np.nanmin(z[valid]))
    z_scale = _adaptive_z_scale(x_span, y_span, z_span)

    return {
        "x": x,
        "y": y,
        "z": z_fill,
        "valid": valid.astype(np.uint8),
        "colors": colors.astype(np.uint8),
        "rows": int(z.shape[0]),
        "cols": int(z.shape[1]),
        "origin_x": origin_x,
        "origin_y": origin_y,
        "source_crs": _as_crs_text(src_crs),
        "target_crs": _as_crs_text(dst_crs),
        "sample_step": int(step),
        "preview_points": int(valid.sum()),
        "total_points": int(np.isfinite(arr).sum()),
        "z_scale": float(z_scale),
    }


def write_browser_cloud_viewer(output_html, terrain, las_href="", variant_options=None, current_variant_key=""):
    output_html = Path(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    x = np.asarray(terrain["x"], dtype=np.float32)
    y = np.asarray(terrain["y"], dtype=np.float32)
    z = np.asarray(terrain["z"], dtype=np.float32)
    valid = np.asarray(terrain["valid"], dtype=np.uint8)
    colors = np.asarray(terrain["colors"], dtype=np.uint8)
    rows = int(terrain["rows"])
    cols = int(terrain["cols"])

    x_span = max(1.0, float(np.nanmax(x) - np.nanmin(x)))
    y_span = max(1.0, float(np.nanmax(y) - np.nanmin(y)))
    z_scale = float(terrain.get("z_scale", LADS_Z_EXAGGERATION))
    z_span = max(1.0, float(np.nanmax(z) - np.nanmin(z)))
    radius = max(x_span, y_span, z_span * z_scale) * 0.8

    pos_b64 = _encode_f32_triplets_base64(x.reshape(-1), y.reshape(-1), z.reshape(-1))
    color_b64 = _encode_u8_triplets_base64(colors.reshape(-1, 3))
    valid_b64 = _encode_u8_base64(valid.reshape(-1))
    exag = float(z_scale)
    las_button = ""
    if las_href:
        las_button = f'<a class="toolbar-btn" href="{las_href}" download>Esporta .LAS</a>'
    variant_html = ""
    if variant_options:
        options_markup = []
        for item in variant_options:
            key = str(item.get("key", ""))
            href = str(item.get("href", ""))
            label = str(item.get("label", key or href))
            selected = " selected" if key == current_variant_key else ""
            options_markup.append(f'<option value="{escape(href, quote=True)}"{selected}>{escape(label)}</option>')
        variant_html = (
            '<label class="toolbar-select-wrap">'
            '<span>Dato</span>'
            f'<select id="variant-select" class="toolbar-select">{"".join(options_markup)}</select>'
            "</label>"
        )
    cloud_preprocess_html = (
        '<label class="toolbar-select-wrap">'
        '<span>Cloud preprocessing</span>'
        '<select id="cloud-preprocess-select" class="toolbar-select">'
        '<option value="cloud1">Cloud 1</option>'
        '<option value="cloud2">Cloud 2</option>'
        '<option value="cloud3">Cloud 3</option>'
        "</select>"
        "</label>"
    )

    html = f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D Cloud</title>
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #000;
    }}
    #app {{
      position: fixed;
      inset: 0;
      background: #000;
    }}
    #toolbar {{
      position: fixed;
      top: 14px;
      left: 14px;
      z-index: 20;
      display: flex;
      gap: 10px;
    }}
    .toolbar-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 14px;
      border-radius: 10px;
      background: rgba(18, 18, 18, 0.92);
      color: #fff;
      text-decoration: none;
      font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      border: 1px solid rgba(255,255,255,0.12);
      backdrop-filter: blur(6px);
    }}
    .toolbar-select-wrap {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 10px;
      background: rgba(18, 18, 18, 0.92);
      color: #fff;
      font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      border: 1px solid rgba(255,255,255,0.12);
      backdrop-filter: blur(6px);
    }}
    .toolbar-select {{
      min-width: 130px;
      padding: 6px 10px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.14);
      background: #111;
      color: #fff;
      font: 500 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      outline: none;
    }}
    canvas {{
      display: block;
    }}
  </style>
</head>
<body>
  <div id="toolbar">{las_button}{variant_html}{cloud_preprocess_html}</div>
  <div id="app"></div>
  <div id="errorbox" style="display:none; position:fixed; right:14px; top:14px; max-width:520px; padding:12px 14px; background:rgba(120,0,0,0.9); color:#fff; font:13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; z-index:30; border-radius:10px; white-space:pre-wrap;"></div>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <script>
    function showError(message) {{
      const box = document.getElementById('errorbox');
      box.style.display = 'block';
      box.textContent = message;
    }}
    try {{
      if (!window.THREE) {{
        throw new Error('Three.js non caricato.');
      }}
    const variantSelect = document.getElementById('variant-select');
    if (variantSelect) {{
      variantSelect.addEventListener('change', function() {{
        if (this.value) {{
          window.location.href = this.value;
        }}
      }});
    }}
    const POS_B64 = "{pos_b64}";
    const COLOR_B64 = "{color_b64}";
    const VALID_B64 = "{valid_b64}";
    const GRID_ROWS = {rows};
    const GRID_COLS = {cols};
    const Z_EXAGGERATION = {exag:.6f};
    const DEFAULT_RADIUS = {radius:.6f};

    function base64ToUint8Array(base64) {{
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {{
        bytes[i] = binary.charCodeAt(i);
      }}
      return bytes;
    }}

    const root = document.getElementById('app');
    const renderer = new THREE.WebGLRenderer({{ antialias: true, powerPreference: 'high-performance' }});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 1);
    renderer.outputEncoding = THREE.sRGBEncoding;
    root.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);
    const hemi = new THREE.HemisphereLight(0xffffff, 0x060708, 1.15);
    scene.add(hemi);
    const dir1 = new THREE.DirectionalLight(0xffffff, 1.0);
    dir1.position.set(1.1, -1.3, 1.45);
    scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0xffddaa, 0.30);
    dir2.position.set(-0.8, 0.7, 0.55);
    scene.add(dir2);

    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, Math.max(50000, DEFAULT_RADIUS * 20));
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 1.05;
    controls.zoomSpeed = 1.15;
    controls.panSpeed = 0.95;
    controls.screenSpacePanning = true;
    controls.minPolarAngle = 0.02;
    controls.maxPolarAngle = Math.PI - 0.02;
    controls.minDistance = Math.max(2, DEFAULT_RADIUS * 0.04);
    controls.maxDistance = Math.max(200000, DEFAULT_RADIUS * 40);
    controls.enableKeys = true;

    const posBytes = base64ToUint8Array(POS_B64);
    const positions = new Float32Array(posBytes.buffer, posBytes.byteOffset, posBytes.byteLength / 4);
    const colorBytes = base64ToUint8Array(COLOR_B64);
    const validBytes = base64ToUint8Array(VALID_B64);

    for (let i = 2; i < positions.length; i += 3) {{
      positions[i] = positions[i] * Z_EXAGGERATION;
    }}

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Uint8BufferAttribute(colorBytes, 3, true));
    const indices = [];
    for (let r = 0; r < GRID_ROWS - 1; r++) {{
      for (let c = 0; c < GRID_COLS - 1; c++) {{
        const a = r * GRID_COLS + c;
        const b = a + 1;
        const d = (r + 1) * GRID_COLS + c;
        const e = d + 1;
        if (validBytes[a] && validBytes[b] && validBytes[d]) indices.push(a, d, b);
        if (validBytes[b] && validBytes[d] && validBytes[e]) indices.push(b, d, e);
      }}
    }}
    if (!indices.length) {{
      throw new Error('Nessun triangolo valido generato per il terrain viewer.');
    }}
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    const bbox = geometry.boundingBox;
    const center = new THREE.Vector3();
    bbox.getCenter(center);
    geometry.translate(-center.x, -center.y, -(bbox.min.z + bbox.max.z) * 0.5);
    geometry.computeBoundingSphere();

    const material = new THREE.MeshPhongMaterial({{
      vertexColors: true,
      shininess: 6,
      specular: 0x1b1b1b,
      flatShading: false,
      side: THREE.DoubleSide
    }});
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    const sphere = geometry.boundingSphere || {{ radius: DEFAULT_RADIUS, center: new THREE.Vector3(0, 0, 0) }};
    const radius = Math.max(10, sphere.radius || DEFAULT_RADIUS);
    controls.target.set(0, 0, 0);
    camera.near = 0.1;
    camera.far = Math.max(200000, radius * 80);
    camera.position.set(radius * 1.22, -radius * 1.18, radius * 0.92);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    controls.update();

    function onResize() {{
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    }}
    window.addEventListener('resize', onResize);

    function animate() {{
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }}
    animate();
    }} catch (err) {{
      console.error(err);
      showError(String(err && err.stack ? err.stack : err));
    }}
  </script>
</body>
</html>
"""
    output_html.write_text(html, encoding="utf-8")
    return output_html


def export_lads_las(dtm, profile, src_crs, output_path, target_crs=LADS_TARGET_CRS):
    if laspy is None:
        raise RuntimeError("Modulo `laspy` non disponibile per esportare .LAS.")
    if pyproj is None:
        raise RuntimeError("Modulo `pyproj` non disponibile per esportare .LAS.")

    cloud = build_lads_point_cloud(dtm, profile, src_crs, target_crs=target_crs, max_points=None)
    xs = np.asarray(cloud["x"], dtype=np.float64) + float(cloud["origin_x"])
    ys = np.asarray(cloud["y"], dtype=np.float64) + float(cloud["origin_y"])
    zs = np.asarray(cloud["z"], dtype=np.float64)

    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.001, 0.001, 0.001], dtype=np.float64)
    header.offsets = np.array([float(np.nanmin(xs)), float(np.nanmin(ys)), float(np.nanmin(zs))], dtype=np.float64)
    try:
        header.add_crs(pyproj.CRS.from_user_input(target_crs or src_crs))
    except Exception:
        pass

    las = laspy.LasData(header)
    las.x = xs
    las.y = ys
    las.z = zs
    try:
        las.classification = np.full(zs.shape[0], 2, dtype=np.uint8)
    except Exception:
        pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    las.write(str(output_path))
    return cloud


def _load_raster_for_cli(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr, src.profile.copy(), src.crs


def main():
    parser = argparse.ArgumentParser(description="Preview LADS 3D da un DTM raster.")
    parser.add_argument("raster_path", help="Path del raster DTM da convertire in point cloud")
    parser.add_argument("--target-crs", default=LADS_TARGET_CRS, help="CRS metrico di destinazione per la preview 3D")
    parser.add_argument("--max-points", type=int, default=LADS_MAX_POINTS, help="Numero massimo di punti da plottare nella preview")
    parser.add_argument("--output", default="", help="PNG di output facoltativo; se omesso salva nulla")
    args = parser.parse_args()

    arr, profile, crs = _load_raster_for_cli(args.raster_path)
    cloud = build_lads_point_cloud(arr, profile, crs, target_crs=args.target_crs, max_points=max(1000, int(args.max_points)))
    fig = build_lads_figure(cloud, title="LADS 3D CLI")
    if args.output:
        fig.savefig(args.output, dpi=140)
        print(args.output)
        return
    print(
        f"LADS pronto | src={cloud['source_crs']} | dst={cloud['target_crs']} | "
        f"punti={cloud['preview_points']}/{cloud['total_points']} | step={cloud['sample_step']}"
    )


if __name__ == "__main__":
    main()
