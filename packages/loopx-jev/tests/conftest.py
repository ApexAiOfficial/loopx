from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(ROOT),
    str(ROOT / "packages/loopx-jev/src"),
    str(Path(__file__).resolve().parent),
]
