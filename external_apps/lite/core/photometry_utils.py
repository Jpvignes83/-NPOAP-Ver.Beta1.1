"""Pure photometric utility functions for NPOAP.

Includes:
- Airmass and zero-point calculation
- Gaia matching with on-disk cache
- Photutils DAOStarFinder source detection
- Empirical PSF (ePSF) FWHM estimation
- Legacy 2D Gaussian FWHM (kept for compatibility)
- Centroid refinement
"""
from __future__ import annotations

import logging
import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
import astropy.units as u
from astropy.stats import sigma_clip
from astroquery.gaia import Gaia
from photutils.centroids import centroid_quadratic
from photutils.detection import DAOStarFinder
from photutils.psf import EPSFBuilder, extract_stars
from scipy.optimize import curve_fit
import warnings

logger = logging.getLogger(__name__)

# On-disk cache for Gaia cone searches
_GAIA_CACHE_DIR = Path.home() / ".npoap" / "gaia_cache"
_GAIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(coord: SkyCoord, radius_arcsec: float) -> str:
    key = f"{coord.ra.deg:.6f}_{coord.dec.deg:.6f}_{radius_arcsec:.2f}"
    return hashlib.md5(key.encode()).hexdigest()


def airmass(ra, dec, obstime, lat=None, lon=None, elev=None):
    """Calcule l'airmass. lat/lon/elev en degrés/m si fournis, sinon valeurs par défaut."""
    try:
        if lat is None:
            lat = -30.52
        if lon is None:
            lon = -70.82
        if elev is None:
            elev = 1710.0

        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)

        if not isinstance(obstime, Time):
            obstime = Time(obstime)

        frame = AltAz(obstime=obstime, location=location)
        coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
        altaz = coord.transform_to(frame)
        alt_deg = altaz.alt.deg

        if alt_deg <= 0:
            return 99.0

        zenith_angle_rad = np.radians(90.0 - alt_deg)
        am = 1.0 / np.cos(zenith_angle_rad)
        return float(am)
    except Exception as e:
        logger.warning(f"Erreur calcul airmass: {e}")
        return 1.0


def compute_zero_point(matched_table, airmass_val, k=0.1):
    """Calcule le zero-point corrigé de l'extinction."""
    try:
        zp_vals = matched_table["phot_g_mean_mag"] - matched_table["instrumental_mag"]
        zp_clipped = sigma_clip(zp_vals, sigma=3, cenfunc="median")
        zp_median = np.median(zp_clipped)
        zp_corrected = zp_median + float(k) * airmass_val
        zp_std = np.std(zp_clipped)
        return zp_corrected, zp_std
    except Exception as e:
        logger.warning(f"Erreur zero-point: {e}")
        return None, None


def match_sources_with_gaia(
    phot_df,
    search_radius_arcsec: float = 2.0,
    gaia_mag_column: str = "phot_g_mean_mag",
    use_cache: bool = True,
):
    """Associe les sources détectées aux entrées Gaia DR3 les plus proches.

    Uses a simple on-disk cache to avoid repeated slow cone searches.
    """
    if not {"ra", "dec"}.issubset(phot_df.columns):
        return phot_df
    coords = SkyCoord(ra=phot_df["ra"].values * u.deg, dec=phot_df["dec"].values * u.deg)
    results = []
    for star in coords:
        cache_file = _GAIA_CACHE_DIR / f"{_cache_key(star, search_radius_arcsec)}.json"
        cached = None
        if use_cache and cache_file.exists():
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
            except Exception:
                cached = None

        if cached is not None:
            results.append(cached)
            continue

        try:
            r = Gaia.cone_search_async(star, radius=search_radius_arcsec * u.arcsec)
            res = r.get_results()
            if len(res) > 0:
                best = res[0]
                entry = {
                    "ra_gaia": float(best["ra"]),
                    "dec_gaia": float(best["dec"]),
                    gaia_mag_column: float(best[gaia_mag_column]) if gaia_mag_column in best.colnames else np.nan,
                    "source_id": int(best["source_id"]),
                }
            else:
                entry = {
                    "ra_gaia": np.nan,
                    "dec_gaia": np.nan,
                    gaia_mag_column: np.nan,
                    "source_id": None,
                }
            if use_cache:
                try:
                    with open(cache_file, "w") as f:
                        json.dump(entry, f)
                except Exception:
                    pass
            results.append(entry)
        except Exception as e:
            logger.debug(f"Gaia match failed: {e}")
            results.append({
                "ra_gaia": np.nan,
                "dec_gaia": np.nan,
                gaia_mag_column: np.nan,
                "source_id": None,
            })
    return pd.concat([phot_df.reset_index(drop=True), pd.DataFrame(results)], axis=1)


def detect_sources_dao(
    data: np.ndarray,
    fwhm: float = 3.0,
    threshold: Optional[float] = None,
    sharplo: float = 0.2,
    sharphi: float = 1.0,
) -> pd.DataFrame:
    """Detect sources with photutils.DAOStarFinder.

    Returns a DataFrame with xcentroid, ycentroid, flux, etc.
    """
    if threshold is None:
        median = np.median(data)
        std = np.std(data)
        threshold = median + 5 * std

    daofind = DAOStarFinder(fwhm=fwhm, threshold=threshold, sharplo=sharplo, sharphi=sharphi)
    sources = daofind(data)
    if sources is None or len(sources) == 0:
        return pd.DataFrame()
    return sources.to_pandas()


