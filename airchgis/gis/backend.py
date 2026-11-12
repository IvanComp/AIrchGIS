"""Find and drive QGIS Processing through the ``qgis_process`` command line.

QGIS is optional. When it is missing, tools fall back to their native
rvt-py/rasterio implementation and say so in their result.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

ENV_VAR = "AIRCHGIS_QGIS_PROCESS"

_CANDIDATES = (
    "/Applications/QGIS*.app/Contents/MacOS/bin/qgis_process",
    "/Applications/QGIS*.app/Contents/MacOS/qgis_process",
    "/usr/bin/qgis_process",
    "/usr/local/bin/qgis_process",
    "C:/Program Files/QGIS*/bin/qgis_process-qgis.bat",
)


class QgisError(RuntimeError):
    pass


def find_qgis_process() -> Path | None:
    """Return the ``qgis_process`` executable, or None if QGIS is not installed."""
    override = os.environ.get(ENV_VAR)
    if override:
        path = Path(override)
        return path if path.exists() else None
    found = shutil.which("qgis_process") or shutil.which("qgis_process-qgis")
    if found:
        return Path(found)
    for pattern in _CANDIDATES:
        hits = sorted(glob.glob(pattern))
        if hits:
            return Path(hits[-1])
    return None


def qgis_available() -> bool:
    return find_qgis_process() is not None


def _env():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def _run(args, timeout):
    exe = find_qgis_process()
    if exe is None:
        raise QgisError("QGIS is not installed: qgis_process was not found.")
    proc = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=timeout, env=_env())
    if proc.returncode != 0:
        raise QgisError((proc.stderr or proc.stdout).strip()[-2000:] or f"qgis_process exited with {proc.returncode}")
    return proc.stdout


def _json_out(text):
    start = text.find("{")
    if start < 0:
        raise QgisError("qgis_process returned no JSON.")
    return json.loads(text[start:])


@lru_cache(maxsize=1)
def qgis_version() -> str | None:
    if not qgis_available():
        return None
    try:
        return _run(["--version"], timeout=60).strip().splitlines()[0]
    except Exception:
        return None


def list_algorithms(timeout=120) -> dict:
    """Map of algorithm id -> name for every installed Processing provider."""
    data = _json_out(_run(["list", "--json"], timeout))
    out = {}
    for provider in (data.get("providers") or {}).values():
        for alg_id, alg in (provider.get("algorithms") or {}).items():
            out[alg_id] = alg.get("name", alg_id)
    return out


def algorithm_help(alg_id: str, timeout=60) -> dict:
    return _json_out(_run(["help", alg_id, "--json"], timeout))


def _format_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_format_value(v) for v in value)
    return str(value)


def build_command(alg_id: str, params: dict, exe: str | os.PathLike | None = None) -> list[str]:
    """The exact ``qgis_process run`` command line, also used for replay scripts."""
    exe = str(exe or find_qgis_process() or "qgis_process")
    args = [exe, "run", alg_id, "--json", "--"]
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)) and key.upper() == "STATISTICS":
            args.extend(f"{key}={_format_value(v)}" for v in value)
        else:
            args.append(f"{key}={_format_value(value)}")
    return args


def run_algorithm(alg_id: str, params: dict, timeout=3600) -> dict:
    """Run one Processing algorithm and return its ``results`` dictionary."""
    command = build_command(alg_id, params)
    data = _json_out(_run(command[1:], timeout))
    return data.get("results", data)
