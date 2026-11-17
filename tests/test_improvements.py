"""Optimized unit tests for NPOAP photometric and light-curve utilities.

Improvements:
- Shared fixtures to avoid repeated setup
- Deterministic data (no random noise in periodogram)
- Smaller arrays for speed
- Clearer assertions
- Optional dependency handling
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

# Graceful import
try:
    from core.lightcurve_analysis import to_lightcurve, periodogram_lombscargle, bin_lightcurve
    from core.photometry_utils import airmass, compute_zero_point, estimate_fwhm_marginal
    from core.diagnostics import compute_diagnostics
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False


pytestmark = pytest.mark.skipif(not MODULES_AVAILABLE, reason="core modules not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def synthetic_lc():
    """Small deterministic light curve with a clear 1.5-day period."""
    times = np.linspace(0, 10, 80)
    flux = 1.0 + 0.3 * np.sin(2 * np.pi * times / 1.5)
    return times, flux


@pytest.fixture(scope="module")
def synthetic_image():
    """Small synthetic image with a Gaussian source."""
    y, x = np.mgrid[0:31, 0:31]
    data = 200 * np.exp(-((x - 15) ** 2 + (y - 15) ** 2) / (2 * 2.2 ** 2))
    data += 50.0  # background
    return data


@pytest.fixture
def matched_table():
    return pd.DataFrame({
        "phot_g_mean_mag": [10.0, 10.1, 10.2, 10.15],
        "instrumental_mag": [15.0, 15.1, 15.2, 15.12],
    })


# ---------------------------------------------------------------------------
# Photometry tests
# ---------------------------------------------------------------------------
def test_airmass_zenith():
    """Une cible placée exactement au zénith (calculée via AltAz) doit avoir un airmass ~1."""
    t = Time("2025-01-01T00:00:00")
    loc = EarthLocation(lat=-30.52 * u.deg, lon=0.0 * u.deg, height=0 * u.m)
    zenith = SkyCoord(alt=90 * u.deg, az=0 * u.deg, frame=AltAz(obstime=t, location=loc)).icrs
    am = airmass(zenith.ra.deg, zenith.dec.deg, t, lat=-30.52, lon=0.0, elev=0)
    assert 0.99 < am < 1.05


def test_airmass_below_horizon():
    t = Time("2025-01-01T12:00:00")
    am = airmass(0.0, 70.0, t, lat=-30.0, lon=0.0, elev=0)
    assert am >= 5.0  # high airmass or 99


def test_compute_zero_point(matched_table):
    zp, zp_std = compute_zero_point(matched_table, airmass_val=1.2, k=0.1)
    assert zp is not None
    assert zp_std is not None
    # ZP = médiane(G - mag_instrumentale) + k * airmass = -5.0 + 0.1 * 1.2 (données de test : G < mag instr.)
    assert zp == pytest.approx(-4.88, abs=0.02)


def test_estimate_fwhm_synthetic(synthetic_image):
    fwhm, _, _ = estimate_fwhm_marginal(synthetic_image, 15, 15, box_size=25)
    assert fwhm is not None
    assert 3.0 < fwhm < 9.0


# ---------------------------------------------------------------------------
# Light-curve tests
# ---------------------------------------------------------------------------
def test_to_lightcurve(synthetic_lc):
    times, flux = synthetic_lc
    lc = to_lightcurve(times, flux)
    assert len(lc) == len(times)


def test_periodogram_detects_period(synthetic_lc):
    times, flux = synthetic_lc
    lc = to_lightcurve(times, flux)
    freq, power = periodogram_lombscargle(lc, min_period=0.5, max_period=5.0)
    assert len(freq) > 0
    # Peak should be near 1/1.5 ≈ 0.666 cycles/day
    peak_freq = freq[np.argmax(power)]
    assert 0.5 < peak_freq < 0.9


def test_bin_lightcurve(synthetic_lc):
    times, flux = synthetic_lc
    lc = to_lightcurve(times, flux)
    binned = bin_lightcurve(lc, bin_size=0.5)
    assert len(binned) < len(lc)
    assert len(binned) > 0


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------
def test_diagnostics_basic(synthetic_image):
    diags = compute_diagnostics(synthetic_image)
    assert "background_median" in diags
    assert diags["background_median"] is not None
    assert diags["n_sources"] >= 0
