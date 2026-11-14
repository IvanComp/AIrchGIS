import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
requirements = root / "requirements.txt"
lines = requirements.read_text().splitlines()
library = next(line.strip() for line in lines if line.strip().startswith("rvt-py"))
subprocess.run([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", "--ignore-requires-python", library], check=True)
with tempfile.TemporaryDirectory() as directory:
    remaining = Path(directory) / "requirements.txt"
    remaining.write_text("\n".join(line for line in lines if line.strip() != library) + "\n")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(remaining)], check=True)
