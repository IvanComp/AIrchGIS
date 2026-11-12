from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RVT_DIR = PROJECT_ROOT / "RVT"
CROP_TOOL_DIR = PROJECT_ROOT / "Crop marks Tool"

RVT_ENTRYPOINT = RVT_DIR / "core.py"
CROP_STANDALONE_ENTRYPOINT = CROP_TOOL_DIR / "s2_cropmarks_gui.py"

RVT_README = RVT_DIR / "README_RVT_Lidar_Explorer.md"
CROP_README = CROP_TOOL_DIR / "README.md"
ROOT_README = PROJECT_ROOT / "README.md"
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.svg"

ROOT_EE_PROJECT_FILE = PROJECT_ROOT / ".ee_project"
CROP_EE_PROJECT_FILE = CROP_TOOL_DIR / ".ee_project"


def latest_files(base: Path, pattern: str, limit: int = 12):
    if not base.exists():
        return []
    files = [p for p in base.rglob(pattern) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    return files[:limit]


def count_files(base: Path, suffixes=None):
    if not base.exists():
        return 0
    if suffixes is None:
        return sum(1 for p in base.rglob("*") if p.is_file())
    suffixes = {s.lower() for s in suffixes}
    return sum(1 for p in base.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)
