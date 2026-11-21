"""Charge le runtime vendu SHOBS-FLUX sur ``sys.path``.

Ordre de résolution (distribution AUTONOME Lite) :

1. ``external_apps/lite/accessories/shobs_flux``
2. ``external_apps/shobs_flux`` (compat anciennes copies)
"""
from __future__ import annotations

import sys
from pathlib import Path

_INSERTED = False


def shobs_flux_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "external_apps" / "lite" / "accessories" / "shobs_flux",
        root / "external_apps" / "shobs_flux",
    ]
    for d in candidates:
        if d.is_dir():
            return d
    return candidates[0]


def ensure_shobs_on_path() -> Path:
    """Insère le dossier SHOBS-FLUX en tête de ``sys.path`` (idempotent)."""
    global _INSERTED
    d = shobs_flux_dir()
    if not d.is_dir():
        raise FileNotFoundError(f"SHOBS-FLUX introuvable : {d}")
    s = str(d)
    if s not in sys.path:
        sys.path.insert(0, s)
    _INSERTED = True
    return d


def import_shobs(name: str):
    """Importe un module du runtime SHOBS (ex. ``bench``, ``darks``, ``image_check``)."""
    ensure_shobs_on_path()
    return __import__(name)