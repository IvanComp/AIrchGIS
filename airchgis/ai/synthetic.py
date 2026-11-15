"""Synthetic terrains with known buried features, for the controlled test of the Unusual relief layer.

Two natural backgrounds:
- "easy": a regional slope with smooth hills at 20-120 m scales and fine noise;
- "hard": fractal (power-law) relief with agricultural terraces and a modern field boundary (a straight bank), which
  are real relief forms but not the features sought, so they count against the method.

Features sought (truth mask): a curved ditch 4 m wide and 0.35 m deep, a mound 9 m in radius and 0.5 m high and a
straight road 6 m wide raised 0.15 m.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def _fractal(n, res, rng, beta=3.5, amplitude=2.0, cutoff_m=20.0):
    """Power-law relief, rolled off below cutoff_m so that the finest scales are left to the micro-roughness."""
    fy = np.fft.fftfreq(n, d=res)[:, None]
    fx = np.fft.rfftfreq(n, d=res)[None, :]
    f = np.hypot(fx, fy)
    f[0, 0] = np.inf
    spec = (rng.normal(size=f.shape) + 1j * rng.normal(size=f.shape)) * f ** (-beta / 2.0)
    spec *= np.exp(-(f * cutoff_m) ** 2)
    spec[0, 0] = 0
    z = np.fft.irfft2(spec, s=(n, n))
    return amplitude * z / z.std()


def terrain(kind="easy", n=500, res=1.0, features=True, seed=0):
    """Return (dem, truth, nuisance): the DTM, the mask of the features sought and the mask of other relief forms
    (terraces, field boundary) that are real but not sought."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n] * res
    z = 200 + 0.04 * xx + 0.015 * yy
    nuisance = np.zeros((n, n), dtype=bool)
    if kind == "easy":
        for s, a in ((120, 6.0), (50, 2.0), (20, 0.5)):
            f = ndimage.gaussian_filter(rng.normal(size=(n, n)), s / res)
            z += a * f / f.std()
    elif kind == "hard":
        z += _fractal(n, res, rng)
        # terraces on the upper third: steps of 0.8 m every ~25 m, with soft risers
        weight = 1 / (1 + np.exp(-(yy - 0.66 * n * res) / 8.0))
        steps = 0.8 * np.floor(xx / 25.0) + 0.8 / (1 + np.exp(-((xx % 25.0) - 22.5) / 0.8))
        z += weight * (steps - 0.032 * xx)
        riser = (weight > 0.5) & (np.abs((xx % 25.0) - 22.5) < 2.5)
        nuisance |= riser
        # modern field boundary: straight bank 2 m wide, 0.3 m high, east-west
        db = np.abs(yy - 0.45 * n * res)
        z += 0.3 * np.exp(-(db / 1.0) ** 2)
        nuisance |= db < 2.5
    else:
        raise ValueError("kind must be 'easy' or 'hard'")
    z += ndimage.gaussian_filter(rng.normal(size=(n, n)), 1.5) * 0.06 + rng.normal(0, 0.03, (n, n))
    truth = np.zeros((n, n), dtype=bool)
    if features:
        cx = 0.3 * n * res + 40 * np.sin(yy / 90.0)
        d = np.abs(xx - cx)
        z -= 0.35 * np.exp(-(d / 2.0) ** 2)
        truth |= d < 3
        r = np.hypot(xx - 0.7 * n * res, yy - 0.26 * n * res)
        z += 0.5 * np.clip(1 - (r / 9.0) ** 2, 0, None)
        truth |= r < 9
        dd = np.abs(xx - yy * 0.6 - 0.24 * n * res) / np.hypot(1, 0.6)
        z += 0.15 / (1 + np.exp((dd - 3) / 0.6))
        truth |= dd < 3.5
    return z.astype(np.float32), truth, nuisance


