"""Data import and migration package for StreamCapEvo.

Provides utilities for:
- Forward migration from Evo 1.x to current data directory
- Optional import from original StreamCap
- Safe file copying with lock handling
"""

from .migration import DetectionResult, detect_evo_data, forward_migrate
from .import_engine import ImportResult, ImportEngine

__all__ = [
    "DetectionResult", "detect_evo_data", "forward_migrate",
    "ImportResult", "ImportEngine"
]
