# core/vizier_fov_query.py
"""
Requêtes VizieR sur le champ (FOV) d'une image FITS avec WCS.

**Exoplanètes** : en priorité ``astroquery.exoplanet_orbit_database``
(`Exoplanet Orbit Database`, orbites / exoplanets.org via astroquery),
puis repli Vizier ``V/151/exoplnt`` (cdsclient puis astroquery).

Galaxies / variables : client CDS **cdsclient** si présent, sinon **astroquery.vizier**.

**Système solaire (IMCCE)** : service SkyBoT via ``astroquery.solarsystem.imcce`` ou
``astroquery.imcce`` (``Skybot.cone_search``), avec époque UT dérivée de l'en-tête FITS
(DATE-OBS, JD, MJD-OBS, etc.) ou l'heure courante en dernier recours.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.table import Table
from astropy.time import Time
from astropy.wcs import WCS

logger = logging.getLogger(__name__)

try:
    from astroquery.vizier import Vizier

    ASTROQUERY_VIZIER = True
except ImportError:
    Vizier = None  # type: ignore[misc, assignment]
    ASTROQUERY_VIZIER = False

try:
    import cdsclient.vizquery as _cds_vizquery  # noqa: F401

    CDSCLIENT_AVAILABLE = True
except ImportError:
    CDSCLIENT_AVAILABLE = False

try:
    from astroquery.exoplanet_orbit_database import ExoplanetOrbitDatabase  # noqa: F401

    EOD_AVAILABLE = True
except ImportError:
    ExoplanetOrbitDatabase = None  # type: ignore[misc, assignment]
    EOD_AVAILABLE = False

# IMCCE Solar System Services (SkyBoT) — préférence au sous-paquet solarsystem (astroquery récent)
try:
    from astroquery.solarsystem.imcce import Skybot  # noqa: F401
except ImportError:
    try:
        from astroquery.imcce import Skybot  # noqa: F401
    except ImportError:
        Skybot = None  # type: ignore[misc, assignment]

IMCCE_SKYBOT_AVAILABLE = Skybot is not None

# Catalogues Vizier (CDS)
CATALOG_EXOPLANETS = "V/151/exoplnt"
CATALOG_VSX = "B/vsx/vsx"
CATALOG_GLADE = "VIII/100/glade4"

_DEFAULT_RADIUS_ARCSEC = 40.0

_VIZIER_MIRRORS = ("vizier.cds.unistra.fr", "vizier.hia.nrc.ca")


@dataclass
class FovOverlayObject:
    category: str
    label: str
    x_pix: float
    y_pix: float
    semi_major_px: float
    semi_minor_px: float
    theta_mpl_deg: float
    details: Dict[str, str] = field(default_factory=dict)


def wcs_from_image_hdu(header) -> Optional[WCS]:
    try:
        w = WCS(header, naxis=2)
        if w.wcs is None:
            return None
        _ = w.pixel_to_world(0, 0)
        return w
    except Exception as e:
        logger.debug("WCS indisponible : %s", e)
        return None


def fov_center_and_radius_deg(wcs: WCS, nx: int, ny: int, margin: float = 1.12) -> Tuple[SkyCoord, float]:
    cx = 0.5 * float(nx - 1)
    cy = 0.5 * float(ny - 1)
    center = wcs.pixel_to_world(cx, cy)
    sep_max = 0.0
    for px, py in ((0, 0), (nx - 1, 0), (0, ny - 1), (nx - 1, ny - 1)):
        try:
            cc = wcs.pixel_to_world(px, py)
            sep_max = max(sep_max, float(center.separation(cc).to(u.deg).value))
        except Exception:
            continue
    r_deg = max(sep_max * margin, 1.0 / 3600.0)
    return center, r_deg


def fov_box_center_size_deg(
    wcs: WCS, nx: int, ny: int, margin: float = 1.02
) -> Tuple[SkyCoord, float, float]:
    """
    Centre et taille (deg) d'une boîte RA/Dec englobant les quatre coins du détecteur.
    """
    cx = 0.5 * float(nx - 1)
    cy = 0.5 * float(ny - 1)
    center = wcs.pixel_to_world(cx, cy)
    cen = center.icrs
    corners = []
    for px, py in ((0, 0), (nx - 1, 0), (0, ny - 1), (nx - 1, ny - 1)):
        try:
            corners.append(wcs.pixel_to_world(px, py).icrs)
        except Exception:
            continue
    if len(corners) < 4:
        _, r_deg = fov_center_and_radius_deg(wcs, nx, ny, margin=margin)
        side = 2.0 * r_deg
        return center, side, side

    cos_dec = float(np.cos(np.radians(cen.dec.deg)))
    cos_dec = max(cos_dec, 1e-6)
    ra_offs = []
    dec_offs = []
    for c in corners:
        dra = float(c.ra.deg - cen.ra.deg)
        dra = (dra + 180.0) % 360.0 - 180.0
        ra_offs.append(dra * cos_dec)
        dec_offs.append(float(c.dec.deg - cen.dec.deg))
    width_deg = max(float(np.ptp(ra_offs)), 1.0 / 3600.0) * margin
    height_deg = max(float(np.ptp(dec_offs)), 1.0 / 3600.0) * margin
    return center, width_deg, height_deg


def _pixel_scale_arcsec_per_px(wcs: WCS, x: float, y: float) -> float:
    try:
        c0 = wcs.pixel_to_world(x, y)
        c1 = wcs.pixel_to_world(x + 1.0, y)
        return float(c0.separation(c1).to(u.arcsec).value)
    except Exception:
        return 1.0


def _fmt_cell(v: Any) -> str:
    if v is None:
        return ""
    try:
        if hasattr(v, "mask") and np.ma.is_masked(v):
            return ""
    except Exception:
        pass
    s = str(v)
    if len(s) > 200:
        return s[:197] + "..."
    return s


def _table_row_dict(tab: Table, row_idx: int) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name in tab.colnames:
        try:
            out[str(name)] = _fmt_cell(tab[name][row_idx])
        except Exception:
            out[str(name)] = ""
    return out


def _guess_radec_columns(tab: Table) -> Optional[Tuple[str, str]]:
    cols_upper = {c.upper(): c for c in tab.colnames}
    ra_order = (
        "RAJ2000",
        "RA_ICRS",
        "_RAJ2000",
        "RA_DEG",
        "RA2000",
        "RA_DEGREE",
        "RA",
    )
    dec_order = (
        "DEJ2000",
        "DE_ICRS",
        "_DEJ2000",
        "DEC_DEG",
        "DE_DEG",
        "DE2000",
        "DEC",
        "DE",
    )
    ra_col = None
    dec_col = None
    for key in ra_order:
        if key in cols_upper:
            ra_col = cols_upper[key]
            break
        for c in tab.colnames:
            if c.lower() == key.lower():
                ra_col = c
                break
        if ra_col:
            break
    if ra_col is None:
        for c in tab.colnames:
            if c.lower() == "ra":
                ra_col = c
                break
    for key in dec_order:
        if key in cols_upper:
            dec_col = cols_upper[key]
            break
        for c in tab.colnames:
            if c.lower() == key.lower():
                dec_col = c
                break
        if dec_col:
            break
    if dec_col is None:
        for c in tab.colnames:
            if c.lower() == "dec":
                dec_col = c
                break
    if ra_col and dec_col:
        return ra_col, dec_col
    return None


def _row_radec_deg(tab: Table, i: int, ra_col: str, dec_col: str) -> Optional[Tuple[float, float]]:
    ra_v = tab[ra_col][i]
    dec_v = tab[dec_col][i]
    try:
        if hasattr(ra_v, "mask") and np.ma.is_masked(ra_v):
            return None
        if hasattr(dec_v, "mask") and np.ma.is_masked(dec_v):
            return None
    except Exception:
        pass

    if isinstance(ra_v, (int, float, np.floating)) and isinstance(dec_v, (int, float, np.floating)):
        ra_f = float(ra_v)
        dec_f = float(dec_v)
        if np.isfinite(ra_f) and np.isfinite(dec_f):
            return ra_f, dec_f

    try:
        sc = SkyCoord(ra_v, dec_v, unit=(u.hourangle, u.deg))
        return float(sc.ra.deg), float(sc.dec.deg)
    except Exception:
        pass
    try:
        sc = SkyCoord(ra_v, dec_v, unit=(u.deg, u.deg))
        return float(sc.ra.deg), float(sc.dec.deg)
    except Exception:
        return None


def overlay_contains_pixel(o: FovOverlayObject, x: float, y: float, pad: float = 1.1) -> bool:
    dx = x - o.x_pix
    dy = y - o.y_pix
    th = np.radians(-o.theta_mpl_deg)
    ca, sa = np.cos(th), np.sin(th)
    xr = dx * ca - dy * sa
    yr = dx * sa + dy * ca
    a = max(o.semi_major_px * pad, 1e-6)
    b = max(o.semi_minor_px * pad, 1e-6)
    return (xr / a) ** 2 + (yr / b) ** 2 <= 1.0


def _exo_label(tab: Table, i: int) -> str:
    for key in ("NAME", "pl_name", "pl_orbname", "name", "hostname", "sy_name"):
        if key in tab.colnames:
            v = _fmt_cell(tab[key][i]).strip()
            if v:
                return v[:48]
    return f"exo#{i + 1}"


def _galaxy_label(tab: Table, i: int) -> str:
    for key in ("GLADE", "Name", "name", "Designation", "PGC"):
        if key in tab.colnames:
            v = _fmt_cell(tab[key][i]).strip()
            if v:
                return v[:48]
    return f"gal#{i + 1}"


def _variable_label(tab: Table, i: int) -> str:
    for key in ("Name", "ID", "OID", "identifier"):
        if key in tab.colnames:
            v = _fmt_cell(tab[key][i]).strip()
            if v:
                return v[:48]
    return f"var#{i + 1}"


def _ss_label(tab: Table, i: int) -> str:
    for key in ("Name", "NAME", "name"):
        if key in tab.colnames:
            v = _fmt_cell(tab[key][i]).strip()
            if v:
                return v[:48]
    return f"SS#{i + 1}"


def observation_time_from_header(header) -> Optional[Time]:
    """Tente d'extraire l'instant d'observation (UTC) depuis un en-tête FITS."""
    if header is None:
        return None
    try:
        if "JD" in header:
            return Time(float(header["JD"]), format="jd", scale="utc")
    except Exception:
        pass
    try:
        if "MJD-OBS" in header:
            return Time(float(header["MJD-OBS"]), format="mjd", scale="utc")
    except Exception:
        pass
    date_obs = header.get("DATE-OBS") or header.get("DATEAVG")
    if date_obs:
        s = str(date_obs).strip()
        try:
            if "T" in s:
                return Time(s, format="isot", scale="utc")
        except Exception:
            pass
        time_obs = header.get("TIME-OBS") or header.get("UT-OBS") or header.get("UTC-OBS")
        if time_obs:
            day = s.split("T")[0].strip()
            try:
                return Time(f"{day}T{str(time_obs).strip()}", format="isot", scale="utc")
            except Exception:
                pass
        try:
            return Time(s, format="iso", scale="utc")
        except Exception:
            pass
    return None


