"""Enhanced Lightkurve / Astropy timeseries helpers for NPOAP.

Deepens integration for detrending, binning, periodograms, and
TESS / Kepler / K2 light-curve import.
"""
from __future__ import annotations

import logging
from typing import Optional, Union, Tuple, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import lightkurve as lk
    from astropy.timeseries import LombScargle, BoxLeastSquares
    from astropy import units as u
    LIGHTKURVE_AVAILABLE = True
except ImportError:
    LIGHTKURVE_AVAILABLE = False
    lk = None
    LombScargle = None
    BoxLeastSquares = None


def to_lightcurve(
    time,
    flux,
    flux_err=None,
    time_format: str = "jd",
    targetid: Optional[str] = None,
    mission: Optional[str] = None,
) -> "lk.LightCurve":
    """Convert arrays or a DataFrame to a lightkurve.LightCurve."""
    if not LIGHTKURVE_AVAILABLE:
        raise ImportError("lightkurve is required")
    if isinstance(time, pd.DataFrame):
        df = time
        time = df["time"].values
        flux = df["flux"].values
        flux_err = df.get("flux_err", None)
        if flux_err is not None:
            flux_err = flux_err.values
    lc = lk.LightCurve(
        time=time,
        flux=flux,
        flux_err=flux_err,
        time_format=time_format,
        targetid=targetid,
        mission=mission,
    )
    return lc


def load_tess_kepler(
    target: str,
    mission: str = "TESS",
    cadence: str = "short",
    quarter: Optional[int] = None,
    sector: Optional[int] = None,
    download_dir: Optional[str] = None,
) -> "lk.LightCurve":
    """Download and stitch a TESS, Kepler or K2 light curve via Lightkurve."""
    if not LIGHTKURVE_AVAILABLE:
        raise ImportError("lightkurve is required")

    search = lk.search_lightcurve(
        target, mission=mission, cadence=cadence, quarter=quarter, sector=sector
    )
    if len(search) == 0:
        raise ValueError(f"No {mission} light curves found for {target}")

    lc_collection = search.download_all(download_dir=download_dir)
    lc = lc_collection.stitch()
    logger.info(f"Loaded {len(lc)} points for {target} ({mission})")
    return lc


def detrend(
    lc: "lk.LightCurve",
    method: str = "biweight",
    window_length: float = 0.5,
    break_tolerance: float = 0.5,
) -> Tuple["lk.LightCurve", Optional[np.ndarray]]:
    """Detrend using Wotan (preferred) or Lightkurve flatten."""
    try:
        import wotan
        flat, trend = wotan.flatten(
            lc.time.value,
            lc.flux.value,
            method=method,
            window_length=window_length,
            break_tolerance=break_tolerance,
            return_trend=True,
        )
        return lc.copy(flux=flat), trend
    except Exception as e:
        logger.debug(f"Wotan unavailable or failed ({e}); falling back to lightkurve")
        return lc.flatten(window_length=window_length), None


def periodogram_lombscargle(
    lc: "lk.LightCurve",
    min_period: float = 0.1,
    max_period: float = 100.0,
    nterms: int = 1,
    samples_per_peak: int = 10,
) -> Tuple[np.ndarray, np.ndarray]:
    """Lomb-Scargle periodogram via astropy.timeseries."""
    if not LIGHTKURVE_AVAILABLE:
        raise ImportError("lightkurve / astropy.timeseries required")
    ls = LombScargle(lc.time, lc.flux, lc.flux_err, nterms=nterms)
    freq, power = ls.autopower(
        minimum_frequency=1.0 / max_period,
        maximum_frequency=1.0 / min_period,
        samples_per_peak=samples_per_peak,
    )
    return freq, power


def periodogram_bls(
    lc: "lk.LightCurve",
    min_period: float = 0.5,
    max_period: float = 50.0,
    frequency_factor: int = 5,
) -> Tuple[np.ndarray, np.ndarray]:
    """Box Least Squares periodogram."""
    if not LIGHTKURVE_AVAILABLE:
        raise ImportError("astropy.timeseries required")
    bls = BoxLeastSquares(lc.time, lc.flux, lc.flux_err)
    periods = np.linspace(min_period, max_period, 10000)
    results = bls.power(periods, frequency_factor=frequency_factor)
    return results.period, results.power


def bin_lightcurve(
    lc: "lk.LightCurve",
    bin_size: float = 0.01,
    method: str = "median",
) -> "lk.LightCurve":
    """Bin a LightCurve (time in days)."""
    if not LIGHTKURVE_AVAILABLE:
        raise ImportError("lightkurve required")
    return lc.bin(time_bin_size=bin_size, aggregate_func=method)


def remove_outliers(
    lc: "lk.LightCurve",
    sigma: float = 5.0,
    sigma_upper: Optional[float] = None,
    sigma_lower: Optional[float] = None,
) -> "lk.LightCurve":
    """Remove outliers using Lightkurve's built-in method."""
    return lc.remove_outliers(
        sigma=sigma, sigma_upper=sigma_upper, sigma_lower=sigma_lower
    )
