"""兼容旧入口：转调通用场景脚本。"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).with_name("run_scenario.py")
    runpy.run_path(str(target), run_name="__main__")