def _query_imcce_skybot(
    center: SkyCoord,
    radius_deg: float,
    epoch: Time,
) -> Optional[Table]:
    """
    Cône SkyBoT (IMCCE). Rayon maximal du service : 10° (tronqué si besoin).
    """
    if not IMCCE_SKYBOT_AVAILABLE or Skybot is None:
        return None
    r_deg = min(float(radius_deg), 10.0)
    if r_deg < float(radius_deg):
        logger.debug("SkyBoT : rayon limité à 10° (service IMCCE)")
    try:
        cen = center.icrs
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tab = Skybot.cone_search(cen, r_deg * u.deg, epoch)
        if tab is None or len(tab) == 0:
            return None
        logger.debug("IMCCE SkyBoT : %d ligne(s)", len(tab))
        return tab
    except Exception as e:
        logger.debug("IMCCE SkyBoT : %s", e)
        return None


def _table_to_overlays(
    tab: Table,
    category: str,
    label_fn,
    wcs: WCS,
    nx: int,
    ny: int,
    default_arcsec: float,
    *,
    chip_margin_frac: float = 0.05,
) -> List[FovOverlayObject]:
    """Projette les lignes du catalogue en pixels ; utilise ``sky_coord`` si présent (EOD)."""
    use_sky_coord = "sky_coord" in tab.colnames
    rd: Optional[Tuple[str, str]] = None
    if not use_sky_coord:
        rd = _guess_radec_columns(tab)
        if rd is None:
            logger.warning("Colonnes RA/Dec introuvables pour %s", category)
            return []

    out: List[FovOverlayObject] = []
    n = len(tab)
    for i in range(n):
        try:
            if use_sky_coord:
                coord = tab["sky_coord"][i]
                if coord is None:
                    continue
                coord = SkyCoord(coord).icrs
            else:
                assert rd is not None
                rdg = _row_radec_deg(tab, i, rd[0], rd[1])
                if rdg is None:
                    continue
                ra, dec = rdg
                if not (np.isfinite(ra) and np.isfinite(dec)):
                    continue
                coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
            xp, yp = wcs.world_to_pixel(coord)
        except Exception:
            continue
        xp_f = float(xp)
        yp_f = float(yp)
        m = max(0.0, float(chip_margin_frac))
        if (
            xp_f < -nx * m
            or xp_f > nx * (1.0 + m)
            or yp_f < -ny * m
            or yp_f > ny * (1.0 + m)
        ):
            continue

        scale = _pixel_scale_arcsec_per_px(wcs, xp_f, yp_f)
        scale = max(scale, 1e-6)
        r_px = max(8.0, min(45.0, default_arcsec / scale))
        b_px = max(6.0, r_px * 0.72)

        details = _table_row_dict(tab, i)
        label = label_fn(tab, i)
        out.append(
            FovOverlayObject(
                category=category,
                label=label,
                x_pix=xp_f,
                y_pix=yp_f,
                semi_major_px=r_px,
                semi_minor_px=b_px,
                theta_mpl_deg=25.0,
                details=details,
            )
        )
    return out


