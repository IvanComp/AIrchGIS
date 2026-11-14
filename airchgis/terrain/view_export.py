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
    mode = view.get("mode_label") or MODE_NAMES.get(view.get("render_mode"))
    if mode:
        parts.append(f"{mode} mode")
    if view.get("ai_view"):
        parts.append(f"{view['ai_view'].get('label', 'priority area')} of the AI priorities, lit from "
                     f"{float(view['ai_view'].get('light_azimuth', 315)):.0f}°")
    if view.get("ai_shown"):
        width = f" for features about {float(view['ai_width_m']):g} m wide" if view.get("ai_width_m") else ""
        parts.append(f"colour or outlines = Unusual relief (AI){width}, priorities to check, not sites")
    if view.get("crs"):
        parts.append(f"CRS {view['crs']}")
    if view.get("cell_size_m"):
        parts.append(f"3D grid cell {float(view['cell_size_m']):.2f} m")
    if view.get("relief_scale_m"):
        parts.append(f"local relief scale {float(view['relief_scale_m']):g} m (heights not true)")
    if view.get("vertical_exaggeration"):
        ve = f"vertical exaggeration x{float(view['vertical_exaggeration']):.2f}"
        if str(view.get("ve_source") or "").startswith("adaptive"):
            ve += " (adaptive)"
        parts.append(ve)
    if view.get("relief_opacity") is not None and float(view["relief_opacity"]) < 100:
        parts.append(f"relief opacity {float(view['relief_opacity']):g}% over satellite imagery")
        if view.get("imagery_attribution"):
            parts.append(str(view["imagery_attribution"]))
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
