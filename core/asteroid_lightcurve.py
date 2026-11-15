"""Asteroid light-curve helpers leveraging Sora + periodogram tools.

Provides thin wrappers that can be extended with Sora shape models.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    from .lightcurve_analysis import periodogram_lombscargle, to_lightcurve
    LIGHTCURVE_AVAILABLE = True
except ImportError:
    LIGHTCURVE_AVAILABLE = False


def asteroid_periodogram(
    times,
    fluxes,
    flux_errs=None,
    min_period: float = 0.1,
    max_period: float = 50.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Lomb-Scargle periodogram specialized for asteroid rotation periods.

    times should be in days (BJD-TDB preferred).
    """
    if not LIGHTCURVE_AVAILABLE:
        raise ImportError("lightcurve_analysis / lightkurve required")
    lc = to_lightcurve(times, fluxes, flux_errs)
    return periodogram_lombscargle(lc, min_period=min_period, max_period=max_period)


def note_sora_integration():
    """Placeholder documenting how to hook Sora shape models.

    Sora is already in the project dependencies. Typical next steps:
    - Use sora.Body or sora.Occultation for shape / chord modelling.
    - Feed the resulting projected area or magnitude model into a
      light-curve fit together with the periodogram peak.
    """
    logger.info("Sora is available for asteroid shape / occultation modelling.")
    return True