def _query_exoplanets_orbit_database(center: SkyCoord, radius_deg: float) -> Optional[Table]:
    """
    Base « Exoplanet Orbit Database » via astroquery.exoplanet_orbit_database.
    Télécharge la table (cache astropy), puis filtre par séparation angulaire.
    """
    if not EOD_AVAILABLE or ExoplanetOrbitDatabase is None:
        return None
    try:
        from astropy.utils.exceptions import AstropyDeprecationWarning
    except ImportError:
        AstropyDeprecationWarning = UserWarning  # type: ignore[misc, assignment]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyDeprecationWarning)
        try:
            full = ExoplanetOrbitDatabase.get_table(cache=True, show_progress=False)
        except Exception as e:
            logger.debug("Exoplanet Orbit Database get_table : %s", e)
            return None

    try:
        cen = center.icrs
        sep = full["sky_coord"].separation(cen)
        mask = sep <= (float(radius_deg) * u.deg)
        sub = full[mask]
        if len(sub) == 0:
            return None
        logger.debug("Exoplanet Orbit Database : %d ligne(s) dans le cône", len(sub))
        return sub
    except Exception as e:
        logger.warning("Filtrage cône Exoplanet Orbit Database : %s", e)
        return None


def _query_vizier_cdsclient(
    catalog_id: str,
    center: SkyCoord,
    radius_deg: float,
    row_limit: int,
) -> Optional[Table]:
    """
    Requête VizieR via cdsclient.vizquery.CDSClient (cds.cdsclient).
    Rayon ASU : -c.rs en **secondes d'arc** (voir vizquery.py).
    """
    if not CDSCLIENT_AVAILABLE:
        return None
    try:
        from urllib.parse import quote

        from cdsclient import vizquery as vq
    except ImportError:
        return None

    try:
        c = center.icrs
        pos = f"{float(c.ra.deg)} {float(c.dec.deg)}"
        r_arcsec = max(float(radius_deg) * 3600.0, 1.0)
        params = [
            "-c={0}".format(quote(pos)),
            "-c.rs={0:f}".format(r_arcsec),
            "-out.max={0:d}".format(int(row_limit)),
        ]
        client = vq.CDSClient(
            default_format=vq.FORMAT_VOTABLE,
            default_limit=int(row_limit),
        )
        client.query(catalog_id, params)
        tab = client.get()
        if tab is None or len(tab) == 0:
            return None
        logger.debug("cdsclient VizieR %s : %d ligne(s)", catalog_id, len(tab))
        return tab
    except Exception as e:
        logger.debug("cdsclient %s : %s", catalog_id, e)
        return None


