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


def feature_points(truth, step=15):
    """Points sampled on the truth mask, used as 'known features' in tests (rows, cols)."""
    rr, cc = np.nonzero(truth)
    keep = ((rr // step) * 1000 + (cc // step))
    _, first = np.unique(keep, return_index=True)
    return list(zip(rr[first].astype(float), cc[first].astype(float)))
