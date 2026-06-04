from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from competitor_collector import build_parser, run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
