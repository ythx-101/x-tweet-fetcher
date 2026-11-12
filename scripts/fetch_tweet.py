#!/usr/bin/env python3
"""Compatibility shim — v1 entry point, forwards to the xtf package.

Prefer: pip install . (or pip install git+https://github.com/ythx-101/x-tweet-fetcher) && xtf --url <URL>
"""
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from xtf.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
