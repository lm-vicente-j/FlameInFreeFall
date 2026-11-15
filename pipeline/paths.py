"""Default filesystem locations shared by every pipeline stage.

Only command-line entry points read these defaults. Library functions receive
paths as arguments so tests can run against temporary directories.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "res"
"""Ignored by git: saved PSI metadata, raw downloads, and intermediate outputs."""
DATA = ROOT / "data"
"""Committed: curated inputs and reviewed outputs handed to the application."""
SCHEMAS = Path(__file__).resolve().parent / "schemas"
EXPERIMENTAL_TABLES = RES / "experimental-tables"
SAMPLES = RES / "samples"
EXTRACTED = RES / "extracted"
