"""Prepare sample data without overwriting an existing course world."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if not (root / "data/cartwheel.db").exists():
    subprocess.run([sys.executable, "-m", "uv", "run", "python", "-m", "seed.generate"], cwd=root, check=True)
