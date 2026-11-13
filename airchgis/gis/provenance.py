

from __future__ import annotations

import hashlib
import json
import platform
import shlex
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def file_sha256(path, chunk=1 << 20) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def environment() -> dict:
    env = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("numpy", "rasterio", "rvt", "laspy", "pyproj"):
        try:
            module = __import__(name)
            env[name] = getattr(module, "__version__", "unknown")
        except Exception:
            env[name] = None
    try:
        from airchgis.gis.backend import qgis_version

        env["qgis"] = qgis_version()
    except Exception:
        env["qgis"] = None
    return env


@dataclass
class Step:
    tool: str
    params: dict
    backend: str
    status: str
    inputs: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    command: list | None = None
    message: str = ""
    started: str = ""
    duration_s: float = 0.0


class ProvenanceLog:
    def __init__(self, title: str = "AIrchGIS session"):
        self.title = title
        self.created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.environment = environment()
        self.steps: list[Step] = []

    def record(self, step: Step) -> Step:
        self.steps.append(step)
        return step

    @staticmethod
    def describe_inputs(paths) -> list:
        return [{"path": str(p), "sha256": file_sha256(p)} for p in paths if p]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "created": self.created,
            "environment": self.environment,
            "steps": [asdict(s) for s in self.steps],
        }

    def save_json(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

    def to_python(self) -> str:
        lines = [
            "from airchgis.gis.provenance import ProvenanceLog, file_sha256",
            "from airchgis.gis.tools import run_tool",
            "",
            f"log = ProvenanceLog({self.title!r} + ' (replay)')",
            "",
        ]
        for i, step in enumerate(self.steps, 1):
            if step.status not in {"ok", "warn"}:
                continue
            for item in step.inputs:
                if item.get("sha256"):
                    lines.append(
                        f"assert file_sha256({item['path']!r}) in (None, {item['sha256']!r}), "
                        f"'input changed since the original run: {item['path']}'"
                    )
            backend = "qgis" if step.backend == "qgis" else "native"
            lines.append(f"run_tool({step.tool!r}, log=log, prefer={backend!r}, **{step.params!r})")
            lines.append("")
        lines.append("log.save_json('replay_provenance.json')")
        return "\n".join(lines) + "\n"

    def to_shell(self) -> str:
        lines = ["#!/bin/sh", "set -e", ""]
        for i, step in enumerate(self.steps, 1):
            if step.command:
                lines.append(shlex.join(step.command))
                lines.append("")
        return "\n".join(lines) + "\n"

    def save_scripts(self, folder, stem="airchgis_session") -> dict:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        py = folder / f"{stem}_replay.py"
        sh = folder / f"{stem}_qgis.sh"
        js = folder / f"{stem}_provenance.json"
        py.write_text(self.to_python(), encoding="utf-8")
        sh.write_text(self.to_shell(), encoding="utf-8")
        self.save_json(js)
        return {"python": py, "shell": sh, "json": js}
