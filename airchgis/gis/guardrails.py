

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


SENSORS = {
    "sentinel-2": {"gsd_m": 10.0, "psf_sigma_px": 0.45, "noise": 0.0396, "contrast": 0.15, "kind": "multispectral"},
    "landsat": {"gsd_m": 30.0, "psf_sigma_px": 0.45, "noise": 0.0396, "contrast": 0.15, "kind": "multispectral"},
    "planetscope": {"gsd_m": 3.0, "psf_sigma_px": 0.5, "noise": 0.05, "contrast": 0.15, "kind": "multispectral"},
    "lidar": {"gsd_m": 1.0, "psf_sigma_px": 0.5, "noise": 0.05, "contrast": 0.3, "kind": "elevation"},
}

SNR_OK = 3.0
SNR_REFUSE = 1.5


@dataclass
class Resolvability:
    verdict: str
    feature_width_m: float
    gsd_m: float
    pixels_across: float
    modulation: float
    snr_single_date: float
    snr_stacked: float
    n_dates: int
    min_resolvable_width_m: float
    message: str

    def to_dict(self):
        return asdict(self)


def _peak_fraction(width_m, gsd_m, sigma_m, samples=4001):

    half_w = width_m / 2.0
    if sigma_m <= 0:
        return min(1.0, width_m / gsd_m) if width_m < gsd_m else 1.0
    total = 0.0
    for i in range(samples):
        u = -gsd_m / 2.0 + gsd_m * (i + 0.5) / samples
        a = (half_w - u) / (sigma_m * math.sqrt(2))
        b = (-half_w - u) / (sigma_m * math.sqrt(2))
        total += 0.5 * (math.erf(a) - math.erf(b))
    return total / samples


def check_resolvability(
    feature_width_m: float,
    sensor: str = "sentinel-2",
    gsd_m: float | None = None,
    contrast: float | None = None,
    noise: float | None = None,
    n_dates: int = 1,
) -> Resolvability:

    if feature_width_m <= 0:
        raise ValueError("feature_width_m must be positive")
    spec = SENSORS.get(sensor.lower(), SENSORS["sentinel-2"])
    gsd = float(gsd_m or spec["gsd_m"])
    sigma = spec["psf_sigma_px"] * gsd
    delta = float(contrast if contrast is not None else spec["contrast"])
    sd = float(noise if noise is not None else spec["noise"])
    n = max(1, int(n_dates))

    modulation = delta * _peak_fraction(feature_width_m, gsd, sigma)
    snr1 = modulation / sd
    snr_n = snr1 * math.sqrt(n)
    pixels = feature_width_m / gsd


    min_width = None
    w = gsd / 10.0
    while w <= 50 * gsd:
        if delta * _peak_fraction(w, gsd, sigma, samples=801) / sd * math.sqrt(n) >= SNR_OK and w >= 2 * gsd:
            min_width = w
            break
        w += gsd / 10.0
    min_width = round(min_width if min_width is not None else 2 * gsd, 1)

    if snr_n < SNR_REFUSE or (pixels < 1.0 and snr_n < SNR_OK):
        verdict = "refuse"
        message = (
            f"A {feature_width_m:g} m feature cannot be resolved at {gsd:g} m: expected SNR {snr_n:.1f} "
            f"over {n} date(s). Use LiDAR or very-high-resolution imagery; at this resolution aim for "
            f"features of at least {min_width:g} m."
        )
    elif snr_n < SNR_OK or pixels < 2.0:
        verdict = "warn"
        message = (
            f"A {feature_width_m:g} m feature spans {pixels:.1f} pixel(s) at {gsd:g} m (SNR {snr_n:.1f}): "
            f"results are unreliable; treat any anomaly as a weak hint."
        )
    else:
        verdict = "ok"
        message = f"A {feature_width_m:g} m feature is resolvable at {gsd:g} m (SNR {snr_n:.1f})."
    return Resolvability(verdict, float(feature_width_m), gsd, round(pixels, 2), round(modulation, 4),
                         round(snr1, 2), round(snr_n, 2), n, min_width, message)
