# gui/target_selector.py
"""Sélection T1 et comparateurs Gaia (photométrie étoiles variables NPOAP)."""
from __future__ import annotations

import logging
import threading
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from astropy.io import fits
from astropy.visualization import ZScaleInterval
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.vizier import Vizier
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle
from matplotlib.backend_bases import MouseButton 
import pandas as pd
from astropy.wcs.utils import proj_plane_pixel_scales

# Import des outils d'analyse depuis le pipeline
from core.photometry_pipeline import (
    launch_photometry_aperture, 
    refine_centroid, 
    estimate_fwhm_marginal, 
    show_diagnostics_windows
)

# --- CONFIGURATION VIZIER ---
Vizier.VIZIER_SERVER = "vizier.cfa.harvard.edu" 
Vizier.ROW_LIMIT = 5000 # On demande beaucoup d'étoiles pour filtrer géométriquement après
# ----------------------------

# Stockage pour fermer les fenêtres de diagnostic précédentes
_current_diag_windows = []

def close_previous_diagnostics():
    """Ferme les fenêtres de diagnostic ouvertes précédemment."""
    global _current_diag_windows
    for win in _current_diag_windows:
        try:
            if win.winfo_exists():
                win.destroy()
        except:
            pass
    _current_diag_windows = []


def _pixel_to_sky(wcs: WCS, x: float, y: float) -> SkyCoord:
    """Ciel depuis pixel — même convention que vizier_fov_query (overlays VSX)."""
    return wcs.pixel_to_world(x, y)


def _sky_to_pixel(wcs: WCS, coord: SkyCoord) -> tuple[float, float]:
    px, py = wcs.world_to_pixel(coord)
    return float(px), float(py)


def _coerce_radec_deg(ra_col, dec_col) -> tuple[np.ndarray, np.ndarray]:
    """Extrait RA/Dec en degrés (float) depuis une table VizieR/Gaia."""
    ra = ra_col
    dec = dec_col
    if hasattr(ra, "to") and hasattr(dec, "to"):
        ra_d = np.asarray(ra.to(u.deg).value, dtype=float)
        dec_d = np.asarray(dec.to(u.deg).value, dtype=float)
    else:
        ra_d = np.asarray(ra, dtype=float)
        dec_d = np.asarray(dec, dtype=float)
    return ra_d, dec_d


def _gaia_table_skycoord(tab) -> SkyCoord:
    ra_d, dec_d = _coerce_radec_deg(tab["RA_ICRS"], tab["DE_ICRS"])
    return SkyCoord(ra=ra_d * u.deg, dec=dec_d * u.deg, frame="icrs")


def _table_to_pixel_arrays(wcs: WCS, tab) -> tuple[np.ndarray, np.ndarray]:
    """Projette une table VizieR/Gaia — même logique que les overlays VSX."""
    from core.vizier_fov_query import _guess_radec_columns, _row_radec_deg

    n = len(tab)
    xp = np.full(n, np.nan, dtype=float)
    yp = np.full(n, np.nan, dtype=float)
    rd = _guess_radec_columns(tab)
    if rd is None:
        return xp, yp
    ra_col, dec_col = rd
    for i in range(n):
        rdg = _row_radec_deg(tab, i, ra_col, dec_col)
        if rdg is None:
            continue
        ra, dec = rdg
        if not (np.isfinite(ra) and np.isfinite(dec)):
            continue
        try:
            coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
            px, py = wcs.world_to_pixel(coord)
            xp[i] = float(px)
            yp[i] = float(py)
        except Exception:
            continue
    return xp, yp


def _world_to_pixel_arrays(wcs: WCS, ra_deg, dec_deg):
    """Projette des RA/Dec (deg) en pixels (convention identique aux overlays VSX)."""
    ra, dec = _coerce_radec_deg(ra_deg, dec_deg)
    xp = np.full(ra.shape, np.nan, dtype=float)
    yp = np.full(ra.shape, np.nan, dtype=float)
    ok = np.isfinite(ra) & np.isfinite(dec)
    if not np.any(ok):
        return xp, yp
    try:
        coords = SkyCoord(ra=ra[ok] * u.deg, dec=dec[ok] * u.deg, frame="icrs")
        x_ok, y_ok = wcs.world_to_pixel(coords)
        xp[ok] = np.asarray(x_ok, dtype=float)
        yp[ok] = np.asarray(y_ok, dtype=float)
    except Exception as e:
        logging.debug("Projection WCS lot : %s — ligne à ligne", e)
        idxs = np.flatnonzero(ok)
        for k in idxs:
            try:
                c = SkyCoord(ra=ra[k] * u.deg, dec=dec[k] * u.deg, frame="icrs")
                xp[k], yp[k] = _sky_to_pixel(wcs, c)
            except Exception:
                pass
    return xp, yp


def _pixel_on_chip_mask(
    xp, yp, ny: int, nx: int, *, chip_margin_frac: float = 0.01
) -> np.ndarray:
    """Masque booléen : pixels dans le détecteur (même tolérance que vizier_fov_query)."""
    xp = np.asarray(xp, dtype=float)
    yp = np.asarray(yp, dtype=float)
    finite = np.isfinite(xp) & np.isfinite(yp)
    m = max(0.0, float(chip_margin_frac))
    on = (
        (xp >= -nx * m)
        & (xp <= nx * (1.0 + m))
        & (yp >= -ny * m)
        & (yp <= ny * (1.0 + m))
    )
    return finite & on


