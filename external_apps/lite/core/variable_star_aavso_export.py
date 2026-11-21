# core/variable_star_aavso_export.py
"""
Conversion des résultats photométriques et export au format AAVSO Extended File Format.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.io import fits
from astropy.time import Time
import astropy.units as u

import config

logger = logging.getLogger(__name__)


def _observer_location() -> EarthLocation:
    obs = getattr(config, "OBSERVATORY", {})
    return EarthLocation(
        lat=float(obs.get("lat", 0.0)) * u.deg,
        lon=float(obs.get("lon", 0.0)) * u.deg,
        height=float(obs.get("elev", 0.0)) * u.m,
    )


def jd_utc_to_bjd_tdb(jd_utc: float, target: SkyCoord) -> float:
    """Convertit un JD (UTC, milieu d'exposition) en BJD-TDB."""
    t = Time(jd_utc, format="jd", scale="utc")
    ltt = t.light_travel_time(target, location=_observer_location())
    return float((t.tdb + ltt).jd)


def relative_flux_to_magnitude(rel_flux: np.ndarray, ref_mag: float) -> np.ndarray:
    """Magnitude différentielle calibrée par rapport à ref_mag (médiane = ref_mag)."""
    rf = np.asarray(rel_flux, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        dm = -2.5 * np.log10(np.maximum(rf, 1e-12))
    return ref_mag + dm


def relative_flux_err_to_mag_err(rel_flux: np.ndarray, rel_flux_err: np.ndarray) -> np.ndarray:
    rf = np.asarray(rel_flux, dtype=float)
    rfe = np.asarray(rel_flux_err, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.abs((2.5 / np.log(10.0)) * (rfe / np.maximum(rf, 1e-12)))


def compute_phases(
    time: np.ndarray,
    period_days: float,
    epoch: float,
) -> np.ndarray:
    """
    Phase normalisée dans [0, 1) : ((t - T0) / P) mod 1.
    """
    p = float(period_days)
    if p <= 0 or not np.isfinite(p):
        raise ValueError("La période doit être un nombre strictement positif (jours).")
    t0 = float(epoch)
    t = np.asarray(time, dtype=float)
    return np.mod((t - t0) / p, 1.0)


def bin_lightcurve_points(
    time: np.ndarray,
    mag: np.ndarray,
    mag_err: Optional[np.ndarray] = None,
    *,
    n_bin: int = 1,
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """
    Regroupe des points consécutifs (tri temporel) par blocs de ``n_bin``.

    Temps : moyenne ; magnitude : moyenne pondérée par 1/σ² si erreurs disponibles.
    """
    n_bin = int(n_bin)
    if n_bin <= 1:
        t = np.asarray(time, dtype=float)
        m = np.asarray(mag, dtype=float)
        e = None if mag_err is None else np.asarray(mag_err, dtype=float)
        return t, m, e

    order = np.argsort(time)
    t = np.asarray(time, dtype=float)[order]
    m = np.asarray(mag, dtype=float)[order]
    e = None if mag_err is None else np.asarray(mag_err, dtype=float)[order]

    n = len(t)
    if n == 0:
        return t, m, e

    t_out: list[float] = []
    m_out: list[float] = []
    e_out: list[float] = []

    for start in range(0, n, n_bin):
        end = min(start + n_bin, n)
        t_blk = t[start:end]
        m_blk = m[start:end]
        t_out.append(float(np.mean(t_blk)))

        if e is not None:
            e_blk = e[start:end]
            valid = np.isfinite(m_blk) & np.isfinite(e_blk) & (e_blk > 0)
            if np.any(valid):
                w = 1.0 / (e_blk[valid] ** 2)
                m_out.append(float(np.sum(w * m_blk[valid]) / np.sum(w)))
                e_out.append(float(1.0 / np.sqrt(np.sum(w))))
            else:
                m_out.append(float(np.nanmean(m_blk)))
                e_out.append(float(np.nan))
        else:
            m_out.append(float(np.nanmean(m_blk)))
            e_out.append(
                float(np.nanstd(m_blk) / np.sqrt(len(m_blk))) if len(m_blk) > 1 else np.nan
            )

    err_arr = np.asarray(e_out, dtype=float) if e is not None or n_bin > 1 else None
    return np.asarray(t_out), np.asarray(m_out), err_arr


def enrich_results_with_bjd(
    df: pd.DataFrame,
    fits_folder: Path,
    target: SkyCoord,
    *,
    fits_files: Optional[list[Path]] = None,
) -> pd.DataFrame:
    """
    Ajoute les colonnes BJD-TDB et MAG / MERR à partir du CSV results et des en-têtes FITS.
    """
    out = df.copy()
    folder = Path(fits_folder)
    if fits_files is None:
        fits_files = sorted(
            list(folder.glob("*.fits"))
            + list(folder.glob("*.fit"))
            + list(folder.glob("*.fts"))
        )
    bjd_list = []
    for i, row in out.iterrows():
        slice_idx = int(row.get("slice", i + 1)) - 1
        bjd = np.nan
        if 0 <= slice_idx < len(fits_files):
            fpath = fits_files[slice_idx]
            try:
                with fits.open(fpath) as hdul:
                    hdr = hdul[0].header
                if "BJD-TDB" in hdr:
                    bjd = float(hdr["BJD-TDB"])
                elif "JD-UTC" in hdr:
                    bjd = jd_utc_to_bjd_tdb(float(hdr["JD-UTC"]), target)
                elif "DATE-OBS" in hdr:
                    exptime = float(hdr.get("EXPTIME", 0) or 0)
                    t0 = Time(hdr["DATE-OBS"], format="isot", scale="utc")
                    jd_mid = (t0 + (exptime / 2.0) * u.s).jd
                    bjd = jd_utc_to_bjd_tdb(jd_mid, target)
            except Exception as e:
                logger.debug("BJD pour %s : %s", fpath.name, e)
        if not np.isfinite(bjd) and "JD-UTC" in row and np.isfinite(row["JD-UTC"]):
            try:
                bjd = jd_utc_to_bjd_tdb(float(row["JD-UTC"]), target)
            except Exception:
                pass
        bjd_list.append(bjd)
    out["BJD-TDB"] = bjd_list
    return out


def build_lightcurve_table(
    results_csv: Path,
    fits_folder: Path,
    target: SkyCoord,
    ref_mag: float,
    *,
    fits_files: Optional[list[Path]] = None,
) -> pd.DataFrame:
    """Construit un tableau temps (BJD-TDB), magnitude, erreur."""
    df = pd.read_csv(results_csv)
    df = enrich_results_with_bjd(df, fits_folder, target, fits_files=fits_files)
    flux_col = "rel_flux_T1_fn" if "rel_flux_T1_fn" in df.columns else "rel_flux_T1"
    err_col = "rel_flux_err_T1" if "rel_flux_err_T1" in df.columns else None
    if flux_col not in df.columns:
        raise ValueError(f"Colonne {flux_col} absente du fichier résultats.")
    df["MAG"] = relative_flux_to_magnitude(df[flux_col].values, ref_mag)
    if err_col and err_col in df.columns:
        df["MERR"] = relative_flux_err_to_mag_err(df[flux_col].values, df[err_col].values)
    else:
        df["MERR"] = np.nan
    return df


def export_aavso_extended_format(
    lc_df: pd.DataFrame,
    output_path: Path,
    *,
    star_name: str,
    obscode: Optional[str] = None,
    filt: str = "V",
    delim: str = ",",
    notes: str = "",
) -> Path:
    """
    Écrit un fichier au format AAVSO Extended (CCD, photométrie standardisée).

    Colonnes de données : DATE, MAG, MERR, FILT, TRANS, MTYPE, NAME
    Les temps sont BJD-TDB (noté dans #NOTES).
    """
    equip = getattr(config, "EQUIPMENT_OBSERVATION", {})
    if obscode is None:
        obscode = str(equip.get("obs_code", "XXXX")).strip() or "XXXX"
    if delim == "tab":
        delim_char = "\t"
        delim_tag = "tab"
    else:
        delim_char = delim if delim else ","
        delim_tag = delim_char if delim_char in (",", ";", "|") else ","

    output_path = Path(output_path)
    time_col = "BJD-TDB" if "BJD-TDB" in lc_df.columns else "JD-UTC"
    if time_col not in lc_df.columns:
        raise ValueError("Aucune colonne temporelle (BJD-TDB ou JD-UTC) dans les données.")

    header_lines = [
        f"#NAME={star_name}",
        f"#OBSCODE={obscode}",
        "#SOFTWARE=NPOAP",
        f"#DELIM={delim_tag}",
        "#DATE=HJD",
        "#NOTES=Times are BJD-TDB mid-exposure. " + (notes or "").strip(),
        f"#FILTER={filt}",
        "#FIELDS=DATE,MAG,MERR,FILT,TRANS,MTYPE,NAME",
    ]

    lines = ["\n".join(header_lines)]
    for _, row in lc_df.iterrows():
        t = row[time_col]
        mag = row.get("MAG", np.nan)
        merr = row.get("MERR", np.nan)
        if not (np.isfinite(t) and np.isfinite(mag)):
            continue
        merr_s = f"{merr:.4f}" if np.isfinite(merr) else "na"
        lines.append(
            delim_char.join(
                [
                    f"{float(t):.8f}",
                    f"{float(mag):.4f}",
                    merr_s,
                    filt,
                    "STD",
                    "STD",
                    star_name,
                ]
            )
        )

    text = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    logger.info("Export AAVSO : %s (%d points)", output_path, len(lines) - 1)
    return output_path