def estimate_fwhm_epsf(
    data: np.ndarray,
    stars_tbl: Optional[pd.DataFrame] = None,
    size: int = 25,
) -> Optional[float]:
    """Estimate a representative FWHM using an empirical PSF (ePSF) built from bright stars.

    Falls back to None if construction fails.
    """
    try:
        if stars_tbl is None or len(stars_tbl) < 5:
            sources = detect_sources_dao(data, fwhm=3.0)
            if len(sources) < 5:
                return None
            stars_tbl = sources.nlargest(15, "flux") if "flux" in sources.columns else sources.head(15)

        from astropy.nddata import NDData
        from astropy.table import Table

        nddata = NDData(data=data)
        stars = extract_stars(
            nddata,
            Table.from_pandas(stars_tbl[["xcentroid", "ycentroid"]]),
            size=size,
        )
        epsf_builder = EPSFBuilder(oversampling=2, maxiters=5)
        epsf, _ = epsf_builder(stars)
        core = epsf.data
        if core is None or core.size == 0:
            return None
        y, x = np.indices(core.shape)
        total = core.sum()
        if total <= 0:
            return None
        x_mean = (x * core).sum() / total
        y_mean = (y * core).sum() / total
        var_x = ((x - x_mean) ** 2 * core).sum() / total
        var_y = ((y - y_mean) ** 2 * core).sum() / total
        sigma = np.sqrt((var_x + var_y) / 2.0)
        fwhm = 2.355 * sigma
        return float(fwhm) if 1.0 < fwhm < 30.0 else None
    except Exception as e:
        logger.debug(f"ePSF FWHM estimation failed: {e}")
        return None


def two_d_gaussian(x_array, y_array, model_norm, model_floor, model_x_mean, model_y_mean,
                   model_x_sigma, model_y_sigma, model_theta):
    """Gaussienne 2D rotée (kept for backward compatibility)."""
    xt = x_array - model_x_mean
    yt = y_array - model_y_mean
    coss = np.cos(model_theta)
    sinn = np.sin(model_theta)
    return model_floor + model_norm * np.exp(
        -0.5 * (
            ((-xt * sinn + yt * coss) / model_y_sigma) ** 2
            + ((xt * coss + yt * sinn) / model_x_sigma) ** 2
        )
    )


def estimate_fwhm_marginal(data, x, y, box_size=25):
    """Estime le FWHM via un fit gaussien 2D. Retourne (fwhm, row_info, col_info) ou Nones."""
    try:
        x, y = int(x), int(y)
        half = box_size // 2
        if (y - half < 0 or y + half + 1 > data.shape[0]
                or x - half < 0 or x + half + 1 > data.shape[1]):
            return None, None, None

        sub = data[y - half:y + half + 1, x - half:x + half + 1]
        if sub.size == 0 or not np.isfinite(sub).any():
            return None, None, None

        x_indices = np.arange(sub.shape[1], dtype=float)
        y_indices = np.arange(sub.shape[0], dtype=float)
        x_grid, y_grid = np.meshgrid(x_indices, y_indices, indexing="xy")

        sub_flat = sub.flatten()
        bg_estimate = np.percentile(sub_flat, 10)
        peak_value = np.max(sub_flat) - bg_estimate
        y_peak, x_peak = np.unravel_index(np.argmax(sub_flat), sub.shape)

        def gaussian_wrapper(coords, norm, floor, x_mean, y_mean, x_sigma, y_sigma, theta):
            xa, ya = coords
            return two_d_gaussian(xa, ya, norm, floor, x_mean, y_mean, x_sigma, y_sigma, theta).flatten()

        p0 = [peak_value, bg_estimate, float(x_peak), float(y_peak), 3.0, 3.0, 0.0]
        bounds = (
            [0, -np.inf, 0, 0, 0.5, 0.5, -np.pi / 4],
            [np.inf, np.inf, sub.shape[1], sub.shape[0], 15.0, 15.0, np.pi / 4],
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            popt, _ = curve_fit(
                gaussian_wrapper,
                (x_grid, y_grid),
                sub.flatten(),
                p0=p0,
                bounds=bounds,
                maxfev=5000,
            )

        _, _, _, _, sx, sy, _ = popt
        if not (0.5 <= sx <= 15.0 and 0.5 <= sy <= 15.0):
            return None, None, None

        sigma_eff = (sx + sy) / 2.0
        fwhm_val = 2.355 * sigma_eff
        if not (1.0 <= fwhm_val <= 30.0):
            return None, None, None

        row_sum = np.sum(sub, axis=1)
        col_sum = np.sum(sub, axis=0)
        r = np.arange(len(row_sum))
        c = np.arange(len(col_sum))
        p_opt_row = [np.max(row_sum), float(np.argmax(row_sum)), sy, np.median(row_sum)]
        p_opt_col = [np.max(col_sum), float(np.argmax(col_sum)), sx, np.median(col_sum)]
        return fwhm_val, (r, row_sum, p_opt_row), (c, col_sum, p_opt_col)

    except Exception as e:
        logger.warning(f"estimate_fwhm_marginal failed: {e}")
        return None, None, None


def refine_centroid(data, x0, y0, box_size=25):
    """Affine le centroïde avec photutils.centroid_quadratic."""
    xi, yi = int(x0), int(y0)
    half = box_size // 2
    if yi - half < 0 or xi - half < 0:
        return x0, y0
    cut = data[yi - half:yi + half + 1, xi - half:xi + half + 1]
    if cut.size == 0 or not np.isfinite(cut).all():
        return x0, y0
    try:
        dx, dy = centroid_quadratic(cut)
        if not np.isfinite(dx):
            return x0, y0
        return xi - half + dx, yi - half + dy
    except Exception:
        return x0, y0
