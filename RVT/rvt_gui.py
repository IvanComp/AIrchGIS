import inspect
from collections import OrderedDict
from pathlib import Path
import numpy as np
import rasterio
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import rvt.vis

EXTS = {".tif", ".tiff", ".asc"}

def key_from_name(name: str) -> str:
    stem = Path(name).stem
    s = stem.lower()
    tokens = [
        "_dtm",
        "_dsmfirst",
        "_dsmlast",
        "_dsm_first",
        "_dsm_last",
        "_dsm-first",
        "_dsm-last",
    ]
    for t in tokens:
        if s.endswith(t):
            return stem[: len(stem) - len(t)]
    return stem

def list_rasters(folder: Path):
    if not folder.exists():
        return []
    out = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            out.append(p)
    return out

def scan_triplets(root: Path):
    dtm_dir = root / "image" / "DTM"
    first_dir = root / "image" / "DSMfirst"
    last_dir = root / "image" / "DSMlast"

    dtm_files = list_rasters(dtm_dir)
    first_files = list_rasters(first_dir)
    last_files = list_rasters(last_dir)

    dtm_map = {}
    first_map = {}
    last_map = {}

    for p in dtm_files:
        k = key_from_name(p.name)
        dtm_map.setdefault(k, p)
    for p in first_files:
        k = key_from_name(p.name)
        first_map.setdefault(k, p)
    for p in last_files:
        k = key_from_name(p.name)
        last_map.setdefault(k, p)

    keys = sorted(set(dtm_map.keys()) & set(first_map.keys()) & set(last_map.keys()))
    triplets = {}
    for k in keys:
        triplets[k] = {"DTM": dtm_map[k], "DSMfirst": first_map[k], "DSMlast": last_map[k]}
    return triplets

def load_raster(path: Path):
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
        res = float(src.res[0])
        profile = src.profile.copy()
    return data, res, profile, nodata

def profile_for_float(profile, nodata_val=-9999.0):
    p = profile.copy()
    p.update(dtype=rasterio.float32, count=1, nodata=nodata_val, driver="GTiff", compress="lzw")
    return p

