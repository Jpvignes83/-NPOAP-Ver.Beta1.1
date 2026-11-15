"""Tests for critical photometric calculation functions."""
import numpy as np
import pytest
from astropy.time import Time

# Import after ensuring path; in real suite add project root to sys.path
try:
    from core.photometry_utils import airmass, compute_zero_point, estimate_fwhm_marginal
except ImportError:
    pytest.skip("photometry_utils not yet in path", allow_module_level=True)


def test_airmass_zenith():
    # At zenith (approx) airmass should be ~1
    # Use a time when the target is high (simplified check)
    t = Time("2025-01-01T00:00:00")
    am = airmass(0.0, -30.52, t, lat=-30.52, lon=0.0, elev=0)
    assert 0.9 < am < 1.2


def test_airmass_below_horizon():
    t = Time("2025-01-01T12:00:00")
    am = airmass(0.0, 60.0, t, lat=-30.0, lon=0.0, elev=0)  # likely low/below
    assert am >= 1.0


def test_compute_zero_point_basic():
    import pandas as pd
    df = pd.DataFrame({
        "phot_g_mean_mag": [10.0, 10.1, 10.2],
        "instrumental_mag": [15.0, 15.1, 15.3],
    })
    zp, std = compute_zero_point(df, airmass_val=1.2, k=0.1)
    assert zp is not None
    assert std is not None


def test_estimate_fwhm_synthetic():
    # Synthetic Gaussian source
    y, x = np.mgrid[0:31, 0:31]
    data = 100 * np.exp(-((x - 15)**2 + (y - 15)**2) / (2 * 2.5**2))
    data += 10  # background
    fwhm, _, _ = estimate_fwhm_marginal(data, 15, 15, box_size=25)
    assert fwhm is not None
    assert 3.0 < fwhm < 10.0
