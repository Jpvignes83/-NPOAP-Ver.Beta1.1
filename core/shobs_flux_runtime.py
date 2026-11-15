"""Charge le runtime vendu ``external_apps/shobs_flux`` sur ``sys.path``."""
from __future__ import annotations

import sys
from pathlib import Path

_INSERTED = False


def shobs_flux_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "external_apps" / "shobs_flux"


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