def _pixel_in_image(cx, cy, ny: int, nx: int, chip_margin_frac: float = 0.01) -> bool:
    return bool(
        _pixel_on_chip_mask(np.asarray([cx]), np.asarray([cy]), ny, nx, chip_margin_frac=chip_margin_frac)[0]
    )


def _angular_radius_pixels(
    wcs: WCS,
    x_pix: float,
    y_pix: float,
    radius_arcmin: float,
    *,
    axes_swapped: bool = False,
) -> float:
    """Convertit un rayon angulaire (arcmin) en rayon d'affichage (pixels) autour de (x_pix, y_pix)."""
    try:
        center = _pixel_to_sky(wcs, x_pix, y_pix)
        edge = center.directional_offset_by(0 * u.deg, float(radius_arcmin) * u.arcmin)
        xe, ye = _sky_to_pixel(wcs, edge)
        if axes_swapped:
            xe, ye = ye, xe
        r_px = float(np.hypot(xe - x_pix, ye - y_pix))
        if np.isfinite(r_px) and r_px > 1.0:
            return r_px
    except Exception:
        pass
    try:
        scales = proj_plane_pixel_scales(wcs)
        scale_deg = float(np.mean(scales))
        if scale_deg > 0:
            return float(radius_arcmin) / 60.0 / scale_deg
    except Exception:
        pass
    return max(30.0, float(radius_arcmin) * 2.0)


def _draw_comp_fov_circle(
    ax,
    wcs: WCS,
    x_pix: float,
    y_pix: float,
    radius_arcmin: float,
    *,
    axes_swapped: bool = False,
) -> Circle:
    """Trace le disque de recherche des comparateurs (cône projeté en cercle local)."""
    r_px = _angular_radius_pixels(
        wcs,
        x_pix,
        y_pix,
        radius_arcmin,
        axes_swapped=axes_swapped,
    )
    circ = Circle(
        (x_pix, y_pix),
        r_px,
        edgecolor="lime",
        ls="--",
        lw=1.8,
        fill=False,
        label="comp_fov",
        zorder=4,
    )
    ax.add_patch(circ)
    return circ


def _load_fits_image_2d(fits_path: Path):
    """Charge une image 2D et le WCS (même logique que VSX / vizier_fov_query)."""
    from core.vizier_fov_query import wcs_from_image_hdu

    with fits.open(fits_path) as hdul:
        data = np.asarray(hdul[0].data, dtype=float)
        header = hdul[0].header
    if data.ndim > 2:
        data = np.squeeze(data)
    if data.ndim != 2:
        raise ValueError(f"Image FITS non 2D après squeeze : shape={data.shape}")
    wcs = wcs_from_image_hdu(header)
    if wcs is None:
        wcs = WCS(header)
        try:
            wcs = wcs.celestial
        except Exception:
            wcs = WCS(header, naxis=2)
    return data, header, wcs


def _tk_widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


def _query_gaia_field_table(wcs: WCS, data_shape, row_limit: int = 5000):
    """Interroge Gaia DR3 sur tout le champ (boîte englobant le détecteur)."""
    from core.vizier_fov_query import fov_center_and_radius_deg

    ny, nx = int(data_shape[0]), int(data_shape[1])
    center, r_deg = fov_center_and_radius_deg(wcs, nx, ny, margin=1.02)
    width = height = 2.0 * r_deg
    v = Vizier(
        columns=["RA_ICRS", "DE_ICRS", "Gmag", "bp_rp", "phot_variable_flag"],
        row_limit=int(row_limit),
    )
    tab = None
    try:
        res = v.query_region(
            center,
            width=width * u.deg,
            height=height * u.deg,
            catalog="I/355/gaiadr3",
        )
        if res and len(res[0]) > 0:
            tab = res[0]
    except Exception as e:
        logging.warning("Gaia boîte champ : %s — repli cône", e)
    if tab is None:
        try:
            res = v.query_region(center, radius=r_deg * u.deg, catalog="I/355/gaiadr3")
            if res and len(res[0]) > 0:
                tab = res[0]
        except Exception as e:
            logging.error("Gaia champ complet : %s", e)
            return None
    if tab is not None and len(tab) > 0:
        xp, yp = _table_to_pixel_arrays(wcs, tab)
        on_chip = _pixel_on_chip_mask(xp, yp, ny, nx, chip_margin_frac=0.01)
        n_chip = int(np.sum(on_chip))
        logging.info(
            "Gaia champ complet : %d étoile(s), boîte ≈ %.3f°, %d projetée(s) sur le capteur",
            len(tab),
            width,
            n_chip,
        )
        if n_chip > 0:
            return tab[on_chip]
        on_sw = _pixel_on_chip_mask(yp, xp, ny, nx, chip_margin_frac=0.01)
        n_sw = int(np.sum(on_sw))
        if n_sw > 0:
            logging.warning(
                "Gaia champ : correction projection x/y (%d / %d sur capteur)",
                n_sw,
                len(tab),
            )
            return tab[on_sw]
        if np.any(np.isfinite(xp)):
            logging.warning(
                "Gaia champ : aucune source sur capteur — xp [%.0f, %.0f], yp [%.0f, %.0f] "
                "pour image %dx%d (échantillon VizieR ignoré)",
                float(np.nanmin(xp)),
                float(np.nanmax(xp)),
                float(np.nanmin(yp)),
                float(np.nanmax(yp)),
                nx,
                ny,
            )
        return None
    return None


