"""Ensure the vendored wfarsenal (repo vendor/) wins over any installed or
sibling copies when tests run under plain `python -m pytest` without an
explicit PYTHONPATH.
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
