#!/usr/bin/env python3
"""AI Company 픽셀 오피스 루트 실행 엔트리포인트."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
START_SCRIPT = ROOT / "pixel_office" / "scripts" / "start.py"

if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.run([sys.executable, str(START_SCRIPT)] + sys.argv[1:]).returncode)
