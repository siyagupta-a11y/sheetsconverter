import sys
import os

# Add backend/ to path so imports work in the serverless environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from main import app  # noqa: F401 — Vercel needs 'app' importable from this module
