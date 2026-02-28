import inspect
import zipfile
import shutil
import math
import io
from pathlib import Path
from collections import OrderedDict

import numpy as np
import rasterio
import rasterio.warp
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib as mpl

mpl.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from PIL import Image
import requests

import rvt.vis

EXTS = {".tif", ".tiff", ".asc"}
SAT_ZOOMS_TRY = (17, 16, 15, 14, 13, 12)


def unzip_all(folder: Path):
    if not folder.exists():
        return 0
    n = 0
    for z in folder.rglob("*.zip"):
        if not z.is_file():
            continue
        dest = z.parent / z.stem
        marker = dest / ".unzipped"
        mt = str(z.stat().st_mtime_ns)
        if marker.exists():
            try:
                if marker.read_text(encoding="utf-8").strip() == mt:
                    continue
            except Exception:
                pass
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except Exception:
                pass
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(z, "r") as zz:
                zz.extractall(dest)
            marker.write_text(mt, encoding="utf-8")
            n += 1
        except Exception:
            pass
    return n


def prepare_inputs(root: Path):
    return (
        unzip_all(root / "image" / "DTM")
        + unzip_all(root / "image" / "DSM_First")
        + unzip_all(root / "image" / "DSM_Last")
    )


def list_rasters(folder: Path):
    if not folder.exists():
        return []
    out = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            out.append(p)
    return out


def pick_latest_raster(folder: Path):
    rasters = list_rasters(folder)
    if not rasters:
        return None
    rasters.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    return rasters[0]


def load_raster(path: Path):
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
        res = float(src.res[0])
        profile = src.profile.copy()
        bounds = (float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top))
        crs = src.crs
    return data, res, profile, nodata, bounds, crs


def profile_for_float(profile, nodata_val=-9999.0):
    p = profile.copy()
    p.update(dtype=rasterio.float32, count=1, nodata=nodata_val, driver="GTiff", compress="lzw")
    return p


def save_geotiff(path: Path, data: np.ndarray, profile, nodata_val=-9999.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    p = profile_for_float(profile, nodata_val=nodata_val)
    out = np.asarray(data, dtype=np.float32)
    out[~np.isfinite(out)] = np.float32(nodata_val)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(out, 1)


def sig_filter(func, kwargs):
    try:
        params = inspect.signature(func).parameters
        return {k: v for k, v in kwargs.items() if k in params}
    except Exception:
        return kwargs


def safe_call(func, args, kwargs):
    kw = sig_filter(func, kwargs)
    try:
        return func(*args, **kw)
    except TypeError:
        return func(*args)


def nanpercentile_safe(a, q):
    finite = np.isfinite(a)
    if finite.sum() == 0:
        return np.nan
    return np.nanpercentile(a, q)


def stretch01(a, p_low, p_high):
    lo = nanpercentile_safe(a, p_low)
    hi = nanpercentile_safe(a, p_high)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = np.nanmin(a)
        hi = np.nanmax(a)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        b = np.zeros_like(a, dtype=np.float32)
        b[~np.isfinite(a)] = np.nan
        return b
    b = (a - lo) / (hi - lo)
    b = np.clip(b, 0.0, 1.0).astype(np.float32)
    b[~np.isfinite(a)] = np.nan
    return b


def fill_nan_with_median(a):
    mask = ~np.isfinite(a)
    if mask.all():
        return a, mask
    v = np.nanmedian(a)
    b = a.copy()
    b[mask] = v
    return b, mask


def extract_array(x):
    if isinstance(x, np.ndarray):
        return x
    if isinstance(x, (list, tuple)):
        for v in x:
            if isinstance(v, np.ndarray):
                return v
        for v in x:
            y = extract_array(v)
            if isinstance(y, np.ndarray):
                return y
        raise TypeError("RVT returned list/tuple without ndarray")
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, np.ndarray):
                return v
        for v in x.values():
            y = extract_array(v)
            if isinstance(y, np.ndarray):
                return y
        raise TypeError("RVT returned dict without ndarray")
    raise TypeError(f"RVT returned unsupported type: {type(x).__name__}")


def as_float32(x):
    return np.asarray(x, dtype=np.float32)