def _query_one_catalog_astroquery(
    viz: Vizier,
    catalog_id: str,
    center: SkyCoord,
    radius_deg: float,
) -> Optional[Table]:
    last_err: Optional[Exception] = None
    for host in _VIZIER_MIRRORS:
        try:
            viz.VIZIER_SERVER = host
            result = viz.query_region(center, radius=radius_deg * u.deg, catalog=catalog_id)
            if not result:
                return None
            tab = result[0]
            if tab is None or len(tab) == 0:
                return None
            return tab
        except Exception as e:
            last_err = e
            logger.debug("Vizier astroquery %s via %s : %s", catalog_id, host, e)
            continue
    logger.warning("Vizier astroquery %s : %s", catalog_id, last_err)
    return None


def _query_one_catalog_astroquery_box(
    viz: Vizier,
    catalog_id: str,
    center: SkyCoord,
    width_deg: float,
    height_deg: float,
) -> Optional[Table]:
    last_err: Optional[Exception] = None
    for host in _VIZIER_MIRRORS:
        try:
            viz.VIZIER_SERVER = host
            result = viz.query_region(
                center,
                width=width_deg * u.deg,
                height=height_deg * u.deg,
                catalog=catalog_id,
            )
            if not result:
                return None
            tab = result[0]
            if tab is None or len(tab) == 0:
                return None
            return tab
        except Exception as e:
            last_err = e
            logger.debug(
                "Vizier astroquery boîte %s via %s : %s", catalog_id, host, e
            )
            continue
    logger.warning("Vizier astroquery boîte %s : %s", catalog_id, last_err)
    return None