def _query_gaia_cone_table(
    center: SkyCoord,
    radius,
    row_limit: int = 5000,
    *,
    gmag_range: tuple[float, float] | None = None,
):
    """Cône VizieR Gaia DR3 autour d'un point."""
    v = Vizier(
        columns=["RA_ICRS", "DE_ICRS", "Gmag", "bp_rp", "phot_variable_flag"],
        row_limit=int(row_limit),
    )
    if gmag_range is not None:
        lo, hi = gmag_range
        v.column_filters = {"Gmag": f"{lo:.1f}..{hi:.1f}"}
    res = v.query_region(center, radius=radius, catalog="I/355/gaiadr3")
    if res and len(res[0]) > 0:
        return res[0]
    return None


def _query_gaia_comparators_for_t1(
    wcs: WCS,
    data_shape,
    target_coord: SkyCoord,
    radius_arcmin: float,
    *,
    t1_mag: float | None = None,
    mag_delta: float = 2.5,
    row_limit: int = 5000,
):
    """Cône Gaia autour de T1 (45′ par défaut) — pool filtré ensuite sur le capteur."""
    radius = float(radius_arcmin) * u.arcmin
    gmag_range = None
    if t1_mag is not None and np.isfinite(t1_mag):
        gmag_range = (float(t1_mag) - mag_delta, float(t1_mag) + mag_delta)
    tab = _query_gaia_cone_table(
        target_coord, radius, row_limit, gmag_range=gmag_range
    )
    if tab is None and gmag_range is not None:
        logging.warning(
            "Gaia comparateurs : filtre Gmag %.1f..%.1f vide — repli sans filtre magnitude",
            gmag_range[0],
            gmag_range[1],
        )
        tab = _query_gaia_cone_table(target_coord, radius, row_limit)
    if tab is not None and len(tab) > 0:
        note = f", G {gmag_range[0]:.1f}..{gmag_range[1]:.1f}" if gmag_range else ""
        logging.info(
            "Gaia comparateurs : cône %.0f′ → %d source(s) VizieR%s",
            radius_arcmin,
            len(tab),
            note,
        )
        return tab
    logging.warning("Gaia comparateurs : cône %.0f′ vide autour de T1", radius_arcmin)
    return None


def _gaia_table_row_is_variable(tab, i: int) -> bool:
    if "phot_variable_flag" not in tab.colnames:
        return False
    var_flag = tab["phot_variable_flag"][i]
    try:
        if var_flag is None or (hasattr(var_flag, "mask") and np.ma.is_masked(var_flag)):
            return False
    except Exception:
        return False
    return str(var_flag).strip().upper() in ("VARIABLE", "TRUE", "1", "Y", "YES")


def _pick_comparators_spread(candidates, n: int, min_sep_arcsec: float = 35.0):
    """
    Choisit n comparateurs répartis sur le champ en privilégiant |G - G_T1| croissant.
    candidates : liste (SkyCoord, Gmag, bp_rp) triée par proximité de magnitude.
    """
    if len(candidates) <= n:
        return candidates
    pool = list(candidates[: min(len(candidates), max(n * 8, 40))])
    selected = [pool.pop(0)]
    while len(selected) < n and pool:
        best_j = None
        best_sep = -1.0
        for j, cand in enumerate(pool):
            min_sep = min(cand[0].separation(s[0]).arcsec for s in selected)
            if min_sep < min_sep_arcsec:
                continue
            if min_sep > best_sep:
                best_sep = min_sep
                best_j = j
        if best_j is None:
            selected.append(pool.pop(0))
        else:
            selected.append(pool.pop(best_j))
    return selected


