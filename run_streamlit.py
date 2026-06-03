"""Convenience launcher for the Streamlit dashboard.

Usage:
    python run_streamlit.py

This mirrors running `streamlit run streamlit_app.py` but avoids typing the
full command and ensures the correct interpreter is used.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).parent.resolve()
    app_path = repo_root / "streamlit_app.py"
    if not app_path.exists():
        raise SystemExit(f"Cannot find app at {app_path}")

    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    raise_code = subprocess.call(cmd)
    if raise_code != 0:
        raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
