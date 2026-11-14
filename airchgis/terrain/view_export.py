import base64
import io
import json
from pathlib import Path

from PIL import Image


MAX_CAPTURE_PIXELS = 32_000_000


MODE_NAMES = {"mesh": "Original", "points": "Cloud 1", "mesh_wire": "Cloud 2", "relief_mesh": "Cloud 3"}


def view_caption(view):
    view = view or {}
    parts = ["3D view"]
    mode = MODE_NAMES.get(view.get("render_mode"))
    if mode:
        parts.append(f"{mode} mode")
    if view.get("crs"):
        parts.append(f"CRS {view['crs']}")
    if view.get("cell_size_m"):
        parts.append(f"3D grid cell {float(view['cell_size_m']):.2f} m")
    if view.get("relief_scale_m"):
        parts.append(f"local relief scale {float(view['relief_scale_m']):g} m (heights not true)")
    if view.get("vertical_exaggeration"):
        parts.append(f"vertical exaggeration x{float(view['vertical_exaggeration']):.2f}")
    return ", ".join(parts) + "."


def save_current_view(encoded, output, view=None):
    output = Path(output)
    if output.suffix.lower() not in {".png", ".pdf"}:
        raise ValueError("Choose PDF or PNG for a 3D view image.")
    raw = base64.b64decode(encoded, validate=True)
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The viewer did not provide a PNG image.")
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
        if width * height > MAX_CAPTURE_PIXELS or width < 1 or height < 1:
            raise ValueError("The captured image exceeds the supported size.")
        image.load()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() == ".png":
            output.write_bytes(raw)
        else:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_pdf import FigureCanvasPdf

            dpi = width / (297 / 25.4)
            figure = Figure(figsize=(297 / 25.4, height / dpi), dpi=dpi, frameon=False)
            FigureCanvasPdf(figure)
            axis = figure.add_axes([0, 0, 1, 1])
            axis.imshow(image, interpolation="none", aspect="auto")
            axis.set_axis_off()
            figure.savefig(output, format="pdf", dpi=dpi, pad_inches=0, transparent=True,
                           metadata={"Title": "AIrchGIS — current 3D view", "Subject": view_caption(view),
                                     "Creator": "AIrchGIS"})
            figure.clear()
    metadata = {"image_pixels": [width, height], "caption": view_caption(view), "view": view or {}, "image_encoding": "lossless PNG",
                "camera": "Captured from the interactive viewer; no camera reconstruction or automatic reframing."}
    output.with_suffix(".view.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
    return output
