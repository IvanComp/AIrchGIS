

from __future__ import annotations

from pathlib import Path

import numpy as np

VIEWER_AZIMUTH = -44.0
VIEWER_ELEVATION = 29.0
MM_PER_INCH = 25.4


def viewer_exaggeration(x_span, y_span, z_span, cap=2.5):

    xy = max(1.0, float(max(x_span, y_span)))
    z = max(1e-6, float(z_span))
    return float(np.clip(0.42 * xy / z, 0.45, cap))


def _downsample(a, max_side):
    h, w = a.shape
    step = max(1, int(np.ceil(max(h, w) / float(max_side))))
    return a[::step, ::step], step


def _nice_length(span):

    target = span / 5.0
    base = 10 ** np.floor(np.log10(max(target, 1e-9)))
    for m in (5, 2, 1):
        if m * base <= target:
            return m * base
    return base


def _hillshade(z, res, azimuth=315.0, altitude=35.0):
    gy, gx = np.gradient(z, res)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(azimuth), np.radians(altitude)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(hs, 0, 1)


def render_3d_figure(dem, res, output, drape=None, azimuth=VIEWER_AZIMUTH, elevation=VIEWER_ELEVATION,
                     vertical_exaggeration=None, dpi=300, width_mm=190.0, height_mm=None, scale_bar=True,
                     north_arrow=True, caption=None, max_side=500, cmap="gray"):

    import matplotlib
    import matplotlib.patches

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import colormaps

    output = Path(output)
    fmt = output.suffix.lower().lstrip(".")
    if fmt not in ("pdf", "png"):
        raise ValueError("Output must end in .pdf or .png")
    z = np.asarray(dem, dtype=np.float64)
    if not np.isfinite(z).any():
        raise ValueError("The terrain model has no valid values.")
    z_small, step = _downsample(z, max_side)
    r = float(res) * step
    h, w = z_small.shape
    x = np.arange(w) * r
    y = (h - 1 - np.arange(h)) * r
    X, Y = np.meshgrid(x, y)
    valid = np.isfinite(z_small)
    if (~valid).any():

        from scipy import ndimage

        valid &= ndimage.binary_erosion(valid, iterations=2, border_value=1)
        z_small = np.where(valid, z_small, np.nan)
    zmin, zmax = float(np.nanmin(z_small)), float(np.nanmax(z_small))
    ve = float(vertical_exaggeration) if vertical_exaggeration else viewer_exaggeration(x[-1] if w > 1 else r, y[0] if h > 1 else r, zmax - zmin)

    if drape is not None:
        d, _ = _downsample(np.asarray(drape, dtype=np.float64), max_side)
        d = d[:h, :w]
        drape_name = "relief visualization"
    else:
        d = _hillshade(np.where(valid, z_small, np.nanmedian(z_small)), r)
        drape_name = "hillshade"
    finite = d[np.isfinite(d) & valid]
    lo, hi = (np.percentile(finite, [2, 98]) if finite.size else (0.0, 1.0))
    norm = np.clip((d - lo) / max(hi - lo, 1e-12), 0, 1)
    colors = colormaps[cmap](np.nan_to_num(norm))
    colors[~valid] = (1, 1, 1, 0)
    Z = np.where(valid, z_small, np.nan) * ve

    height_mm = height_mm or width_mm * 0.68
    fig = plt.figure(figsize=(width_mm / MM_PER_INCH, height_mm / MM_PER_INCH), dpi=dpi)

    bottom = 0.07 if caption else 0.0
    ax = fig.add_axes([-0.22, bottom - 0.22, 1.44, (1.0 - bottom) + 0.44], projection="3d")
    ax.plot_surface(X, Y, Z, facecolors=colors, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=False,
                    rasterized=True)
    xs, ys, zs = x[-1] - x[0] if w > 1 else r, y[0] - y[-1] if h > 1 else r, max((zmax - zmin) * ve, 1e-6)
    ax.set_box_aspect((xs, ys, zs))
    ax.view_init(elev=float(elevation), azim=float(azimuth))
    ax.set_axis_off()

    if scale_bar or north_arrow:

        from mpl_toolkits.mplot3d import proj3d

        fig.canvas.draw()

        def to_fig(px, py, pz):
            u, v, _ = proj3d.proj_transform(px, py, pz, ax.get_proj())
            disp = ax.transData.transform((u, v))
            return fig.transFigure.inverted().transform(disp)

        zb = zmin * ve
    if scale_bar:
        length = _nice_length(xs)
        p0, p1 = to_fig(x[0], y[-1], zb), to_fig(x[0] + length, y[-1], zb)
        off = np.array([0.0, -0.025])
        fig.add_artist(plt.Line2D([p0[0] + off[0], p1[0] + off[0]], [p0[1] + off[1], p1[1] + off[1]],
                                  color="black", linewidth=2.5, solid_capstyle="butt", transform=fig.transFigure))
        label = f"{length:g} m" if length < 1000 else f"{length / 1000:g} km"
        mid = (p0 + p1) / 2 + off
        fig.text(mid[0], mid[1] - 0.012, label, fontsize=7, ha="center", va="top")
    if north_arrow:
        c = to_fig(x[len(x) // 2], y[len(y) // 2], zb)
        n = to_fig(x[len(x) // 2], y[len(y) // 2] + 0.2 * ys, zb)
        d = (n - c) / max(np.linalg.norm(n - c), 1e-9) * 0.06
        base = np.array([0.88, 0.80])
        fig.add_artist(matplotlib.patches.FancyArrow(base[0], base[1], d[0], d[1], width=0.004, head_width=0.018,
                                                     head_length=0.018, length_includes_head=True, color="black",
                                                     transform=fig.transFigure))
        fig.text(base[0] + d[0] * 1.35, base[1] + d[1] * 1.35, "N", fontsize=8, weight="bold", ha="center", va="center")
    if caption:
        caption = caption.replace("{ve}", f"{ve:.2f}")
        fig.text(0.01, 0.015, caption, fontsize=7, ha="left", va="bottom", wrap=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format=fmt, dpi=dpi, facecolor="white")
    plt.close(fig)
    return {"output": str(output), "format": fmt, "dpi": int(dpi), "width_mm": float(width_mm), "height_mm": float(height_mm),
            "azimuth": float(azimuth), "elevation": float(elevation), "vertical_exaggeration": ve,
            "drape": drape_name, "grid_step": int(step),
            "note": f"3D figure ({fmt.upper()}, {dpi} dpi, {width_mm:g} mm wide), vertical exaggeration {ve:.2f}x, "
                    f"camera {azimuth:g} deg / {elevation:g} deg, {drape_name} draped."}