def find_comparison_stars(
    gaia_table,
    wcs: WCS,
    data: np.ndarray,
    target_coord: SkyCoord,
    t1_mag: float,
    *,
    max_comps: int = 10,
    mag_delta: float = 2.5,
    min_sep_from_t1_arcsec: float = 10.0,
    max_sep_from_t1_arcsec=None,
    chip_margin_frac: float = 0.01,
    spread_on_field: bool = True,
    axes_swapped: dict | None = None,
):
    """
    Sélectionne jusqu'à max_comps comparateurs Gaia dans l'image.

    max_sep_from_t1_arcsec=None : pas de limite angulaire haute (tout le champ).
    """
    if gaia_table is None or len(gaia_table) == 0:
        return []

    ny, nx = int(data.shape[0]), int(data.shape[1])
    cand = []
    colnames = gaia_table.colnames
    if "Gmag" not in colnames or "RA_ICRS" not in colnames or "DE_ICRS" not in colnames:
        logging.error("Table Gaia : colonnes manquantes (%s)", colnames)
        return []

    xp, yp = _table_to_pixel_arrays(wcs, gaia_table)
    on_chip = _pixel_on_chip_mask(xp, yp, ny, nx, chip_margin_frac=chip_margin_frac)
    if len(gaia_table) > 0 and not np.any(on_chip):
        on_chip_sw = _pixel_on_chip_mask(yp, xp, ny, nx, chip_margin_frac=chip_margin_frac)
        if np.sum(on_chip_sw) > 0:
            logging.warning("Comparateurs : projection x/y inversée — correction automatique")
            xp, yp = yp, xp
            on_chip = on_chip_sw
            if axes_swapped is not None:
                axes_swapped["v"] = True
    n_on_chip = int(np.sum(on_chip))
    if n_on_chip == 0 and len(gaia_table) > 0:
        try:
            t1_x, t1_y = wcs.world_to_pixel(target_coord)
            fin = np.isfinite(xp) & np.isfinite(yp)
            logging.warning(
                "Comparateurs : 0 sur capteur — T1 @ (%.0f, %.0f), "
                "Gaia xp [%.0f, %.0f] yp [%.0f, %.0f] (%d/%d finies), image %dx%d",
                float(t1_x),
                float(t1_y),
                float(np.nanmin(xp)) if np.any(fin) else float("nan"),
                float(np.nanmax(xp)) if np.any(fin) else float("nan"),
                float(np.nanmin(yp)) if np.any(fin) else float("nan"),
                float(np.nanmax(yp)) if np.any(fin) else float("nan"),
                int(np.sum(fin)),
                len(gaia_table),
                nx,
                ny,
            )
        except Exception as e:
            logging.warning("Comparateurs : diagnostic projection impossible : %s", e)

    n_mag_ok = 0
    chip_idx = np.flatnonzero(on_chip)

    ra_d, dec_d = _coerce_radec_deg(gaia_table["RA_ICRS"], gaia_table["DE_ICRS"])

    for i in chip_idx:
        try:
            gmag_val = gaia_table["Gmag"][i]
            if np.ma.is_masked(gmag_val):
                continue
            m = float(gmag_val)
            if not np.isfinite(m):
                continue
            if abs(m - t1_mag) > mag_delta:
                continue
            n_mag_ok += 1
            if _gaia_table_row_is_variable(gaia_table, i):
                continue

            c_sky = SkyCoord(ra=float(ra_d[i]) * u.deg, dec=float(dec_d[i]) * u.deg, frame="icrs")

            sep = c_sky.separation(target_coord).arcsec
            if sep <= min_sep_from_t1_arcsec:
                continue
            if max_sep_from_t1_arcsec is not None and sep > max_sep_from_t1_arcsec:
                continue

            bprp = None
            if "bp_rp" in colnames and not np.ma.is_masked(gaia_table["bp_rp"][i]):
                bprp = float(gaia_table["bp_rp"][i])
            elif "BP-RP" in colnames and not np.ma.is_masked(gaia_table["BP-RP"][i]):
                bprp = float(gaia_table["BP-RP"][i])

            cand.append((c_sky, m, bprp))
        except Exception as e:
            logging.debug("Comparateur Gaia ligne %d ignorée : %s", i, e)
            continue

    cand.sort(
        key=lambda x: (
            abs(x[1] - t1_mag),
            x[0].separation(target_coord).arcsec,
        )
    )
    if spread_on_field and len(cand) > max_comps:
        cand = _pick_comparators_spread(cand, max_comps)
    else:
        cand = cand[:max_comps]
    cone_note = ""
    if max_sep_from_t1_arcsec is not None:
        cone_note = f", cône ≤{max_sep_from_t1_arcsec / 60.0:.0f}′"
    logging.info(
        "Comparateurs : %d retenus (mag ±%.1f, T1 G=%.2f%s) — %d mag OK sur %d sur capteur / %d Gaia",
        len(cand),
        mag_delta,
        float(t1_mag),
        cone_note,
        n_mag_ok,
        n_on_chip,
        len(gaia_table),
    )
    return cand


