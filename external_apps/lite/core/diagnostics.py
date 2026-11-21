"""Centralized image-quality and observing diagnostics.

Collects FWHM, airmass, seeing estimates, and other metrics that were
previously scattered across GUI and pipeline code.
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

import numpy as np
from astropy.time import Time
from astropy.coordinates import SkyCoord

from .photometry_utils import airmass, estimate_fwhm_epsf, detect_sources_dao

logger = logging.getLogger(__name__)


def compute_diagnostics(
    data: np.ndarray,
    header: Optional[dict] = None,
    target_coord: Optional[SkyCoord] = None,
    obstime: Optional[Time] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    elev: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a dictionary of standard quality diagnostics for an image."""
    diagnostics: Dict[str, Any] = {
        "fwhm_px": None,
        "fwhm_arcsec": None,
        "airmass": None,
        "n_sources": 0,
        "background_median": float(np.median(data)) if data.size else None,
        "background_std": float(np.std(data)) if data.size else None,
    }

    try:
        sources = detect_sources_dao(data)
        diagnostics["n_sources"] = len(sources)
        fwhm = estimate_fwhm_epsf(data, stars_tbl=sources)
        if fwhm is not None:
            diagnostics["fwhm_px"] = fwhm
            if header is not None:
                plate_scale = header.get("PIXSCALE") or header.get("CDELT1")
                if plate_scale is not None:
                    try:
                        diagnostics["fwhm_arcsec"] = abs(float(plate_scale)) * fwhm * 3600.0
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"Diagnostics FWHM failed: {e}")

    if target_coord is not None and obstime is not None:
        try:
            diagnostics["airmass"] = airmass(
                target_coord.ra.deg,
                target_coord.dec.deg,
                obstime,
                lat=lat,
                lon=lon,
                elev=elev,
            )
        except Exception as e:
            logger.debug(f"Diagnostics airmass failed: {e}")

    return diagnostics


def summarize_diagnostics(diagnostics_list: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a list of per-image diagnostics into summary statistics."""
    if not diagnostics_list:
        return {}
    fwhm_vals = [d["fwhm_px"] for d in diagnostics_list if d.get("fwhm_px") is not None]
    am_vals = [d["airmass"] for d in diagnostics_list if d.get("airmass") is not None]
    return {
        "n_images": len(diagnostics_list),
        "median_fwhm_px": float(np.median(fwhm_vals)) if fwhm_vals else None,
        "median_airmass": float(np.median(am_vals)) if am_vals else None,
        "total_sources": int(sum(d.get("n_sources", 0) for d in diagnostics_list)),
    }
