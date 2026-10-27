"""
Shared normalization for header keyword / column matching.

Rules applied to both DB keywords and file header cells before compare:
strip, casefold (lowercase), remove whitespace, remove symbols.
Only letters and digits remain.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from common.header_match import normalize_header_match

__all__ = ["normalize_header_match"]
