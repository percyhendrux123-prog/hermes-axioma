"""Moved to axioma/seal.py (self-contained, stdlib only). Kept only so an older import still works."""
from .seal import (CODE_LINE, LABEL, Fingerprint, canonical, clean_line, compare_lines,  # noqa: F401
                   load_key, parse_code, stamp, unstamp)
