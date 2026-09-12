"""Evaluation helper (submission entry). Re-exports the validator."""
import os
import sys

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from validate import main, validate  # noqa: F401