def compute_method(method, dem, res, az, alt, z, rad, n_dir):
    if method == "Raw":
        return dem

    dem2, mask = fill_nan_with_median(dem)

    if method == "Hillshade" and hasattr(rvt.vis, "hillshade"):
        f = rvt.vis.hillshade
        kw = {
            "sun_az": az,
            "sun_el": alt,
            "sun_azimuth": az,
            "sun_altitude": alt,
            "azimuth": az,
            "altitude": alt,
            "z_factor": z,
            "z": z,
        }
        out = safe_call(f, (dem2, res, res), kw)
        out = as_float32(extract_array(out))
        out[mask] = np.nan
        return out

    if method == "Slope":
        if hasattr(rvt.vis, "slope"):
            f = rvt.vis.slope
            kw = {"z_factor": z, "z": z}
            out = safe_call(f, (dem2, res, res), kw)
            out = as_float32(extract_array(out))
            out[mask] = np.nan
            return out
        if hasattr(rvt.vis, "slope_aspect"):
            f = rvt.vis.slope_aspect
            kw = {"z_factor": z, "z": z}
            out = safe_call(f, (dem2, res, res), kw)
            out = as_float32(extract_array(out))
            out[mask] = np.nan
            return out

    if method == "Sky-View Factor" and hasattr(rvt.vis, "sky_view_factor"):
        f = rvt.vis.sky_view_factor
        kw = {
            "resolution": res,
            "compute_svf": True,
            "svf_n_dir": int(n_dir),
            "n_dir": int(n_dir),
            "max_rad": rad,
            "radius": rad,
            "rad": rad,
            "z_factor": z,
            "z": z,
        }
        out = safe_call(f, (dem2,), kw)
        out = as_float32(extract_array(out))
        out[mask] = np.nan
        return out

    if method == "Local Relief Model" and hasattr(rvt.vis, "local_relief_model"):
        f = rvt.vis.local_relief_model
        kw = {"radius": rad, "rad": rad, "max_rad": rad, "z_factor": z, "z": z}
        out = safe_call(f, (dem2, res, res), kw)
        out = as_float32(extract_array(out))
        out[mask] = np.nan
        return out

    if method == "Positive Openness" and hasattr(rvt.vis, "openness_pos"):
        f = rvt.vis.openness_pos
        kw = {"radius": rad, "rad": rad, "max_rad": rad, "n_dir": int(n_dir), "svf_n_dir": int(n_dir), "z_factor": z, "z": z}
        out = safe_call(f, (dem2, res, res), kw)
        out = as_float32(extract_array(out))
        out[mask] = np.nan
        return out

    if method == "Negative Openness" and hasattr(rvt.vis, "openness_neg"):
        f = rvt.vis.openness_neg
        kw = {"radius": rad, "rad": rad, "max_rad": rad, "n_dir": int(n_dir), "svf_n_dir": int(n_dir), "z_factor": z, "z": z}
        out = safe_call(f, (dem2, res, res), kw)
        out = as_float32(extract_array(out))
        out[mask] = np.nan
        return out

    raise RuntimeError(f"Metodo non disponibile o non supportato: {method}")


def latlon_to_global_px(lat, lon, zoom):
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * 256.0 * n
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * 256.0 * n
    return x, y


def clamp_int(v, lo, hi):
    return int(max(lo, min(hi, v)))


class BasemapCache:
    def __init__(self, max_items=6):
        self.max_items = max_items
        self._cache = OrderedDict()

    def get(self, key, loader):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        v = loader()
        self._cache[key] = v
        if len(self._cache) > self.max_items:
            self._cache.popitem(last=False)
        return v