def launch_target_selection(
    fits_path,
    on_selection_done=launch_photometry_aperture,
    is_asteroid=False,
    ephemeris_data=None,
    header_target_coord=None,
    *,
    max_comps: int = 15,
    comps_full_fov: bool = False,
    comp_search_radius_arcmin: float = 45.0,
    comp_mag_delta: float = 2.5,
    wcs: WCS | None = None,
):
    """
    Lance la fenêtre de sélection de T1 et des étoiles de comparaison.
    
    Parameters
    ----------
    fits_path : str or Path
        Chemin vers l'image FITS de référence
    on_selection_done : callable, optional
        Fonction callback appelée après la sélection (default: launch_photometry_aperture)
    is_asteroid : bool, optional
        Si True, T1 est un astéroïde (ne pas chercher dans Gaia, utiliser magnitude éphémérides)
    ephemeris_data : Table, optional
        Table d'éphémérides avec colonnes 'datetime_jd' et 'V' pour les astéroïdes
    header_target_coord : SkyCoord, optional
        Coordonnées de la cible lues depuis l'entête FITS pour affichage.
    max_comps : int
        Nombre maximal de comparateurs proposés.
    comps_full_fov : bool
        Si True, cherche les comparateurs sur tout le champ (répartis sur le CCD).
    comp_search_radius_arcmin : float
        Rayon du cône Gaia autour de T1 (arcmin) ; les comparateurs sont retenus dans ce disque.
    comp_mag_delta : float
        Écart maximal |G_comp - G_T1| autorisé.
    wcs : WCS, optional
        WCS déjà résolu (ex. même instance que les overlays VSX). Si None, relu depuis le FITS.
    """
    fits_path = Path(fits_path)

    # 1. Chargement FITS (2D — les clics matplotlib doivent être en pixels, pas en °)
    try:
        data, header, wcs_loaded = _load_fits_image_2d(fits_path)
    except Exception as e:
        messagebox.showerror("Erreur FITS", f"Impossible d'ouvrir l'image :\n{e}")
        return
    if wcs is None:
        wcs = wcs_loaded
    ny, nx = int(data.shape[0]), int(data.shape[1])
    logging.info(
        "Sélection cibles : capteur %dx%d (WCS %s)",
        nx,
        ny,
        "externe (overlays VSX)" if wcs is not wcs_loaded else "depuis FITS",
    )

    # 2. ZScale
    try:
        interval = ZScaleInterval()
        vmin, vmax = interval.get_limits(data)
    except:
        vmin, vmax = np.percentile(data, [10, 90])

    # 3. Comparateurs : cône autour de T1 (défaut 45′)
    comp_search_radius = float(comp_search_radius_arcmin) * u.arcmin
    comp_max_sep_arcsec = None if comps_full_fov else comp_search_radius.to(u.arcsec).value

    # 4. Interface
    root = tk.Toplevel()
    if comps_full_fov:
        mode_hint = f"champ complet, {max_comps} comps"
    else:
        mode_hint = f"{max_comps} comps / {comp_search_radius_arcmin:.0f}′"
    root.title(f"Sélection Cibles - {fits_path.name} ({mode_hint})")
    root.geometry("1450x850") 

    # --- Zone Gauche (Liste) ---
    left_frame = tk.Frame(root, width=500, bg="#f0f0f0") 
    left_frame.pack(side=tk.LEFT, fill=tk.Y)
    left_frame.pack_propagate(False)

    tk.Label(left_frame, text=" Étoiles Sélectionnées (Coordonnées Gaia) ", bg="#ddd", font=("Arial", 10, "bold"), pady=5).pack(fill=tk.X)
    
    # En-têtes colonnes
    h_frame = tk.Frame(left_frame, bg="#ccc")
    h_frame.pack(fill="x", padx=2, pady=2)
    tk.Label(h_frame, text="", width=5, bg="#ccc").pack(side="left") 
    tk.Label(h_frame, text="ID", width=4, bg="#ccc", font=("Arial",9,"bold")).pack(side="left")
    tk.Label(h_frame, text="Mag", width=6, bg="#ccc", font=("Arial",9,"bold")).pack(side="left")
    tk.Label(h_frame, text="BP-RP", width=6, bg="#ccc", font=("Arial",9,"bold")).pack(side="left")
    tk.Label(h_frame, text="RA (deg)", width=12, bg="#ccc", font=("Arial",9,"bold")).pack(side="left")
    tk.Label(h_frame, text="Dec (deg)", width=12, bg="#ccc", font=("Arial",9,"bold")).pack(side="left")

    list_container = tk.Frame(left_frame, bg="#f0f0f0")
    list_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

    btn_frame = tk.Frame(left_frame, bg="#e0e0e0", pady=10)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
    
    # --- Zone Droite (Graphique) ---
    right_frame = tk.Frame(root, bg="black")
    right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    status_label = tk.Label(right_frame, text="Mode: SÉLECTION (Cliquez gauche T1, Droit Diagnostic)", 
                            bg="black", fg="#00ff00", font=("Consolas", 11, "bold"), pady=5)
    status_label.pack(side=tk.TOP, fill=tk.X)

    # Axes en pixels : avec projection WCS, xdata/ydata au clic sont en degrés et
    # cassent refine_centroid / le filtre comparateurs (mag T1 incohérente).
    fig = Figure(figsize=(8, 8))
    ax = fig.add_subplot(111)
    ax.imshow(
        data,
        origin="lower",
        cmap="gray",
        vmin=vmin,
        vmax=vmax,
        extent=(0, nx, 0, ny),
    )
    ax.set_xlabel("x (pixel)")
    ax.set_ylabel("y (pixel)")

    def format_coord(x, y):
        try:
            c = _pixel_to_sky(wcs, x, y)
            return f"RA={c.ra.deg:.5f} Dec={c.dec.deg:.5f}"
        except Exception:
            return ""

    ax.format_coord = format_coord

    def _parse_header_coord(header):
        ra_h = header.get("OBJCTRA") or header.get("RA")
        dec_h = header.get("OBJCTDEC") or header.get("DEC")
        if not ra_h or not dec_h:
            return None
        
        try:
            ra_val = float(ra_h)
            dec_val = float(dec_h)
            if ra_val > 24.0:
                return SkyCoord(ra_val, dec_val, unit=(u.deg, u.deg))
        except Exception:
            pass
        
        try:
            return SkyCoord(ra_h, dec_h, unit=(u.hourangle, u.deg))
        except Exception:
            try:
                return SkyCoord(float(ra_h), float(dec_h), unit=(u.deg, u.deg))
            except Exception:
                return None

    # --- Header T1 ---
    try:
        target_coord_h = header_target_coord
        if target_coord_h is None:
            target_coord_h = _parse_header_coord(header)
        
        if target_coord_h is not None:
            tx, ty = _sky_to_pixel(wcs, target_coord_h)
            if np.isfinite(tx) and np.isfinite(ty):
                c = Circle(
                    (tx, ty),
                    radius=30,
                    edgecolor='yellow',
                    ls='--',
                    lw=1.5,
                    fill=False,
                    label='header_t1'
                )
                ax.add_patch(c)
    except Exception as e:
        logging.warning(f"Impossible d'afficher T1 du header: {e}")

    canvas = FigureCanvasTkAgg(fig, master=right_frame)
    canvas.draw()

    toolbar = NavigationToolbar2Tk(canvas, right_frame)
    toolbar.update()
    toolbar.pack(side=tk.BOTTOM, fill=tk.X)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    
    # Changer le curseur pour le rendre plus visible en mode zoom
    # Utiliser "pencil" qui est plus visible
    def update_cursor(event):
        mode = toolbar.mode if hasattr(toolbar, 'mode') else ""
        if mode and mode != "" and 'zoom' in mode.lower():
            canvas_widget.config(cursor="pencil")
        else:
            canvas_widget.config(cursor="")
    
    canvas.mpl_connect('motion_notify_event', update_cursor)

    # Variables d'état
    state = {"comps": [], "vars": [], "mag_t1": None, "bp_rp_t1": None, "target": None, "fwhm_t1": None}
    
    def update_list():
        if not _tk_widget_alive(list_container):
            return
        try:
            for w in list(list_container.winfo_children()):
                w.destroy()
        except tk.TclError:
            return

        # --- Ligne T1 ---
        if state["target"]:
            row = tk.Frame(list_container, bg="#f0f0f0")
            row.pack(fill="x", pady=2)
            
            t1_var = tk.BooleanVar(value=True)
            row.t1_var = t1_var 
            chk = tk.Checkbutton(row, variable=t1_var, state="disabled", bg="#f0f0f0", width=2)
            chk.pack(side="left")
            
            tk.Label(row, text="T1", width=4, fg="red", font=("Arial",9,"bold"), bg="#f0f0f0").pack(side="left")
            
            mag = state.get("mag_t1")
            mag_val = f"{mag:.2f}" if mag else "?"
            tk.Label(row, text=mag_val, width=6, bg="#f0f0f0").pack(side="left")
            
            bprp = state.get("bp_rp_t1")
            bprp_val = f"{bprp:.2f}" if bprp is not None else "-"
            tk.Label(row, text=bprp_val, width=6, bg="#f0f0f0").pack(side="left")
            
            t = state["target"]
            tk.Label(row, text=f"{t.ra.deg:.5f}", width=12, bg="#eef").pack(side="left", padx=1)
            tk.Label(row, text=f"{t.dec.deg:.5f}", width=12, bg="#eef").pack(side="left", padx=1)
        
        # --- Lignes Comparateurs ---
        if state["comps"]:
            for i, comp_data in enumerate(state["comps"]):
                bp_rp = None
                if isinstance(comp_data, dict):
                    coord = comp_data["coord"]
                    mag = comp_data["mag"]
                    bp_rp = comp_data.get("bp_rp")
                elif len(comp_data) == 3:
                    coord, mag, bp_rp = comp_data
                else:
                    coord, mag = comp_data 

                f = tk.Frame(list_container, bg="#f0f0f0")
                f.pack(fill="x", pady=1)
                
                v = state["vars"][i]
                
                tk.Checkbutton(f, variable=v, bg="#f0f0f0", width=2).pack(side="left") 
                tk.Label(f, text=f"C{i+1}", width=4, fg="blue", bg="#f0f0f0").pack(side="left")
                
                m_txt = f"{mag:.2f}" if mag else "?"
                tk.Label(f, text=m_txt, width=6, bg="#f0f0f0").pack(side="left")
                
                br_txt = f"{bp_rp:.2f}" if bp_rp is not None else "-"
                tk.Label(f, text=br_txt, width=6, bg="#f0f0f0").pack(side="left")
                
                tk.Label(f, text=f"{coord.ra.deg:.5f}", width=12, bg="#fff").pack(side="left", padx=1)
                tk.Label(f, text=f"{coord.dec.deg:.5f}", width=12, bg="#fff").pack(side="left", padx=1)

    def on_click(event):
        # Le clic droit doit fonctionner même en mode zoom/pan
        is_right_click = event.button == MouseButton.RIGHT
        
        # Bloquons seulement le clic gauche si le mode toolbar est actif
        if not is_right_click and toolbar.mode != "" and toolbar.mode is not None:
            status_label.config(text=f"⚠️ MODE {str(toolbar.mode).upper()} ACTIF ! Désactivez la loupe.", fg="white", bg="red")
            return
        
        if not event.inaxes: return

        x_raw, y_raw = event.xdata, event.ydata
        if not np.isfinite(x_raw) or not np.isfinite(y_raw): return
            
        try:
            x_c, y_c = refine_centroid(data, x_raw, y_raw)
            if not np.isfinite(x_c) or not np.isfinite(y_c): raise ValueError("Centroidage échoué.")
            
            fwhm_info = estimate_fwhm_marginal(data, x_c, y_c)
            fwhm_val = fwhm_info[0] if fwhm_info and fwhm_info[0] else 0.0
            coord = _pixel_to_sky(wcs, x_c, y_c)
            
        except Exception as e:
            logging.error(f"Erreur de centroidage/FWHM: {e}")
            return
            
        if event.button == MouseButton.RIGHT:
            try:
                logging.info(f"Clic droit détecté à ({x_c:.1f}, {y_c:.1f}), fwhm_info={fwhm_info}")
                
                # Stocker le FWHM si c'est sur T1
                if state["target"] and fwhm_info and fwhm_info[0] is not None:
                    # Vérifier si le clic est proche de T1 (dans un rayon de 50 pixels)
                    tx, ty = _sky_to_pixel(wcs, state["target"])
                    dist = np.sqrt((x_c - tx)**2 + (y_c - ty)**2)
                    if dist < 50:  # Si le clic droit est sur T1
                        state["fwhm_t1"] = fwhm_info[0]
                        logging.info(f"FWHM T1 mesuré par clic droit : {state['fwhm_t1']:.2f} px")
                
                close_previous_diagnostics() 
                new_windows = show_diagnostics_windows(data, x_c, y_c, fwhm_info, parent=root) 
                logging.info(f"show_diagnostics_windows a retourné {len(new_windows) if new_windows else 0} fenêtres")
                if new_windows:
                    _current_diag_windows.extend(new_windows)
                    status_label.config(text=f"Diagnostic @ {x_c:.1f},{y_c:.1f}", bg="#ccffcc")
                else:
                    status_label.config(text=f"❌ Impossible d'afficher le diagnostic (FWHM invalide?)", bg="orange")
            except Exception as e:
                logging.error(f"Erreur lors de l'affichage du diagnostic: {e}", exc_info=True)
                status_label.config(text=f"❌ Erreur diagnostic: {e}", bg="red")
            
        elif event.button == MouseButton.LEFT:
            if not _tk_widget_alive(root):
                return
            if _tk_widget_alive(status_label):
                status_label.config(text="Interrogation Gaia...", fg="black", bg="orange")
            if _tk_widget_alive(root):
                root.config(cursor="watch")

            state["comps"] = []
            state["vars"] = []
            state["mag_t1"] = None
            state["bp_rp_t1"] = None

            to_remove = [p for p in ax.patches if p.get_label() != "header_t1"]
            for p in to_remove:
                p.remove()
            for t in list(ax.texts):
                t.remove()

            state["target"] = coord
            ax.add_patch(Circle((x_c, y_c), 20, edgecolor="red", lw=2, fill=False))
            ax.annotate("T1", (x_c + 25, y_c + 25), color="red", fontweight="bold")
            if not comps_full_fov:
                _draw_comp_fov_circle(
                    ax, wcs, x_c, y_c, comp_search_radius_arcmin
                )
            canvas.draw_idle()

            target_click = coord
            axes_swapped = {"v": False}

            def _run_gaia_selection():
                err_msg = None
                warn_msg = None
                info_msg = None
                cand = []
                t1_mag_local = None
                bp_rp_local = None

                try:
                    if is_asteroid:
                        if ephemeris_data is not None:
                            from astropy.time import Time

                            date_obs = header.get("DATE-OBS") or header.get("DATE")
                            if date_obs:
                                t_obs = Time(date_obs, scale="utc")
                                jd_obs = t_obs.jd
                                if (
                                    "datetime_jd" in ephemeris_data.colnames
                                    and "V" in ephemeris_data.colnames
                                ):
                                    eph_jds = ephemeris_data["datetime_jd"]
                                    mag_v = ephemeris_data["V"]
                                    t1_mag_local = float(np.interp(jd_obs, eph_jds, mag_v))
                    else:
                        v = Vizier(
                            columns=[
                                "RA_ICRS",
                                "DE_ICRS",
                                "Gmag",
                                "bp_rp",
                                "phot_variable_flag",
                            ],
                            row_limit=5000,
                        )
                        res_t1 = v.query_region(
                            target_click, radius=2.5 * u.arcsec, catalog="I/355/gaiadr3"
                        )
                        if res_t1 and len(res_t1) > 0 and len(res_t1[0]) > 0:
                            gaia_table = res_t1[0]
                            gaia_coords = _gaia_table_skycoord(gaia_table)
                            separations = target_click.separation(gaia_coords)
                            idx_closest = int(np.argmin(separations))
                            if "Gmag" in gaia_table.colnames and not np.ma.is_masked(
                                gaia_table["Gmag"][idx_closest]
                            ):
                                t1_mag_local = float(gaia_table["Gmag"][idx_closest])
                            if "bp_rp" in gaia_table.colnames and not np.ma.is_masked(
                                gaia_table["bp_rp"][idx_closest]
                            ):
                                bp_rp_local = float(gaia_table["bp_rp"][idx_closest])
                            elif "BP-RP" in gaia_table.colnames and not np.ma.is_masked(
                                gaia_table["BP-RP"][idx_closest]
                            ):
                                bp_rp_local = float(gaia_table["BP-RP"][idx_closest])
                            if t1_mag_local is None:
                                err_msg = (
                                    "Cette étoile n'a pas de magnitude (Gmag).\n"
                                    "Veuillez choisir une autre cible."
                                )
                        else:
                            err_msg = "Aucune étoile Gaia trouvée pour T1 à cette position."

                    if err_msg is None and t1_mag_local is not None:
                        if comps_full_fov:
                            gaia_field = _query_gaia_field_table(wcs, data.shape)
                        else:
                            gaia_field = _query_gaia_comparators_for_t1(
                                wcs,
                                data.shape,
                                target_click,
                                comp_search_radius_arcmin,
                                t1_mag=t1_mag_local,
                                mag_delta=comp_mag_delta,
                            )

                        if gaia_field is not None and len(gaia_field) > 0:
                            logging.info(
                                "Gaia sélection comps : %d source(s) dans le pool",
                                len(gaia_field),
                            )
                            cand = find_comparison_stars(
                                gaia_field,
                                wcs,
                                data,
                                target_click,
                                t1_mag_local,
                                max_comps=max_comps,
                                mag_delta=comp_mag_delta,
                                min_sep_from_t1_arcsec=10.0,
                                max_sep_from_t1_arcsec=comp_max_sep_arcsec,
                                chip_margin_frac=0.01,
                                spread_on_field=False,
                                axes_swapped=axes_swapped,
                            )
                            if not cand:
                                warn_msg = (
                                    f"Aucun comparateur dans {comp_search_radius_arcmin:.0f}′ "
                                    f"(G ± {comp_mag_delta:.1f} autour de T1={t1_mag_local:.2f}).\n"
                                    "Élargissez le filtre magnitude ou cliquez une autre cible."
                                )
                        elif not is_asteroid:
                            warn_msg = (
                                "Aucune étoile Gaia DR3 récupérée sur le champ.\n"
                                "Vérifiez la connexion VizieR / astroquery."
                            )
                except Exception as e:
                    logging.error("Erreur Gaia: %s", e, exc_info=True)
                    err_msg = str(e)

                def _apply_gaia_selection():
                    if not _tk_widget_alive(root):
                        return
                    try:
                        if err_msg:
                            messagebox.showerror("Gaia", err_msg, parent=root)
                            if _tk_widget_alive(status_label):
                                status_label.config(text=err_msg, fg="white", bg="red")
                            return
                        state["mag_t1"] = t1_mag_local
                        state["bp_rp_t1"] = bp_rp_local
                        state["comps"] = []
                        state["vars"] = []
                        for cc, mm, val_bp in cand:
                            state["comps"].append((cc, mm, val_bp))
                            state["vars"].append(tk.BooleanVar(value=True))
                            cx, cy = _sky_to_pixel(wcs, cc)
                            if axes_swapped.get("v"):
                                cx, cy = cy, cx
                            ax.add_patch(
                                Rectangle(
                                    (cx - 15, cy - 15), 30, 30, edgecolor="cyan", fill=False
                                )
                            )
                            ax.annotate(
                                f"C{len(state['comps'])}",
                                (cx + 18, cy),
                                color="cyan",
                                fontsize=9,
                            )
                        if not comps_full_fov and state["target"] is not None:
                            tx, ty = _sky_to_pixel(wcs, state["target"])
                            if axes_swapped.get("v"):
                                tx, ty = ty, tx
                            for p in ax.patches:
                                if p.get_label() == "comp_fov":
                                    p.remove()
                            _draw_comp_fov_circle(
                                ax,
                                wcs,
                                tx,
                                ty,
                                comp_search_radius_arcmin,
                                axes_swapped=axes_swapped.get("v", False),
                            )
                        update_list()
                        if warn_msg:
                            messagebox.showwarning("Comparateurs", warn_msg, parent=root)
                        msg = (
                            f"T1 (Mag: {state['mag_t1'] or '?'}). "
                            f"{len(state['comps'])} comparateurs."
                        )
                        if _tk_widget_alive(status_label):
                            status_label.config(text=msg, fg="#00ff00", bg="black")
                    finally:
                        if _tk_widget_alive(root):
                            root.config(cursor="")
                        try:
                            canvas.draw_idle()
                        except Exception:
                            pass

                root.after(0, _apply_gaia_selection)

            threading.Thread(target=_run_gaia_selection, daemon=True).start()

    fig.canvas.mpl_connect("button_press_event", on_click)

    def validate():
        if state["target"]:
            final_comps = [c[0] for i, c in enumerate(state["comps"]) if state["vars"][i].get()]
            close_previous_diagnostics()
            
            # Créer target_data avec coord et FWHM (si mesuré)
            target_data_dict = {"coord": state["target"]}
            if state["fwhm_t1"] is not None:
                target_data_dict["fwhm"] = state["fwhm_t1"]
                logging.info(f"FWHM T1 transmis à launch_photometry_aperture : {state['fwhm_t1']:.2f} px")
            if state.get("mag_t1") is not None:
                target_data_dict["mag"] = state["mag_t1"]
            
            on_selection_done(fits_path, target_data_dict, final_comps)
            root.destroy()
        else:
            messagebox.showwarning("Stop", "Définissez T1 avant de valider.")

    ttk.Button(btn_frame, text="✅ VALIDER LA SÉLECTION", command=validate).pack(fill=tk.X, ipady=5, padx=5)
    root.mainloop()

class TargetSelector:
    def __init__(self, fits_path=None, on_selection_done=launch_photometry_aperture):
        self.fits_path = fits_path
        self.on_selection_done = on_selection_done
    def run(self, fits_path=None, on_selection_done=None):
        launch_target_selection(fits_path or self.fits_path, on_selection_done or self.on_selection_done)
    @staticmethod
    def open(fits_path, on_selection_done=launch_photometry_aperture):
        launch_target_selection(fits_path, on_selection_done)