def save_geotiff(path: Path, data: np.ndarray, profile, nodata_val=-9999.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    p = profile_for_float(profile, nodata_val=nodata_val)
    out = np.array(data, dtype=np.float32, copy=True)
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

def compute_method(method, dem, res, az, alt, z, rad, n_dir):
    if method == "Raw":
        return dem
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
        return safe_call(f, (dem, res, res), kw)
    if method == "Slope":
        if hasattr(rvt.vis, "slope"):
            f = rvt.vis.slope
            kw = {"z_factor": z, "z": z}
            return safe_call(f, (dem, res, res), kw)
        if hasattr(rvt.vis, "slope_aspect"):
            f = rvt.vis.slope_aspect
            kw = {"z_factor": z, "z": z}
            out = safe_call(f, (dem, res, res), kw)
            if isinstance(out, (tuple, list)) and len(out) >= 1:
                return out[0]
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
        out = safe_call(f, (dem,), kw)
        if isinstance(out, (tuple, list)) and len(out) >= 1:
            return out[0]
        return out
    if method == "Local Relief Model" and hasattr(rvt.vis, "local_relief_model"):
        f = rvt.vis.local_relief_model
        kw = {
            "radius": rad,
            "rad": rad,
            "max_rad": rad,
            "z_factor": z,
            "z": z,
        }
        return safe_call(f, (dem, res, res), kw)
    if method == "Positive Openness" and hasattr(rvt.vis, "openness_pos"):
        f = rvt.vis.openness_pos
        kw = {
            "radius": rad,
            "rad": rad,
            "max_rad": rad,
            "n_dir": int(n_dir),
            "svf_n_dir": int(n_dir),
            "z_factor": z,
            "z": z,
        }
        return safe_call(f, (dem, res, res), kw)
    if method == "Negative Openness" and hasattr(rvt.vis, "openness_neg"):
        f = rvt.vis.openness_neg
        kw = {
            "radius": rad,
            "rad": rad,
            "max_rad": rad,
            "n_dir": int(n_dir),
            "svf_n_dir": int(n_dir),
            "z_factor": z,
            "z": z,
        }
        return safe_call(f, (dem, res, res), kw)
    raise RuntimeError(f"Metodo non disponibile o non supportato: {method}")

class TileCache:
    def __init__(self, max_items=3):
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

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RVT Lidar Explorer")
        self.geometry("1200x720")
        self.minsize(1050, 650)

        self.root_dir = tk.StringVar(value=str(Path.cwd()))
        self.triplets = {}
        self.tile_keys = []
        self.selected_tile = tk.StringVar(value="")
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

        self._update_job = None
        self.cache = TileCache(max_items=3)

        self._build_ui()
        self.refresh_triplets()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(main, padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        path_box = ttk.LabelFrame(left, text="Root progetto", padding=8)
        path_box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        path_box.columnconfigure(0, weight=1)
        ttk.Entry(path_box, textvariable=self.root_dir).grid(row=0, column=0, sticky="ew")
        ttk.Button(path_box, text="Sfoglia", command=self.pick_root).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(path_box, text="Refresh", command=self.refresh_triplets).grid(row=0, column=2, padx=(8, 0))

        tile_box = ttk.LabelFrame(left, text="Tile", padding=8)
        tile_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        tile_box.columnconfigure(0, weight=1)
        self.tile_combo = ttk.Combobox(tile_box, textvariable=self.selected_tile, values=[], state="readonly")
        self.tile_combo.grid(row=0, column=0, sticky="ew")
        self.tile_combo.bind("<<ComboboxSelected>>", lambda e: self.schedule_update())

        ds_box = ttk.LabelFrame(left, text="Dataset", padding=8)
        ds_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for i, name in enumerate(["DTM", "DSMfirst", "DSMlast", "nDSM", "First-Last"]):
            ttk.Radiobutton(ds_box, text=name, value=name, variable=self.dataset, command=self.schedule_update).grid(row=i, column=0, sticky="w")

        meth_box = ttk.LabelFrame(left, text="Metodo RVT", padding=8)
        meth_box.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        meth_box.columnconfigure(0, weight=1)
        self.method_combo = ttk.Combobox(meth_box, textvariable=self.method, values=self.available_methods(), state="readonly")
        self.method_combo.grid(row=0, column=0, sticky="ew")
        self.method_combo.bind("<<ComboboxSelected>>", lambda e: self.schedule_update())

        par_box = ttk.LabelFrame(left, text="Parametri", padding=8)
        par_box.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        par_box.columnconfigure(0, weight=1)

        self._add_slider(par_box, "Azimuth", self.azimuth, 0.0, 360.0, 0)
        self._add_slider(par_box, "Altitude", self.altitude, 0.0, 90.0, 1)
        self._add_slider(par_box, "Z-factor", self.z_factor, 0.1, 10.0, 2)
        self._add_slider(par_box, "Radius", self.radius, 1.0, 200.0, 3)
        self._add_slider(par_box, "Directions", self.n_dir, 4, 64, 4, is_int=True)
        self._add_slider(par_box, "Stretch low (p)", self.p_low, 0.0, 20.0, 5)
        self._add_slider(par_box, "Stretch high (p)", self.p_high, 80.0, 100.0, 6)

        ttk.Checkbutton(par_box, text="Invert", variable=self.invert, command=self.schedule_update).grid(row=7, column=0, sticky="w", pady=(6, 0))

        btn_box = ttk.Frame(left)
        btn_box.grid(row=5, column=0, sticky="ew")
        btn_box.columnconfigure(0, weight=1)
        ttk.Button(btn_box, text="Export corrente GeoTIFF", command=self.export_current).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(btn_box, text="Batch pipeline base", command=self.batch_pipeline).grid(row=1, column=0, sticky="ew")

        self.status = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.status, wraplength=360).grid(row=6, column=0, sticky="ew", pady=(10, 0))

        fig = Figure(figsize=(6, 5), dpi=100)
        self.ax = fig.add_subplot(111)
        self.ax.set_axis_off()
        self.im = None
        self.canvas = FigureCanvasTkAgg(fig, master=right)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _add_slider(self, parent, label, var, vmin, vmax, row, is_int=False):
        frm = ttk.Frame(parent)
        frm.grid(row=row, column=0, sticky="ew", pady=2)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text=label).grid(row=0, column=0, sticky="w")
        if is_int:
            scale = ttk.Scale(frm, from_=vmin, to=vmax, command=lambda v: self._set_int(var, v))
        else:
            scale = ttk.Scale(frm, from_=vmin, to=vmax, command=lambda v: self._on_scale(var, v))
        scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        val_lbl = ttk.Label(frm, text="")
        val_lbl.grid(row=0, column=2, sticky="e")
        def sync_label(*_):
            val = var.get()
            if is_int:
                val_lbl.config(text=str(int(val)))
            else:
                val_lbl.config(text=f"{float(val):.2f}")
        var.trace_add("write", sync_label)
        sync_label()
        if is_int:
            scale.set(int(var.get()))
        else:
            scale.set(float(var.get()))

    def _set_int(self, var, v):
        try:
            var.set(int(round(float(v))))
        except Exception:
            pass
        self.schedule_update()

    def _on_scale(self, var, v):
        try:
            var.set(float(v))
        except Exception:
            pass
        self.schedule_update()

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

    def pick_root(self):
        p = filedialog.askdirectory(initialdir=self.root_dir.get())
        if p:
            self.root_dir.set(p)
            self.refresh_triplets()

    def refresh_triplets(self):
        root = Path(self.root_dir.get()).expanduser().resolve()
        self.triplets = scan_triplets(root)
        self.tile_keys = sorted(self.triplets.keys())
        self.tile_combo["values"] = self.tile_keys
        if self.tile_keys:
            if self.selected_tile.get() not in self.tile_keys:
                self.selected_tile.set(self.tile_keys[0])
        else:
            self.selected_tile.set("")
        self.method_combo["values"] = self.available_methods()
        if self.method.get() not in self.method_combo["values"]:
            self.method.set(self.method_combo["values"][0] if self.method_combo["values"] else "Raw")
        self.schedule_update()

    def load_tile(self, key):
        paths = self.triplets.get(key)
        if not paths:
            raise RuntimeError("Tile non trovato")
        dtm, res, prof, _ = load_raster(paths["DTM"])
        dsmf, _, _, _ = load_raster(paths["DSMfirst"])
        dsml, _, _, _ = load_raster(paths["DSMlast"])
        ndsm = dsmf - dtm
        diff = dsmf - dsml
        return {
            "DTM": dtm,
            "DSMfirst": dsmf,
            "DSMlast": dsml,
            "nDSM": ndsm,
            "First-Last": diff,
            "res": res,
            "profile": prof,
        }

    def schedule_update(self):
        if self._update_job is not None:
            try:
                self.after_cancel(self._update_job)
            except Exception:
                pass
        self._update_job = self.after(150, self.update_view)

    def update_view(self):
        self._update_job = None
        key = self.selected_tile.get()
        if not key:
            self.status.set("Nessuna tripletta disponibile. Verifica le cartelle image/DTM, image/DSMfirst, image/DSMlast.")
            self._show_blank()
            return
        try:
            tile = self.cache.get(key, lambda: self.load_tile(key))
            base = self.dataset.get()
            method = self.method.get()
            dem = tile.get(base)
            if dem is None:
                raise RuntimeError("Dataset non disponibile")
            res = tile["res"]
            az = float(self.azimuth.get())
            alt = float(self.altitude.get())
            z = float(self.z_factor.get())
            rad = float(self.radius.get())
            n_dir = int(self.n_dir.get())
            out = compute_method(method, dem, res, az, alt, z, rad, n_dir)
            out = np.array(out, dtype=np.float32, copy=False)
            p_lo = float(self.p_low.get())
            p_hi = float(self.p_high.get())
            if p_hi <= p_lo:
                p_lo, p_hi = 2.0, 98.0
            disp = stretch01(out, p_lo, p_hi)
            cmap = "gray_r" if self.invert.get() else "gray"
            self._draw(disp, cmap=cmap, title=f"{key} | {base} | {method}")
            mn = float(np.nanmin(out)) if np.isfinite(out).any() else np.nan
            mx = float(np.nanmax(out)) if np.isfinite(out).any() else np.nan
            self.status.set(f"Triplette: {len(self.tile_keys)} | res: {res} | min: {mn:.4f} | max: {mx:.4f}")
        except Exception as e:
            self.status.set(f"Errore: {e}")
            self._show_blank()

    def _show_blank(self):
        self.ax.clear()
        self.ax.set_axis_off()
        self.im = None
        self.canvas.draw_idle()

    def _draw(self, img01, cmap="gray", title=""):
        self.ax.clear()
        self.ax.set_axis_off()
        m = np.ma.masked_invalid(img01)
        self.im = self.ax.imshow(m, cmap=cmap, interpolation="nearest")
        self.ax.set_title(title, fontsize=10)
        self.canvas.draw_idle()

    def export_current(self):
        key = self.selected_tile.get()
        if not key:
            return
        try:
            tile = self.cache.get(key, lambda: self.load_tile(key))
            base = self.dataset.get()
            method = self.method.get()
            dem = tile.get(base)
            if dem is None:
                raise RuntimeError("Dataset non disponibile")
            res = tile["res"]
            az = float(self.azimuth.get())
            alt = float(self.altitude.get())
            z = float(self.z_factor.get())
            rad = float(self.radius.get())
            n_dir = int(self.n_dir.get())
            out = compute_method(method, dem, res, az, alt, z, rad, n_dir)
            out = np.array(out, dtype=np.float32, copy=False)
            out_dir = Path(self.root_dir.get()) / "output_rvt_gui" / key
            fname = f"{base}__{method.replace(' ', '_').replace('-', '_')}__az{int(round(az))}__alt{int(round(alt))}__z{z:.2f}__r{rad:.1f}__n{int(n_dir)}.tif"
            save_geotiff(out_dir / fname, out, tile["profile"])
            self.status.set(f"Export: {out_dir / fname}")
        except Exception as e:
            messagebox.showerror("Export fallito", str(e))

    def batch_pipeline(self):
        root = Path(self.root_dir.get())
        if not self.tile_keys:
            return
        out_root = root / "output_rvt_batch"
        ok = 0
        fail = 0
        for key in self.tile_keys:
            try:
                tile = self.load_tile(key)
                res = tile["res"]
                prof = tile["profile"]
                dtm = tile["DTM"]
                dsmf = tile["DSMfirst"]
                dsml = tile["DSMlast"]
                out_dir = out_root / key
                if hasattr(rvt.vis, "hillshade"):
                    hs = compute_method("Hillshade", dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
                    save_geotiff(out_dir / "1_DTM_Hillshade.tif", hs, prof)
                if hasattr(rvt.vis, "sky_view_factor"):
                    svf = compute_method("Sky-View Factor", dtm, res, 315.0, 45.0, 1.0, 10.0, 16)
                    save_geotiff(out_dir / "2_DTM_SkyViewFactor.tif", svf, prof)
                ndsm = dsmf - dtm
                save_geotiff(out_dir / "3_nDSM.tif", ndsm, prof)
                diff = dsmf - dsml
                save_geotiff(out_dir / "4_FirstMinusLast.tif", diff, prof)
                ok += 1
            except Exception:
                fail += 1
        self.status.set(f"Batch completato. OK: {ok} | Fail: {fail} | Output: {out_root}")

if __name__ == "__main__":
    App().mainloop()