def ringwork_site(n=600, res=1.0, seed=0, rings=True):
    """A hill with a concentric ringwork (three ditches 4 m wide, 0.4 m deep, at radii 35, 55 and 75 m, slightly
    elliptic and with gaps) under smooth natural relief and noise, plus things that must not become priorities:
    a lake (a level water surface with LiDAR noise), a clipped edge with missing data and an artefact step along it,
    and a modern road (straight, 6 m wide, graded, with sharp edges).
    Returns (dem, masks) with masks 'ring', 'lake', 'edge', 'road'."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n] * res
    z = 300 + 0.02 * xx
    for s, a in ((120, 4.0), (50, 1.5), (20, 0.4)):
        f = ndimage.gaussian_filter(rng.normal(size=(n, n)), s / res)
        z += a * f / f.std()
    cy, cx = 0.45 * n * res, 0.45 * n * res
    r = np.hypot((xx - cx) / 1.0, (yy - cy) / 0.88)
    z += 12.0 * np.exp(-(r / 110.0) ** 2)
    ang = np.arctan2(yy - cy, xx - cx)
    ring = np.zeros((n, n), dtype=bool)
    if rings:
        for radius, gap in ((35.0, 0.6), (55.0, 2.4), (75.0, -1.9)):
            d = np.abs(r - radius)
            keep = np.abs(np.angle(np.exp(1j * (ang - gap)))) > 0.35  # a gap (entrance) in each ditch
            z -= 0.4 * np.exp(-(d / 2.0) ** 2) * keep
            ring |= (d < 3) & keep
    z += ndimage.gaussian_filter(rng.normal(size=(n, n)), 1.5) * 0.06 + rng.normal(0, 0.03, (n, n))
    # modern road: straight, raised 0.3 m with a flat top and sharp edges, crossing the south-east
    dd = np.abs((xx - 0.85 * n * res) + 0.35 * (yy - 0.5 * n * res)) / np.hypot(1, 0.35)
    road = dd < 3
    z = np.where(dd < 3, z + 0.3, z + 0.3 / (1 + np.exp((dd - 3) / 0.3)))
    # lake in the north-east corner: a level surface at a fixed elevation with LiDAR noise
    lake = np.hypot(xx - 0.9 * n * res, yy - 0.1 * n * res) < 0.18 * n * res
    level = float(np.percentile(z[lake], 5))
    z = np.where(lake, level + rng.normal(0, 0.05, (n, n)), z)
    # clipped edge in the south-west: missing data beyond a diagonal, with a 0.8 m artefact step along it
    cut = (yy - 0.75 * n * res) - xx
    edge = (cut > -6) & (cut <= 0)
    z = np.where(edge, z + 0.8, z)
    z = np.where(cut > 0, np.nan, z)
    return z.astype(np.float32), {"ring": ring, "lake": lake, "edge": edge | (cut > 0), "road": road}


def stepped_hill_site(n=600, res=1.0, seed=0, terraces=True):
    """An irregular hill (two lobes, about 25 m high) with three stepped bands that follow its contours (sunken steps
    0.4 m deep at 6, 10 and 14 m below the top, each with a gap), under smooth natural relief and noise. Negatives
    on the same terrain: a long straight slope with natural geological steps at constant elevation, and agricultural
    terraces (parallel straight risers). Returns (dem, masks) with masks 'bands', 'geology', 'agri'."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n] * res
    z = 250 + 0.01 * xx
    for s, a in ((120, 3.0), (50, 1.0), (20, 0.3)):
        f = ndimage.gaussian_filter(rng.normal(size=(n, n)), s / res)
        z += a * f / f.std()
    cy, cx = 0.4 * n * res, 0.4 * n * res
    hill = (25.0 * np.exp(-(((xx - cx) / 90.0) ** 2 + ((yy - cy) / 65.0) ** 2))
            + 10.0 * np.exp(-(((xx - cx - 60) / 45.0) ** 2 + ((yy - cy + 35) / 40.0) ** 2)))
    top = float(hill.max())
    gy, gx = np.gradient(hill, res)
    slope = np.maximum(np.hypot(gx, gy), 1e-3)
    ang = np.arctan2(yy - cy, xx - cx)
    bands = np.zeros((n, n), dtype=bool)
    if terraces:
        for drop, gap in ((6.0, 0.8), (10.0, 2.6), (14.0, -1.7)):
            d = (hill - (top - drop)) / slope  # horizontal distance to the contour
            keep = np.abs(np.angle(np.exp(1j * (ang - gap)))) > 0.5
            near = (np.abs(d) < 10)
            z -= 0.4 * np.exp(-(d / 2.0) ** 2) * keep * near
            bands |= (np.abs(d) < 3) & keep
    z += hill
    # natural geological steps on a long straight slope (east strip): steps at constant elevation, straight lines
    geo = xx > 0.8 * n * res
    plane = 0.12 * (xx - 0.8 * n * res)
    steps = 0.5 * np.floor(plane / 2.0) + 0.5 / (1 + np.exp(-((plane % 2.0) - 1.5) / 0.05))
    z = np.where(geo, z + plane + steps - 0.25 * plane, z)
    geology = geo & (np.abs((plane % 2.0) - 1.5) < 0.4)
    # agricultural terraces in the south: parallel straight risers every 20 m
    agri_zone = yy > 0.8 * n * res
    z = np.where(agri_zone, z + 0.6 / (1 + np.exp(-((xx % 20.0) - 17.0) / 0.6)), z)
    agri = agri_zone & (np.abs((xx % 20.0) - 17.0) < 2.5)
    z += ndimage.gaussian_filter(rng.normal(size=(n, n)), 1.5) * 0.06 + rng.normal(0, 0.03, (n, n))
    return z.astype(np.float32), {"bands": bands, "geology": geology, "agri": agri}


def feature_points(truth, step=15):
    """Points sampled on the truth mask, used as 'known features' in tests (rows, cols)."""
    rr, cc = np.nonzero(truth)
    keep = ((rr // step) * 1000 + (cc // step))
    _, first = np.unique(keep, return_index=True)
    return list(zip(rr[first].astype(float), cc[first].astype(float)))
