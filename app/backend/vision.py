"""Adaptador de visión de la app Salcobrand → motor propio NeuraVision (sin servicios externos).

Mantiene la interfaz que usa main.py: MAX_IMAGES y analyze_shelf(images, planogram_context).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # carpeta salcobrand/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_IMAGES = 6


def analyze_shelf(images, planogram_context=None):
    from neuravision.engine import analyze_shelf as run_engine
    return run_engine(images, planogram_context)