def fetch_tile(z, x, y, session):
    url = f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def build_satellite_rgb(bounds_lonlat, zoom):
    left, bottom, right, top = bounds_lonlat
    if right <= left or top <= bottom:
        return None

    px0, py0 = latlon_to_global_px(top, left, zoom)
    px1, py1 = latlon_to_global_px(bottom, right, zoom)

    min_px = min(px0, px1)
    max_px = max(px0, px1)
    min_py = min(py0, py1)
    max_py = max(py0, py1)

    n = 2 ** zoom
    max_tile = n - 1

    tx0 = clamp_int(math.floor(min_px / 256.0), 0, max_tile)
    tx1 = clamp_int(math.floor((max_px - 1.0) / 256.0), 0, max_tile)
    ty0 = clamp_int(math.floor(min_py / 256.0), 0, max_tile)
    ty1 = clamp_int(math.floor((max_py - 1.0) / 256.0), 0, max_tile)

    tiles_x = tx1 - tx0 + 1
    tiles_y = ty1 - ty0 + 1
    if tiles_x * tiles_y > 64:
        return None

    w = tiles_x * 256
    h = tiles_y * 256
    mosaic = Image.new("RGB", (w, h), (0, 0, 0))

    session = requests.Session()
    session.headers.update({"User-Agent": "RVT-Lidar-Explorer"})

    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = fetch_tile(zoom, tx, ty, session)
            if tile is None:
                continue
            ox = (tx - tx0) * 256
            oy = (ty - ty0) * 256
            mosaic.paste(tile, (ox, oy))

    crop_l = int(round(min_px - tx0 * 256.0))
    crop_t = int(round(min_py - ty0 * 256.0))
    crop_r = int(round(max_px - tx0 * 256.0))
    crop_b = int(round(max_py - ty0 * 256.0))

    crop_l = max(0, min(w, crop_l))
    crop_t = max(0, min(h, crop_t))
    crop_r = max(0, min(w, crop_r))
    crop_b = max(0, min(h, crop_b))

    if crop_r <= crop_l or crop_b <= crop_t:
        return None

    return mosaic.crop((crop_l, crop_t, crop_r, crop_b))


