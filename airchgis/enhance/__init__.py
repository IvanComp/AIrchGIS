"""Cleaning, enhancement and automatic selection of visualizations.

The package turns the user's own files into clearer pictures, step by step,
and measures every step:

- :mod:`.metrics`: label-free quality measures (noise, stripes, spikes,
  voids, visibility of features at the target scale);
- :mod:`.clean`: DTM/DSM destriping, spike and pit removal, void filling and
  edge-preserving denoising, each with a before/after report;
- :mod:`.points`: statistical outlier removal for LAS/LAZ point clouds;
- :mod:`.multispectral`: cloud, shadow and haze masks, band artefacts and a
  quality score for each date;
- :mod:`.contrast`: adaptive local contrast, multi-scale detail and
  pan-sharpening (when a panchromatic band exists);
- :mod:`.bestview`: computes a grid of relief visualizations and ranks them
  by how well they show features of the size sought;
- :mod:`.fuse`: a blend of the best layers with weights optimized for the
  same score.

Nothing here invents detail: there is no super-resolution, and every output
says which steps were applied and what they changed.
"""