def _query_one_catalog(
    viz: Optional[Vizier],
    catalog_id: str,
    center: SkyCoord,
    radius_deg: float,
    row_limit: int,
    *,
    width_deg: Optional[float] = None,
    height_deg: Optional[float] = None,
) -> Optional[Table]:
    use_box = (
        width_deg is not None
        and height_deg is not None
        and width_deg > 0
        and height_deg > 0
    )
    if use_box and ASTROQUERY_VIZIER and viz is not None:
        tab = _query_one_catalog_astroquery_box(
            viz, catalog_id, center, width_deg, height_deg
        )
        if tab is not None and len(tab) > 0:
            return tab
        r_equiv = radius_deg
    else:
        r_equiv = radius_deg
    tab = _query_vizier_cdsclient(catalog_id, center, r_equiv, row_limit)
    if tab is not None and len(tab) > 0:
        return tab
    if not ASTROQUERY_VIZIER or viz is None:
        return None
    if use_box:
        return _query_one_catalog_astroquery_box(
            viz, catalog_id, center, width_deg, height_deg
        )
    return _query_one_catalog_astroquery(viz, catalog_id, center, radius_deg)


def query_fov_overlays(
    wcs: WCS,
    shape: Tuple[int, int],
    *,
    include_exoplanets: bool = True,
    include_galaxies: bool = True,
    include_variables: bool = True,
    include_solar_system: bool = False,
    observation_time: Optional[Time] = None,
    row_limit: int = 8000,
    fov_query: str = "cone",
    fov_margin: float = 1.12,
    chip_margin_frac: float = 0.05,
) -> List[FovOverlayObject]:
    any_vizier = include_exoplanets or include_galaxies or include_variables
    if any_vizier and not (CDSCLIENT_AVAILABLE or ASTROQUERY_VIZIER or EOD_AVAILABLE):
        raise RuntimeError(
            "Installer cdsclient et/ou astroquery (dont exoplanet_orbit_database si disponible)."
        )
    if include_solar_system and not IMCCE_SKYBOT_AVAILABLE and not any_vizier:
        raise RuntimeError(
            "Installer astroquery avec IMCCE (SkyBoT : astroquery.solarsystem.imcce ou astroquery.imcce)."
        )

    ny, nx = int(shape[0]), int(shape[1])
    box_w_deg: Optional[float] = None
    box_h_deg: Optional[float] = None
    if fov_query == "box":
        center, box_w_deg, box_h_deg = fov_box_center_size_deg(
            wcs, nx, ny, margin=fov_margin
        )
        _, r_corner = fov_center_and_radius_deg(wcs, nx, ny, margin=fov_margin)
        r_deg = max(
            0.5 * float(np.hypot(box_w_deg, box_h_deg)),
            r_corner,
        )
    else:
        center, r_deg = fov_center_and_radius_deg(wcs, nx, ny, margin=fov_margin)

    viz = None
    if ASTROQUERY_VIZIER:
        viz = Vizier(columns=["**"])
        viz.ROW_LIMIT = int(row_limit)

    overlays: List[FovOverlayObject] = []
    overlay_kw = {"chip_margin_frac": chip_margin_frac}

    if include_exoplanets:
        tab = _query_exoplanets_orbit_database(center, r_deg)
        if tab is None or len(tab) == 0:
            tab = _query_one_catalog(viz, CATALOG_EXOPLANETS, center, r_deg, row_limit)
        if tab is not None and len(tab) > 0:
            overlays.extend(
                _table_to_overlays(
                    tab, "exoplanet", _exo_label, wcs, nx, ny, _DEFAULT_RADIUS_ARCSEC, **overlay_kw
                )
            )

    if include_galaxies:
        tab = _query_one_catalog(viz, CATALOG_GLADE, center, r_deg, row_limit)
        if tab is not None and len(tab) > 0:
            overlays.extend(
                _table_to_overlays(
                    tab,
                    "galaxy",
                    _galaxy_label,
                    wcs,
                    nx,
                    ny,
                    _DEFAULT_RADIUS_ARCSEC * 1.25,
                    **overlay_kw,
                )
            )

    if include_variables:
        tab = _query_one_catalog(
            viz,
            CATALOG_VSX,
            center,
            r_deg,
            row_limit,
            width_deg=box_w_deg,
            height_deg=box_h_deg,
        )
        if (tab is None or len(tab) == 0) and fov_query == "box":
            logger.info("VSX boîte vide — repli cône r=%.4f°", r_deg)
            tab = _query_one_catalog(viz, CATALOG_VSX, center, r_deg, row_limit)
        if tab is not None and len(tab) > 0:
            overlays.extend(
                _table_to_overlays(
                    tab,
                    "variable",
                    _variable_label,
                    wcs,
                    nx,
                    ny,
                    _DEFAULT_RADIUS_ARCSEC * 0.9,
                    **overlay_kw,
                )
            )

    if include_solar_system and IMCCE_SKYBOT_AVAILABLE:
        epoch = observation_time
        if epoch is None:
            epoch = Time.now()
            logger.info("SkyBoT (IMCCE) : instant d'observation absent de l'en-tête — époque UTC actuelle.")
        tab = _query_imcce_skybot(center, r_deg, epoch)
        if tab is not None and len(tab) > 0:
            overlays.extend(
                _table_to_overlays(
                    tab,
                    "solar_system",
                    _ss_label,
                    wcs,
                    nx,
                    ny,
                    _DEFAULT_RADIUS_ARCSEC * 0.85,
                    **overlay_kw,
                )
            )

    if fov_query == "box" and box_w_deg is not None and box_h_deg is not None:
        logger.info(
            "Vizier FOV boîte : %d objets (var=%s) %.3f°×%.3f° marge=%.2f chip±%.0f%%",
            len(overlays),
            include_variables,
            box_w_deg,
            box_h_deg,
            fov_margin,
            chip_margin_frac * 100.0,
        )
    else:
        logger.info(
            "Vizier FOV : %d objets (exo=%s gal=%s var=%s ss=%s) r=%.4f° centre=%s — "
            "eod=%s cdsclient=%s astroquery=%s imcce_skybot=%s",
            len(overlays),
            include_exoplanets,
            include_galaxies,
            include_variables,
            include_solar_system,
            r_deg,
            center.to_string("hmsdms"),
            EOD_AVAILABLE,
            CDSCLIENT_AVAILABLE,
            ASTROQUERY_VIZIER,
            IMCCE_SKYBOT_AVAILABLE,
        )
    return overlays