class InputData:
    def __init__(self, root: Path):
        self.root = root
        self.loaded = False
        self.error = None

        self.dtm = None
        self.dsmf = None
        self.dsml = None
        self.ndsm = None
        self.diff = None

        self.res = None
        self.profile = None
        self.bounds = None
        self.crs = None

        self._p_dtm = None
        self._p_f = None
        self._p_l = None

    def load(self):
        prepare_inputs(self.root)

        p_dtm = pick_latest_raster(self.root / "image" / "DTM")
        p_f = pick_latest_raster(self.root / "image" / "DSM_First")
        p_l = pick_latest_raster(self.root / "image" / "DSM_Last")

        if p_dtm is None or p_f is None or p_l is None:
            self.loaded = False
            self.error = "Input mancanti: metti zip o raster in image/DTM, image/DSM_First, image/DSM_Last."
            return

        dtm, res, prof, _, bounds, crs = load_raster(p_dtm)
        dsmf, _, _, _, _, _ = load_raster(p_f)
        dsml, _, _, _, _, _ = load_raster(p_l)

        self.dtm = dtm
        self.dsmf = dsmf
        self.dsml = dsml
        self.ndsm = dsmf - dtm
        self.diff = dsmf - dsml

        self.res = res
        self.profile = prof
        self.bounds = bounds
        self.crs = crs

        self._p_dtm = p_dtm
        self._p_f = p_f
        self._p_l = p_l

        self.loaded = True
        self.error = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RVT Lidar Explorer")
        self.geometry("1200x720")
        self.minsize(1050, 650)

        self.root_path = Path(__file__).resolve().parent
        self.data = InputData(self.root_path)
        self.basemap_cache = BasemapCache(max_items=6)

        self.dataset = tk.StringVar(value="DTM")
        self.method = tk.StringVar(value="Hillshade")

        self.azimuth = tk.DoubleVar(value=315.0)
        self.altitude = tk.DoubleVar(value=45.0)
        self.z_factor = tk.DoubleVar(value=1.0)
        self.radius = tk.DoubleVar(value=10.0)
        self.n_dir = tk.IntVar(value=16)

        self.p_low = tk.DoubleVar(value=2.0)
        self.p_high = tk.DoubleVar(value=98.0)
        self.invert = tk.BooleanVar(value=False)

        self.basemap_on = tk.BooleanVar(value=False)
        self.basemap_mix = tk.DoubleVar(value=0.35)

        self.param_widgets = {}

        self._update_job = None
        self._pan_state = None
        self._home_limits = None
        self._last_shape = None

        self._build_ui()
        self.reload_inputs()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self, padding=0)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(main, padding=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        top = ttk.Frame(left)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text=str(self.root_path)).grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="Reload", command=self.reload_inputs).grid(row=0, column=1, padx=(8, 0))

        ds_box = ttk.LabelFrame(left, text="Dataset", padding=8)
        ds_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for i, name in enumerate(["DTM", "DSM_First", "DSM_Last", "nDSM", "First-Last", "Original"]):
            ttk.Radiobutton(ds_box, text=name, value=name, variable=self.dataset, command=lambda: (self.update_param_states(), self.schedule_update())).grid(row=i, column=0, sticky="w")

        basemap_box = ttk.LabelFrame(left, text="Basemap (Satellite)", padding=8)
        basemap_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        basemap_box.columnconfigure(1, weight=1)

        self.basemap_cb = ttk.Checkbutton(basemap_box, text="Basemap", variable=self.basemap_on, command=lambda: (self.update_param_states(), self.schedule_update()))
        self.basemap_cb.grid(row=0, column=0, sticky="w")

        self.basemap_scale = ttk.Scale(basemap_box, from_=0.0, to=1.0, command=lambda v: self._set_float(self.basemap_mix, v))
        self.basemap_scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.basemap_mix_lbl = ttk.Label(basemap_box, text="")
        self.basemap_mix_lbl.grid(row=0, column=2, sticky="e")

        def sync_mix(*_):
            self.basemap_mix_lbl.config(text=f"{float(self.basemap_mix.get()):.2f}")

        self.basemap_mix.trace_add("write", sync_mix)
        sync_mix()
        self.basemap_scale.set(float(self.basemap_mix.get()))

        meth_box = ttk.LabelFrame(left, text="Metodo RVT", padding=8)
        meth_box.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        meth_box.columnconfigure(0, weight=1)
        self.method_combo = ttk.Combobox(meth_box, textvariable=self.method, values=self.available_methods(), state="readonly")
        self.method_combo.grid(row=0, column=0, sticky="ew")
        self.method_combo.bind("<<ComboboxSelected>>", lambda e: (self.update_param_states(), self.schedule_update()))

        par_box = ttk.LabelFrame(left, text="Parametri", padding=8)
        par_box.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        par_box.columnconfigure(0, weight=1)

        self._add_slider(par_box, "Azimuth", "azimuth", self.azimuth, 0.0, 360.0, 0)
        self._add_slider(par_box, "Altitude", "altitude", self.altitude, 0.0, 90.0, 1)
        self._add_slider(par_box, "Z-factor", "z_factor", self.z_factor, 0.1, 10.0, 2)
        self._add_slider(par_box, "Radius", "radius", self.radius, 1.0, 200.0, 3)
        self._add_slider(par_box, "Directions", "n_dir", self.n_dir, 4, 64, 4, is_int=True)
        self._add_slider(par_box, "Stretch low (p)", "p_low", self.p_low, 0.0, 20.0, 5)
        self._add_slider(par_box, "Stretch high (p)", "p_high", self.p_high, 80.0, 100.0, 6)

        self.invert_cb = ttk.Checkbutton(par_box, text="Invert", variable=self.invert, command=self.schedule_update)
        self.invert_cb.grid(row=7, column=0, sticky="w", pady=(6, 0))

        btn_box = ttk.Frame(left)
        btn_box.grid(row=5, column=0, sticky="ew")
        btn_box.columnconfigure(0, weight=1)
        ttk.Button(btn_box, text="Export corrente GeoTIFF", command=self.export_current).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(btn_box, text="Batch pipeline base", command=self.batch_pipeline).grid(row=1, column=0, sticky="ew")

        self.status = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.status, wraplength=360).grid(row=6, column=0, sticky="ew", pady=(10, 0))

        fig = Figure(figsize=(6, 5), dpi=100)
        fig.patch.set_facecolor("black")
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        self.ax = fig.add_subplot(111)
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")

        self.im_base = None
        self.im_over = None

        self.canvas = FigureCanvasTkAgg(fig, master=right)
        w = self.canvas.get_tk_widget()
        w.grid(row=0, column=0, sticky="nsew")
        w.configure(borderwidth=0, highlightthickness=0)
        self._connect_mouse()

    def available_methods(self):
        methods = ["Raw"]
        if hasattr(rvt.vis, "hillshade"):
            methods.append("Hillshade")
        if hasattr(rvt.vis, "slope") or hasattr(rvt.vis, "slope_aspect"):
            methods.append("Slope")
        if hasattr(rvt.vis, "sky_view_factor"):
            methods.append("Sky-View Factor")
        if hasattr(rvt.vis, "local_relief_model"):
            methods.append("Local Relief Model")
        if hasattr(rvt.vis, "openness_pos"):
            methods.append("Positive Openness")
        if hasattr(rvt.vis, "openness_neg"):
            methods.append("Negative Openness")
        return methods

    def _add_slider(self, parent, label, key, var, vmin, vmax, row, is_int=False):
        frm = ttk.Frame(parent)
        frm.grid(row=row, column=0, sticky="ew", pady=2)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text=label).grid(row=0, column=0, sticky="w")

        if is_int:
            scale = ttk.Scale(frm, from_=vmin, to=vmax, command=lambda v: self._set_int(var, v))
        else:
            scale = ttk.Scale(frm, from_=vmin, to=vmax, command=lambda v: self._set_float(var, v))

        scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.param_widgets[key] = scale

        val_lbl = ttk.Label(frm, text="")
        val_lbl.grid(row=0, column=2, sticky="e")

        def sync_label(*_):
            val = var.get()
            val_lbl.config(text=str(int(val)) if is_int else f"{float(val):.2f}")

        var.trace_add("write", sync_label)
        sync_label()
        scale.set(int(var.get()) if is_int else float(var.get()))

    def _set_int(self, var, v):
        try:
            var.set(int(round(float(v))))
        except Exception:
            pass
        self.schedule_update()

    def _set_float(self, var, v):
        try:
            var.set(float(v))
        except Exception:
            pass
        self.schedule_update()

    def reload_inputs(self):
        self.data.load()
        if not self.data.loaded:
            self.status.set(self.data.error or "Errore input.")
            self.update_param_states()
            self._show_blank()
            return
        self.status.set("OK")
        self.update_param_states()
        self.schedule_update()

    def update_param_states(self):
        ds = self.dataset.get()
        is_original = ds == "Original"
        m = self.method.get()

        if is_original:
            self.method_combo.state(["disabled"])
            self.invert_cb.state(["disabled"])
            self.basemap_cb.state(["disabled"])
            self.basemap_scale.state(["disabled"])
        else:
            self.method_combo.state(["!disabled"])
            self.invert_cb.state(["!disabled"])
            self.basemap_cb.state(["!disabled"])
            self.basemap_scale.state(["!disabled"] if self.basemap_on.get() else ["disabled"])

        use_params = (not is_original) and (m != "Raw")

        need_az_alt = use_params and (m == "Hillshade")
        need_rad = use_params and (m in {"Sky-View Factor", "Local Relief Model", "Positive Openness", "Negative Openness"})
        need_dir = use_params and (m in {"Sky-View Factor", "Positive Openness", "Negative Openness"})
        need_z = use_params and (m in {"Hillshade", "Slope", "Sky-View Factor", "Local Relief Model", "Positive Openness", "Negative Openness"})

        self.param_widgets["azimuth"].state(["!disabled"] if need_az_alt else ["disabled"])
        self.param_widgets["altitude"].state(["!disabled"] if need_az_alt else ["disabled"])
        self.param_widgets["radius"].state(["!disabled"] if need_rad else ["disabled"])
        self.param_widgets["n_dir"].state(["!disabled"] if need_dir else ["disabled"])
        self.param_widgets["z_factor"].state(["!disabled"] if need_z else ["disabled"])
        self.param_widgets["p_low"].state(["!disabled"] if not is_original else ["disabled"])
        self.param_widgets["p_high"].state(["!disabled"] if not is_original else ["disabled"])

    def schedule_update(self):
        if self._update_job is not None:
            try:
                self.after_cancel(self._update_job)
            except Exception:
                pass
        self._update_job = self.after(120, self.update_view)

    def _stretch_for_display(self, arr):
        p_lo = float(self.p_low.get())
        p_hi = float(self.p_high.get())
        if p_hi <= p_lo:
            p_lo, p_hi = 2.0, 98.0
        return stretch01(as_float32(arr), p_lo, p_hi)

    def _bounds_lonlat(self):
        bounds = self.data.bounds
        crs = self.data.crs
        if bounds is None:
            return None
        if crs is not None and crs.to_string() != "EPSG:4326":
            try:
                b = rasterio.warp.transform_bounds(crs, "EPSG:4326", *bounds, densify_pts=21)
                return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
            except Exception:
                return bounds
        return bounds

    def _satellite(self, w, h):
        bounds_ll = self._bounds_lonlat()
        if bounds_ll is None:
            return None

        for zbm in SAT_ZOOMS_TRY:
            cache_key = ("sat", zbm, w, h, bounds_ll)

            def loader():
                img = build_satellite_rgb(bounds_ll, zbm)
                if img is None:
                    return None
                img = img.resize((w, h), resample=Image.BILINEAR)
                return np.asarray(img, dtype=np.float32) / 255.0

            sat = self.basemap_cache.get(cache_key, loader)
            if sat is not None:
                return sat
        return None

    def _get_dataset_array(self, ds):
        if ds == "DTM":
            return self.data.dtm
        if ds == "DSM_First":
            return self.data.dsmf
        if ds == "DSM_Last":
            return self.data.dsml
        if ds == "nDSM":
            return self.data.ndsm
        if ds == "First-Last":
            return self.data.diff
        return None

    def update_view(self):
        self._update_job = None
        if not self.data.loaded:
            self._show_blank()
            return

        ds = self.dataset.get()

        try:
            if ds == "Original":
                ref = self.data.dtm
                if ref is None:
                    raise RuntimeError("DTM mancante.")
                h, w = ref.shape
                sat = self._satellite(w, h)
                if sat is None:
                    raise RuntimeError("Satellite non disponibile (rete o area troppo grande).")
                self._draw(sat, None, alpha_over=0.0, reset=False)
                self.status.set("Original: Satellite")
                return

            dem = self._get_dataset_array(ds)
            if dem is None:
                raise RuntimeError("Dataset non disponibile.")

            method = self.method.get()
            res = float(self.data.res)
            az = float(self.azimuth.get())
            alt = float(self.altitude.get())
            z = float(self.z_factor.get())
            rad = float(self.radius.get())
            n_dir = int(self.n_dir.get())

            out = compute_method(method, dem, res, az, alt, z, rad, n_dir)
            out = as_float32(out)

            disp_over = self._stretch_for_display(out)
            cmap = "gray_r" if self.invert.get() else "gray"
            cmap_obj = mpl.colormaps.get_cmap(cmap).copy()
            cmap_obj.set_bad("black")

            base = None
            alpha_over = 1.0
            if self.basemap_on.get():
                base = self._satellite(disp_over.shape[1], disp_over.shape[0])
                mix = float(self.basemap_mix.get())
                mix = max(0.0, min(1.0, mix))
                alpha_over = 1.0 - mix

            self._draw(base, (disp_over, cmap_obj), alpha_over=alpha_over, reset=False)

            mn = float(np.nanmin(out)) if np.isfinite(out).any() else np.nan
            mx = float(np.nanmax(out)) if np.isfinite(out).any() else np.nan
            self.status.set(f"{ds} | {method} | min {mn:.4f} | max {mx:.4f}")

        except Exception as e:
            self.status.set(f"Errore: {e}")
            self._show_blank()

    def _show_blank(self):
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")
        self.ax.figure.patch.set_facecolor("black")
        self.im_base = None
        self.im_over = None
        self.canvas.draw_idle()

    def _draw(self, base_rgb01, over_pack, alpha_over=1.0, reset=False):
        h = None
        w = None
        if over_pack is not None:
            over01, _ = over_pack
            h, w = over01.shape[:2]
        elif base_rgb01 is not None:
            h, w = base_rgb01.shape[:2]

        if h is None or w is None:
            self._show_blank()
            return

        keep = (not reset) and (self._last_shape == (h, w)) and (self.im_over is not None or self.im_base is not None)
        prev_xlim = self.ax.get_xlim() if keep else None
        prev_ylim = self.ax.get_ylim() if keep else None

        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor("black")
        self.ax.figure.patch.set_facecolor("black")

        if base_rgb01 is not None:
            base_rgb01 = np.asarray(base_rgb01, dtype=np.float32)
            self.im_base = self.ax.imshow(base_rgb01, interpolation="nearest", alpha=1.0)
        else:
            self.im_base = None

        if over_pack is not None and alpha_over > 0.0:
            over01, cmap_obj = over_pack
            over01 = np.asarray(over01, dtype=np.float32)
            m1 = np.ma.masked_invalid(over01)
            self.im_over = self.ax.imshow(m1, cmap=cmap_obj, interpolation="nearest", alpha=alpha_over)
        else:
            self.im_over = None

        if keep and prev_xlim is not None and prev_ylim is not None:
            self.ax.set_xlim(prev_xlim)
            self.ax.set_ylim(prev_ylim)

        if self._home_limits is None or reset:
            self._home_limits = (self.ax.get_xlim(), self.ax.get_ylim())

        self._last_shape = (h, w)
        self.canvas.draw_idle()

    def export_current(self):
        if not self.data.loaded:
            return
        ds = self.dataset.get()
        if ds == "Original":
            messagebox.showerror("Export", "Export disabilitato su Original (satellite).")
            return
        arr = self._get_dataset_array(ds)
        if arr is None:
            messagebox.showerror("Export", "Dataset non disponibile.")
            return
        try:
            method_name = self.method.get()
            res = float(self.data.res)
            az = float(self.azimuth.get())
            alt = float(self.altitude.get())
            z = float(self.z_factor.get())
            rad = float(self.radius.get())
            n_dir = int(self.n_dir.get())

            out = compute_method(method_name, arr, res, az, alt, z, rad, n_dir)
            out = as_float32(out)

            out_dir = self.root_path / "output_rvt_gui"
            fname = f"{ds}__{method_name.replace(' ', '_').replace('-', '_')}.tif"
            save_geotiff(out_dir / fname, out, self.data.profile)
            self.status.set(f"Export: {out_dir / fname}")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def batch_pipeline(self):
        if not self.data.loaded:
            return
        out_root = self.root_path / "output_rvt_batch"
        out_root.mkdir(parents=True, exist_ok=True)
        log_path = out_root / "batch_log.txt"

        ok = 0
        fail = 0
        logs = []

        try:
            dtm = self.data.dtm
            dsmf = self.data.dsmf
            dsml = self.data.dsml
            res = float(self.data.res)
            prof = self.data.profile

            if dtm is None or dsmf is None or dsml is None:
                raise RuntimeError("Input incompleti per batch.")

            if hasattr(rvt.vis, "hillshade"):
                hs = compute_method("Hillshade", dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
                save_geotiff(out_root / "1_DTM_Hillshade.tif", hs, prof)

            if hasattr(rvt.vis, "sky_view_factor"):
                svf = compute_method("Sky-View Factor", dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
                save_geotiff(out_root / "2_DTM_SkyViewFactor.tif", svf, prof)

            save_geotiff(out_root / "3_nDSM.tif", dsmf - dtm, prof)
            save_geotiff(out_root / "4_FirstMinusLast.tif", dsmf - dsml, prof)
            ok = 1
        except Exception as e:
            fail = 1
            logs.append(f"{type(e).__name__}: {e}")

        log_path.write_text("\n".join(logs), encoding="utf-8")
        self.status.set(f"Batch OK: {ok} | Fail: {fail} | Log: {log_path}")

    def _connect_mouse(self):
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

    def _on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        base = 1.2
        btn = getattr(event, "button", None)
        if btn in ("up", 1):
            scale = 1 / base
        else:
            scale = base

        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        x = event.xdata
        y = event.ydata

        w = (xlim[1] - xlim[0]) * scale
        h = (ylim[1] - ylim[0]) * scale

        rx = (x - xlim[0]) / (xlim[1] - xlim[0])
        ry = (y - ylim[0]) / (ylim[1] - ylim[0])

        self.ax.set_xlim(x - w * rx, x + w * (1 - rx))
        self.ax.set_ylim(y - h * ry, y + h * (1 - ry))
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes != self.ax:
            return
        if event.dblclick and event.button == 1 and self._home_limits is not None:
            xlim, ylim = self._home_limits
            self.ax.set_xlim(xlim)
            self.ax.set_ylim(ylim)
            self.canvas.draw_idle()
            return
        if event.button != 1:
            return
        if event.xdata is None or event.ydata is None:
            return
        self._pan_state = (event.xdata, event.ydata, self.ax.get_xlim(), self.ax.get_ylim())

    def _on_motion(self, event):
        if self._pan_state is None:
            return
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        x0, y0, xlim0, ylim0 = self._pan_state
        dx = x0 - event.xdata
        dy = y0 - event.ydata

        self.ax.set_xlim(xlim0[0] + dx, xlim0[1] + dx)
        self.ax.set_ylim(ylim0[0] + dy, ylim0[1] + dy)
        self.canvas.draw_idle()

    def _on_release(self, event):
        if event.button == 1:
            self._pan_state = None

if __name__ == "__main__":
    App().mainloop()