# core/exoplanetpie_pipeline.py
"""
Pipeline ExoPlanetPie natif NPOAP : ExoClock / NASA Archive -> téléchargement TESS/Kepler ->
slicing par cycle -> fit batman + ultranest (LDC ExoTETHyS) -> diagramme O-C.

Réimplémentation en Python pur des fonctions de ExoPlanetPie 4.3.0 (Pieter Vuylsteke),
sans dépendre du `.exe` PyInstaller.

Dépendances optionnelles (toutes listées dans requirements.txt) :
    batman-package, ultranest, lightkurve, astroquery, exotethys.

Toutes sont importées de façon protégée : le module se charge même si certaines
sont absentes (les fonctions concernées lèvent alors une RuntimeError explicite).
"""

from __future__ import annotations

import json
import logging
import math
import time as _time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Imports protégés
# ────────────────────────────────────────────────────────────────────────────
try:
    import batman  # batman-package
    BATMAN_AVAILABLE = True
except ImportError:
    BATMAN_AVAILABLE = False
    logger.warning("batman-package indisponible (pip install batman-package).")

try:
    from ultranest import ReactiveNestedSampler
    ULTRANEST_AVAILABLE = True
except ImportError:
    ULTRANEST_AVAILABLE = False
    logger.warning("ultranest indisponible (pip install ultranest).")

try:
    import lightkurve as lk  # type: ignore
    LIGHTKURVE_AVAILABLE = True
except Exception:  # lightkurve peut lever ImportError ou ValueError selon l'env
    LIGHTKURVE_AVAILABLE = False
    logger.warning("lightkurve indisponible (pip install lightkurve).")

try:
    from core.exotethys_ldc import (
        EXOTETHYS_AVAILABLE,
        run_exotethys_ldc_claret4,
    )
except Exception:
    EXOTETHYS_AVAILABLE = False

    def run_exotethys_ldc_claret4(*_args, **_kwargs):  # type: ignore[no-redef]
        raise RuntimeError("ExoTETHyS indisponible : voir core.exotethys_ldc")

# ────────────────────────────────────────────────────────────────────────────
# Constantes / configuration
# ────────────────────────────────────────────────────────────────────────────
EXOCLOCK_PLANETS_URL = "https://www.exoclock.space/database/planets_json"
NASA_TAP_SYNC = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
DEFAULT_USER_AGENT = "NPOAP-ExoPlanetPie/1.0"
DEFAULT_HTTP_TIMEOUT = 60

# Filtres exoplanetpie -> codes utilisés par exotethys (cf. core/exotethys_ldc.py)
SUPPORTED_FILTERS: Tuple[str, ...] = (
    "TESS",
    "COUSINS_V",
    "COUSINS_R",
    "COUSINS_I",
    "SLOAN_g",
    "SLOAN_r",
    "SLOAN_i",
    "G",
    "G_BP",
    "G_RP",
)


@dataclass
class PlanetParams:
    """Paramètres minimaux d'un système étoile-planète."""

    name: str = ""
    ra_deg: float = 0.0
    dec_deg: float = 0.0
    # Étoile
    teff: float = 5800.0        # K
    logg: float = 4.5           # cgs
    feh: float = 0.0            # [Fe/H]
    rstar_rsun: float = 1.0
    mstar_msun: float = 1.0
    # Planète / orbite
    period_d: float = 1.0
    t0_bjd: float = 2_457_000.0  # BJD_TDB
    rp_over_rs: float = 0.1
    sma_over_rs: float = 10.0
    inclination_deg: float = 89.0
    eccentricity: float = 0.0
    arg_periastron_deg: float = 90.0
    duration_d: float = 0.1     # transit duration (approx., for selection window)
    source: str = ""             # "exoclock" | "nasa_archive" | "manual"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanetParams":
        valid = {k: v for k, v in d.items() if k in cls.__annotations__}
        return cls(**valid)


@dataclass
class TransitFitResult:
    """Sortie d'un fit batman+ultranest pour un transit individuel."""

    cycle: int
    t0_bjd: float
    t0_err_minus: float
    t0_err_plus: float
    rp_over_rs: float
    rp_over_rs_err: float
    chi2_red: float
    n_points: int
    detrend_order: int
    samples_path: Optional[str] = None
    logz: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ────────────────────────────────────────────────────────────────────────────
# 1. GetPlanet : ExoClock + NASA Exoplanet Archive
# ────────────────────────────────────────────────────────────────────────────
def _http_get_json(url: str, timeout: float = DEFAULT_HTTP_TIMEOUT) -> Any:
    """
    GET URL et parse en JSON.

    Particularité : les TAP (NASA Exoplanet Archive, Vizier, …) renvoient un corps
    de réponse texte explicite en cas d'erreur ADQL/SQL mais avec un code 400. On
    le récupère et on le concatène au message d'exception pour que l'utilisateur
    voie la cause réelle (« Unknown column foo », « Syntax error », …).
    """
    req = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as err:
        body = ""
        try:
            body = err.read().decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            pass
        snippet = body[:500] if body else "(corps de réponse vide)"
        raise RuntimeError(
            f"HTTP {err.code} sur {url}\n→ Réponse serveur : {snippet}"
        ) from err


def fetch_exoclock_planets_catalog() -> Dict[str, Any]:
    """
    Télécharge le catalogue ExoClock (planets_json).
    Retourne un dict {nom_planète: enregistrement}.
    """
    data = _http_get_json(EXOCLOCK_PLANETS_URL)
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Réponse ExoClock inattendue pour {EXOCLOCK_PLANETS_URL} (attendu: dict)."
        )
    return data


def _feh_from_exoclock_record(p: Dict[str, Any]) -> float:
    """
    [Fe/H] depuis un enregistrement ExoClock.

    L'ancien code utilisait ``feh=_f("meta", ...)`` : ``meta`` est souvent absent ou non
    numérique, ce qui forçait 0.0 tout en pouvant perturber la résolution ExoTETHyS.
    On essaie plusieurs clés courantes et un sous-dict ``meta`` éventuel.
    """
    keys = ("feh", "metallicity", "metal", "mh", "st_met", "star_metallicity")

    def _try(obj: Any) -> Optional[float]:
        if not isinstance(obj, dict):
            return None
        for k in keys:
            if k not in obj:
                continue
            try:
                v = float(obj[k])
                if math.isfinite(v):
                    return v
            except (TypeError, ValueError):
                continue
        return None

    v = _try(p)
    if v is not None:
        return v
    meta = p.get("meta")
    v = _try(meta) if meta is not None else None
    if v is not None:
        return v
    return 0.0


def fetch_planet_from_exoclock(planet_name: str) -> PlanetParams:
    """
    Interroge ExoClock (`https://www.exoclock.space/database/planets_json`)
    pour récupérer les éphémérides étoile+planète. Lève KeyError si absent.
    """
    data = _http_get_json(EXOCLOCK_PLANETS_URL)
    if not isinstance(data, dict):
        raise RuntimeError("Réponse ExoClock inattendue (pas un dict).")

    target = planet_name.strip()
    lookup = {k.lower(): k for k in data.keys()}
    found_key = lookup.get(target.lower()) or lookup.get(target.replace(" ", "").lower())
    if found_key is None:
        # essai en supprimant les espaces sur les clés d'ExoClock
        compact = {k.replace(" ", "").lower(): k for k in data.keys()}
        found_key = compact.get(target.replace(" ", "").lower())
    if found_key is None:
        raise KeyError(f"Planète « {planet_name} » introuvable sur ExoClock.")

    p = data[found_key]

    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(p[key])
        except (KeyError, TypeError, ValueError):
            return default

    return PlanetParams(
        name=found_key,
        ra_deg=_f("ra_j2000", _f("ra")),
        dec_deg=_f("dec_j2000", _f("dec")),
        teff=_f("teff", 5800.0),
        logg=_f("logg", 4.5),
        feh=_feh_from_exoclock_record(p),
        rstar_rsun=_f("rstar", _f("r_star", 1.0)),
        mstar_msun=_f("mstar", _f("m_star", 1.0)),
        period_d=_f("ephem_period", _f("period")),
        t0_bjd=_f("ephem_mid_time", _f("t0")),
        rp_over_rs=_f("rp_over_rs"),
        sma_over_rs=_f("sma_over_rs"),
        inclination_deg=_f("inclination", 89.0),
        eccentricity=_f("eccentricity", 0.0),
        arg_periastron_deg=_f("periastron", 90.0),
        duration_d=_f("duration", 0.0) / 24.0 if _f("duration", 0.0) > 1.0 else _f("duration", 0.1),
        source="exoclock",
    )


def _nasa_name_variants(planet_name: str) -> List[str]:
    """
    Génère plusieurs orthographes du nom de planète à tester contre
    ``pscomppars.pl_name``.

    Le NASA Exoplanet Archive utilise le nom **confirmé** de la planète (ex.
    ``TOI-216 b``) alors que l'utilisateur saisit souvent le nom **TOI**
    (``TOI-216.01``, format mission TESS). On essaie successivement le nom
    original, le nom sans espaces parasites, les variantes ``.01 → b``,
    ``.02 → c``, et un repli en majuscules.
    """
    name = planet_name.strip()
    seen: List[str] = []

    def _add(s: str) -> None:
        s = s.strip()
        if s and s not in seen:
            seen.append(s)

    _add(name)
    _add(" ".join(name.split()))
    _add(name.upper())

    # Variantes TOI-xxx.0N -> TOI-xxx <lettre>
    import re

    m = re.match(r"^\s*(?P<root>[A-Za-z0-9\-]+?)[.\s]+(?P<idx>\d+)\s*$", name)
    if m:
        root = m.group("root")
        idx = int(m.group("idx"))
        # .01 = b, .02 = c, .03 = d, ...
        letter = chr(ord("b") + max(idx - 1, 0)) if idx >= 1 else "b"
        _add(f"{root} {letter}")
        _add(f"{root.upper()} {letter}")
        _add(f"{root}-{letter}")

    return seen


def fetch_planet_from_nasa_archive(planet_name: str) -> PlanetParams:
    """
    Interroge le NASA Exoplanet Archive TAP (table ``pscomppars``).

    ``pscomppars`` est déjà la table « best parameters per planet » : elle
    expose une seule ligne par planète (les valeurs **par défaut** sélectionnées
    automatiquement). La colonne ``default_flag`` n'existe que dans la table
    ``ps`` (rangée par référence) ; l'utiliser ici renvoie un HTTP 400.

    Plusieurs orthographes du nom sont essayées (voir :func:`_nasa_name_variants`).
    """
    from urllib.parse import urlencode

    last_error: Optional[Exception] = None
    for candidate in _nasa_name_variants(planet_name):
        pl_name = candidate.replace("'", "''")
        adql = (
            "select pl_name,ra,dec,st_teff,st_logg,st_met,st_rad,st_mass,"
            "pl_orbper,pl_tranmid,pl_ratror,pl_ratdor,pl_orbincl,pl_orbeccen,"
            "pl_orblper,pl_trandur "
            "from pscomppars "
            f"where lower(pl_name)=lower('{pl_name}')"
        )
        url = NASA_TAP_SYNC + "?" + urlencode(
            {"query": adql, "format": "json"}
        )
        try:
            rows = _http_get_json(url)
        except RuntimeError as exc:  # remontée par _http_get_json (HTTPError -> RuntimeError)
            last_error = exc
            logger.debug("NASA TAP a échoué pour « %s » : %s", candidate, exc)
            continue
        if rows:
            logger.info(
                "NASA Exoplanet Archive : « %s » résolu en « %s ».",
                planet_name, candidate,
            )
            break
    else:
        # Aucune variante n'a renvoyé de lignes ; si la dernière était une erreur,
        # on la remonte (utile pour HTTP 400/500). Sinon : Not Found.
        if last_error is not None:
            raise last_error
        raise KeyError(
            f"Planète « {planet_name} » introuvable dans NASA Exoplanet Archive "
            f"(variantes essayées : {', '.join(_nasa_name_variants(planet_name))})."
        )
    r = rows[0]

    def _f(k: str, default: float = 0.0) -> float:
        v = r.get(k)
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    duration_h = _f("pl_trandur", 0.0)
    return PlanetParams(
        name=r.get("pl_name") or planet_name,
        ra_deg=_f("ra"),
        dec_deg=_f("dec"),
        teff=_f("st_teff", 5800.0),
        logg=_f("st_logg", 4.5),
        feh=_f("st_met", 0.0),
        rstar_rsun=_f("st_rad", 1.0),
        mstar_msun=_f("st_mass", 1.0),
        period_d=_f("pl_orbper", 1.0),
        t0_bjd=_f("pl_tranmid", 2_457_000.0),
        rp_over_rs=_f("pl_ratror", 0.1),
        sma_over_rs=_f("pl_ratdor", 10.0),
        inclination_deg=_f("pl_orbincl", 89.0),
        eccentricity=_f("pl_orbeccen", 0.0),
        arg_periastron_deg=_f("pl_orblper", 90.0),
        duration_d=duration_h / 24.0 if duration_h > 0 else 0.1,
        source="nasa_archive",
    )


# ────────────────────────────────────────────────────────────────────────────
# 2. SatelliteData : téléchargement TESS/Kepler via lightkurve
# ────────────────────────────────────────────────────────────────────────────
def list_satellite_lightcurves(
    target: str, mission: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Renvoie la liste des fichiers TESS/Kepler/K2 trouvés sur MAST pour ``target``.
    Chaque entrée : {mission, author, year, exptime, target_name, ref}
    où ``ref`` est l'objet SearchResult row utilisable par :func:`download_satellite_lightcurve`.
    """
    if not LIGHTKURVE_AVAILABLE:
        raise RuntimeError("lightkurve non installé (pip install lightkurve).")

    sr = lk.search_lightcurve(target, mission=mission) if mission else lk.search_lightcurve(target)
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(sr):
        # lightkurve >= 2.4 : SearchResult est itérable, row.table possède les colonnes
        try:
            t = row.table[0]
            year = int(str(t.get("t_min", ""))[:4]) if t.get("t_min") else 0
        except Exception:
            t = {}
            year = 0
        out.append(
            {
                "index": i,
                "mission": str(t.get("project") or t.get("obs_collection") or ""),
                "author": str(t.get("author") or t.get("provenance_name") or ""),
                "year": year,
                "exptime": float(t.get("t_exptime", 0.0) or 0.0),
                "target_name": str(t.get("target_name") or target),
                "ok": True,
            }
        )
    # On garde la SearchResult complète pour téléchargement ultérieur.
    list_satellite_lightcurves._last_search = sr  # type: ignore[attr-defined]
    return out


def download_satellite_lightcurve(
    index: int,
    out_dir: Path,
    flux_column: str = "pdcsap_flux",
) -> Path:
    """
    Télécharge la light-curve sélectionnée (via :func:`list_satellite_lightcurves`)
    et l'enregistre en CSV `time, flux, flux_err` (BJD_TDB).
    """
    if not LIGHTKURVE_AVAILABLE:
        raise RuntimeError("lightkurve non installé.")
    sr = getattr(list_satellite_lightcurves, "_last_search", None)
    if sr is None:
        raise RuntimeError(
            "Aucune SearchResult en cache : relancez la recherche avant le téléchargement."
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lc = sr[index].download(flux_column=flux_column)
    if lc is None:
        raise RuntimeError(f"Téléchargement vide pour l'index {index}.")
    lc = lc.remove_nans()
    t = np.asarray(lc.time.value, dtype=float)
    # lightkurve BTJD -> BJD_TDB : pour TESS, time + 2457000 ; pour Kepler, time + 2454833.
    fmt = getattr(lc.time, "format", "")
    if fmt == "btjd":
        t = t + 2_457_000.0
    elif fmt == "bkjd":
        t = t + 2_454_833.0

    f = np.asarray(lc.flux.value, dtype=float)
    fe_raw = getattr(lc, "flux_err", None)
    if fe_raw is None:
        fe = np.full_like(f, np.nan)
    else:
        fe = np.asarray(fe_raw.value, dtype=float)

    fname = f"{lc.meta.get('TARGETID', sr[index].target_name[0])}_{lc.meta.get('SECTOR', lc.meta.get('QUARTER', 'X'))}_{index}.csv"
    fpath = out_dir / fname.replace(" ", "_")
    arr = np.column_stack([t, f, fe])
    np.savetxt(fpath, arr, delimiter=",", header="time_bjd_tdb,flux,flux_err", comments="")
    logger.info("LightCurve sauvegardée : %s (%d points)", fpath, len(t))
    return fpath


# ────────────────────────────────────────────────────────────────────────────
# 3. Detrend + normalisation simple (polynôme global hors-transit)
# ────────────────────────────────────────────────────────────────────────────
def detrend_and_normalize(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: Optional[np.ndarray],
    transit_mask: Optional[np.ndarray] = None,
    poly_order: int = 2,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Ajuste un polynôme d'ordre ``poly_order`` sur les points HORS transit, divise.
    Si ``transit_mask`` est None, on suppose qu'il n'y a pas de transit (normalisation globale).
    """
    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    if transit_mask is None:
        keep = ok
    else:
        keep = ok & (~np.asarray(transit_mask, dtype=bool))
    if keep.sum() < poly_order + 2:
        return f / np.nanmedian(f[ok]), (flux_err / np.nanmedian(f[ok]) if flux_err is not None else None)
    coeffs = np.polyfit(t[keep] - t[keep].mean(), f[keep], poly_order)
    baseline = np.polyval(coeffs, t - t[keep].mean())
    fn = f / baseline
    fen = flux_err / baseline if flux_err is not None else None
    return fn, fen


# ────────────────────────────────────────────────────────────────────────────
# 4. PrepareData : repérer les transits & découper en cycles
# ────────────────────────────────────────────────────────────────────────────
def list_expected_transits(
    time: np.ndarray,
    t0_bjd: float,
    period_d: float,
) -> List[Tuple[int, float]]:
    """Retourne la liste (cycle_number, expected_t0) couverts par ``time``."""
    t = np.asarray(time, dtype=float)
    if t.size == 0 or period_d <= 0.0:
        return []
    n_min = int(math.floor((t.min() - t0_bjd) / period_d)) - 1
    n_max = int(math.ceil((t.max() - t0_bjd) / period_d)) + 1
    out: List[Tuple[int, float]] = []
    for n in range(n_min, n_max + 1):
        tc = t0_bjd + n * period_d
        if t.min() - period_d * 0.5 <= tc <= t.max() + period_d * 0.5:
            out.append((n, tc))
    return out


def slice_transits(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: Optional[np.ndarray],
    t0_bjd: float,
    period_d: float,
    selection_hours: float = 6.0,
    duration_d: float = 0.1,
) -> List[Dict[str, Any]]:
    """
    Découpe la light-curve en fenêtres ``[tc - selection_h/24, tc + selection_h/24]``
    pour chaque cycle couvert. Garde uniquement les fenêtres avec >= 30 points.

    Renvoie une liste de dicts {cycle, t_expected, time, flux, flux_err}.
    """
    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    fe = np.asarray(flux_err, dtype=float) if flux_err is not None else None
    half = max(selection_hours / 24.0, 1.5 * duration_d)
    out: List[Dict[str, Any]] = []
    for cycle, tc in list_expected_transits(t, t0_bjd, period_d):
        mask = (t >= tc - half) & (t <= tc + half) & np.isfinite(f)
        if mask.sum() < 30:
            continue
        seg = {
            "cycle": cycle,
            "t_expected": tc,
            "time": t[mask].copy(),
            "flux": f[mask].copy(),
            "flux_err": fe[mask].copy() if fe is not None else None,
        }
        out.append(seg)
    return out


def save_transit_segment(seg: Dict[str, Any], out_dir: Path, prefix: str = "cycle") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fp = out_dir / f"{prefix}_{int(seg['cycle']):+06d}.csv"
    t = seg["time"]
    f = seg["flux"]
    fe = seg["flux_err"] if seg["flux_err"] is not None else np.full_like(t, np.nan)
    arr = np.column_stack([t, f, fe])
    np.savetxt(fp, arr, delimiter=",", header="time_bjd_tdb,flux,flux_err", comments="")
    return fp


# ────────────────────────────────────────────────────────────────────────────
# 5. Limb darkening via ExoTETHyS (réutilise core/exotethys_ldc.py)
# ────────────────────────────────────────────────────────────────────────────
# Chaîne de grilles ExoTETHyS : Phoenix peut refuser certains (Teff, logg, [Fe/H]) avec
# « metallicity is out of the range (0.0 - 0.0) » → pas de nœud valide ; on essaie d'autres grilles.
_EXOTETHYS_MODEL_FALLBACK_CHAIN: Tuple[str, ...] = (
    "Phoenix_2018",
    "Stagger_2018",
    "Atlas_2000",
    "Phoenix_2012_13",
    "MPS_Atlas_set1_2023",
)


def _sanitize_stellar_for_exotethys(teff: float, logg: float, mh: float) -> Tuple[float, float, float]:
    """Garde-fous pour éviter Teff/logg/MH absurdes qui vident la grille ExoTETHyS."""
    t = float(teff)
    g = float(logg)
    m = float(mh)
    if not math.isfinite(t) or t < 2000.0 or t > 100_000.0:
        logger.debug("ExoTETHyS : Teff=%s remplacé par 5800 K", teff)
        t = 5800.0
    if not math.isfinite(g) or g <= 0.0 or g > 6.0:
        logger.debug("ExoTETHyS : log g=%s remplacé par 4.5 (cgs)", logg)
        g = 4.5
    if not math.isfinite(m):
        m = 0.0
    m = float(np.clip(m, -2.5, 0.75))
    return t, g, m


def compute_ld_coeffs(
    planet: PlanetParams,
    filter_ui: str = "TESS",
    stellar_models: Optional[Sequence[str]] = None,
) -> np.ndarray:
    """
    Coefficients Claret-4 via ExoTETHyS pour l'étoile décrite par ``planet``.
    Essaie plusieurs grilles stellaires si la première refuse (hors tabulation).
    Fallback : `[0.5, 0.0, 0.0, 0.0]` si ExoTETHyS indisponible ou si toutes les grilles échouent.
    """
    if not EXOTETHYS_AVAILABLE:
        logger.warning("ExoTETHyS indisponible, on utilise un LDC quadratique générique.")
        return np.array([0.5, 0.0, 0.0, 0.0], dtype=float)

    teff, logg, mh = _sanitize_stellar_for_exotethys(planet.teff, planet.logg, planet.feh)
    models: Tuple[str, ...]
    if stellar_models:
        models = tuple(dict.fromkeys(stellar_models))  # ordre conservé, sans doublons
    else:
        models = _EXOTETHYS_MODEL_FALLBACK_CHAIN

    last_exc: Optional[Exception] = None
    for model in models:
        try:
            coeffs = run_exotethys_ldc_claret4(
                filter_ui=filter_ui,
                teff=teff,
                logg=logg,
                mh=mh,
                stellar_model=model,
            )
            if model != models[0]:
                logger.info("ExoTETHyS LDC : grille « %s » a réussi (après échec d'une grille précédente).", model)
            return coeffs
        except Exception as exc:
            last_exc = exc
            logger.debug("ExoTETHyS (%s) échec : %s", model, exc)

    logger.warning(
        "ExoTETHyS : toutes les grilles ont échoué (%s), LDC générique utilisé.",
        last_exc,
    )
    return np.array([0.5, 0.0, 0.0, 0.0], dtype=float)


# ────────────────────────────────────────────────────────────────────────────
# 6. Transit fitter : batman + ultranest
# ────────────────────────────────────────────────────────────────────────────
def _batman_lightcurve(
    t: np.ndarray,
    t0: float,
    period: float,
    rp: float,
    a_rs: float,
    inc: float,
    ecc: float,
    omega: float,
    u_ldc: Sequence[float],
    limb_dark: str = "nonlinear",
    exp_time: float = 0.0,
    supersample_factor: int = 1,
) -> np.ndarray:
    if not BATMAN_AVAILABLE:
        raise RuntimeError("batman-package non installé.")
    p = batman.TransitParams()
    p.t0 = float(t0)
    p.per = float(period)
    p.rp = float(rp)
    p.a = float(a_rs)
    p.inc = float(inc)
    p.ecc = float(ecc)
    p.w = float(omega)
    p.limb_dark = limb_dark
    if limb_dark == "nonlinear":
        u = list(u_ldc)
        while len(u) < 4:
            u.append(0.0)
        p.u = [float(x) for x in u[:4]]
    elif limb_dark == "quadratic":
        u = list(u_ldc)[:2]
        while len(u) < 2:
            u.append(0.0)
        p.u = [float(x) for x in u]
    else:
        p.u = list(u_ldc)

    if exp_time and supersample_factor > 1:
        m = batman.TransitModel(
            p, t, supersample_factor=supersample_factor, exp_time=exp_time / 86400.0
        )
    else:
        m = batman.TransitModel(p, t)
    return m.light_curve(p)


def fit_transit_batman_ultranest(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: Optional[np.ndarray],
    planet: PlanetParams,
    cycle: int = 0,
    filter_ui: str = "TESS",
    ld_coeffs: Optional[Sequence[float]] = None,
    fit_rp: bool = True,
    fit_a_rs: bool = False,
    fit_inc: bool = False,
    detrend_order: int = 1,
    exp_time_s: float = 0.0,
    t0_window_d: float = 0.05,
    min_num_live_points: int = 200,
    dlogz: float = 0.5,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> TransitFitResult:
    """
    Fit bayésien d'un transit unique avec **batman** + **ultranest**.

    Paramètres libres minimum : t0 (BJD_TDB) + ``c0, c1`` du polynôme de baseline.
    Optionnels : rp/Rs (par défaut on), a/Rs, inclinaison.

    Le posterior est marginalisé sur l'incertitude photométrique : si ``flux_err``
    est ``None`` ou tout NaN, on utilise un sigma libre (jeffreys log-uniform).
    """
    if not BATMAN_AVAILABLE:
        raise RuntimeError("batman-package non installé (pip install batman-package).")
    if not ULTRANEST_AVAILABLE:
        raise RuntimeError("ultranest non installé (pip install ultranest).")

    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    n = t.size
    if n < 20:
        raise ValueError(f"Trop peu de points ({n}) pour fitter ce transit.")

    if flux_err is None:
        sigma_obs = None
        fe = np.full(n, np.nan)
    else:
        fe = np.asarray(flux_err, dtype=float)
        ok = np.isfinite(fe) & (fe > 0)
        sigma_obs = float(np.nanmedian(fe[ok])) if ok.any() else None

    # LDC
    if ld_coeffs is None:
        ld_coeffs = compute_ld_coeffs(planet, filter_ui=filter_ui)
    ld = np.asarray(ld_coeffs, dtype=float).ravel()
    if ld.size >= 4:
        ld4 = ld[:4]
        limb_dark = "nonlinear"
    else:
        ld4 = np.concatenate([ld, np.zeros(4 - ld.size)])
        limb_dark = "nonlinear"

    # Indice du cycle attendu :
    tc_expected = planet.t0_bjd + cycle * planet.period_d if planet.period_d > 0 else float(np.median(t))

    # Construction des noms et bornes des paramètres
    param_names: List[str] = ["t0"]
    bounds: List[Tuple[float, float]] = [(tc_expected - t0_window_d, tc_expected + t0_window_d)]
    if fit_rp:
        param_names.append("rp_over_rs")
        bounds.append((max(planet.rp_over_rs * 0.5, 1e-3), planet.rp_over_rs * 1.5 + 0.02))
    if fit_a_rs:
        param_names.append("a_over_rs")
        bounds.append((max(planet.sma_over_rs * 0.7, 1.5), planet.sma_over_rs * 1.3))
    if fit_inc:
        param_names.append("inclination")
        bounds.append((max(planet.inclination_deg - 5.0, 60.0), min(planet.inclination_deg + 5.0, 90.0)))

    # Coefficients polynôme baseline : c0 ≈ 1, c1..cN selon l'ordre
    if detrend_order >= 0:
        param_names.append("c0")
        bounds.append((0.95, 1.05))
    for k in range(1, max(detrend_order, 0) + 1):
        param_names.append(f"c{k}")
        bounds.append((-0.5, 0.5))

    if sigma_obs is None:
        param_names.append("log_sigma")
        bounds.append((-12.0, -2.0))   # exp(-12)..exp(-2) ≈ 6e-6 .. 0.135

    bounds_arr = np.asarray(bounds, dtype=float)
    lo = bounds_arr[:, 0]
    hi = bounds_arr[:, 1]
    span = hi - lo

    def prior_transform(cube: np.ndarray) -> np.ndarray:
        return lo + cube * span

    t_ref = float(t.mean())

    def model(theta: np.ndarray) -> np.ndarray:
        idx = 0
        t0 = float(theta[idx]); idx += 1
        rp = float(theta[idx]) if fit_rp else planet.rp_over_rs
        if fit_rp:
            idx += 1
        a_rs = float(theta[idx]) if fit_a_rs else planet.sma_over_rs
        if fit_a_rs:
            idx += 1
        inc = float(theta[idx]) if fit_inc else planet.inclination_deg
        if fit_inc:
            idx += 1

        c0 = float(theta[idx]); idx += 1
        baseline = np.full_like(t, c0)
        for k in range(1, max(detrend_order, 0) + 1):
            baseline = baseline + float(theta[idx]) * ((t - t_ref) ** k)
            idx += 1
        flux_model = _batman_lightcurve(
            t,
            t0=t0,
            period=planet.period_d,
            rp=rp,
            a_rs=a_rs,
            inc=inc,
            ecc=planet.eccentricity,
            omega=planet.arg_periastron_deg,
            u_ldc=ld4,
            limb_dark=limb_dark,
            exp_time=exp_time_s,
            supersample_factor=7 if exp_time_s > 0 else 1,
        )
        return baseline * flux_model

    def log_likelihood(theta: np.ndarray) -> float:
        try:
            mu = model(theta)
        except Exception as exc:
            logger.debug("batman a planté pour theta=%s : %s", theta, exc)
            return -1e300
        if sigma_obs is None:
            sig = math.exp(float(theta[-1]))
        else:
            sig = sigma_obs
        if not np.all(np.isfinite(mu)):
            return -1e300
        resid = (f - mu) / sig
        return float(-0.5 * np.sum(resid * resid) - n * math.log(sig) - 0.5 * n * math.log(2.0 * math.pi))

    if progress_callback:
        progress_callback(f"Cycle {cycle:+d} : ultranest démarre ({n} pts, {len(param_names)} param.)")

    sampler = ReactiveNestedSampler(param_names, log_likelihood, transform=prior_transform)
    t_start = _time.time()
    result = sampler.run(
        min_num_live_points=min_num_live_points,
        dlogz=dlogz,
        show_status=False,
        viz_callback=None,
    )
    dt = _time.time() - t_start
    if progress_callback:
        progress_callback(f"Cycle {cycle:+d} : terminé en {dt:.1f}s")

    # Résultats : on prend la médiane et les quantiles 16-84
    samples = np.asarray(result["samples"])
    weights = np.asarray(result.get("weighted_samples", {}).get("weights", np.ones(samples.shape[0])))
    if weights.sum() <= 0:
        weights = np.ones(samples.shape[0])
    weights = weights / weights.sum()

    def _wquantile(x: np.ndarray, qs: Sequence[float]) -> np.ndarray:
        order = np.argsort(x)
        cw = np.cumsum(weights[order])
        return np.array([x[order][np.searchsorted(cw, q)] for q in qs])

    medians = np.array([_wquantile(samples[:, k], [0.5])[0] for k in range(samples.shape[1])])
    lowers = np.array([_wquantile(samples[:, k], [0.16])[0] for k in range(samples.shape[1])])
    uppers = np.array([_wquantile(samples[:, k], [0.84])[0] for k in range(samples.shape[1])])

    # Calcul chi2 réduit avec le modèle médian
    mu_best = model(medians)
    if sigma_obs is None:
        sig = math.exp(float(medians[-1]))
    else:
        sig = sigma_obs
    chi2 = float(np.sum(((f - mu_best) / sig) ** 2))
    ndof = max(n - len(param_names), 1)

    return TransitFitResult(
        cycle=int(cycle),
        t0_bjd=float(medians[0]),
        t0_err_minus=float(medians[0] - lowers[0]),
        t0_err_plus=float(uppers[0] - medians[0]),
        rp_over_rs=float(medians[1]) if fit_rp else float(planet.rp_over_rs),
        rp_over_rs_err=float((uppers[1] - lowers[1]) / 2.0) if fit_rp else 0.0,
        chi2_red=chi2 / ndof,
        n_points=int(n),
        detrend_order=int(detrend_order),
        samples_path=None,
        logz=float(result.get("logz", float("nan"))),
        notes=f"params={param_names}",
    )


# ────────────────────────────────────────────────────────────────────────────
# 7. Transit Merger / O-C
# ────────────────────────────────────────────────────────────────────────────
def save_midtimes(results: Sequence[TransitFitResult], out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["ok,cycle,transit_midtime,transit_midtime_min,transit_midtime_plus,rp_over_rs,chi2_red,n_points,notes"]
    for r in results:
        rows.append(
            f"1,{r.cycle},{r.t0_bjd:.8f},{r.t0_err_minus:.8f},"
            f"{r.t0_err_plus:.8f},{r.rp_over_rs:.6f},"
            f"{r.chi2_red:.4f},{r.n_points},{r.notes.replace(',', ';')}"
        )
    out_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return out_path


def load_midtimes(path: Path) -> List[Dict[str, Any]]:
    """Charge un CSV `ok,cycle,transit_midtime,...` produit par save_midtimes."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    rows: List[Dict[str, Any]] = []
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return rows
    header = [c.strip() for c in lines[0].split(",")]
    for ln in lines[1:]:
        parts = [c.strip() for c in ln.split(",")]
        if len(parts) < len(header):
            continue
        row: Dict[str, Any] = {}
        for k, v in zip(header, parts):
            if k in ("ok", "cycle", "n_points"):
                try:
                    row[k] = int(float(v))
                except ValueError:
                    row[k] = 0
            else:
                try:
                    row[k] = float(v)
                except ValueError:
                    row[k] = v
        rows.append(row)
    return rows


def merge_midtimes(
    rows_a: Sequence[Dict[str, Any]],
    rows_b: Sequence[Dict[str, Any]],
    period_d: float,
    clean_threshold_d: float = 0.001,
) -> List[Dict[str, Any]]:
    """Concatène, recalcule cycle, supprime doublons (mêmes mid-times à `clean_threshold_d` près)."""
    merged = list(rows_a) + list(rows_b)
    if period_d > 0:
        ref = min((r["transit_midtime"] for r in merged if r.get("ok", 1)), default=0.0)
        for r in merged:
            r["cycle"] = int(round((r["transit_midtime"] - ref) / period_d))
    merged.sort(key=lambda r: r["transit_midtime"])
    cleaned: List[Dict[str, Any]] = []
    for r in merged:
        if cleaned and abs(r["transit_midtime"] - cleaned[-1]["transit_midtime"]) < clean_threshold_d:
            # Garde la mesure avec la plus petite incertitude minus
            if r.get("transit_midtime_min", 1.0) < cleaned[-1].get("transit_midtime_min", 1.0):
                cleaned[-1] = r
            continue
        cleaned.append(r)
    return cleaned


@dataclass
class TTVFitResult:
    model: str          # "linear" | "sin" | "quadratic" (decay)
    period_d: float
    t0_bjd: float
    extra: Dict[str, float] = field(default_factory=dict)
    chi2_red: float = 0.0
    rms_minutes: float = 0.0
    o_minus_c_d: np.ndarray = field(default_factory=lambda: np.empty(0))
    cycles: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int))
    midtimes_d: np.ndarray = field(default_factory=lambda: np.empty(0))


def fit_ttv(
    midtimes: Sequence[Dict[str, Any]],
    model: str = "linear",
) -> TTVFitResult:
    """
    Fit du diagramme O-C par moindres carrés.

    Modèles supportés :
      * ``linear``    : Tn = T0 + n * P (deux paramètres)
      * ``quadratic`` : Tn = T0 + n * P + 0.5 * dP/dN * n^2 (décroissance orbitale)
      * ``sin``       : Tn = T0 + n*P + A * sin(2π n / N_ttv + phi)
    """
    rows = [r for r in midtimes if r.get("ok", 1)]
    if len(rows) < 3:
        raise ValueError("Au moins 3 mid-times sont nécessaires pour un fit TTV.")

    cycles = np.array([r["cycle"] for r in rows], dtype=float)
    tmid = np.array([r["transit_midtime"] for r in rows], dtype=float)
    tmid_min = np.array([r.get("transit_midtime_min", 0.001) for r in rows], dtype=float)
    tmid_plus = np.array([r.get("transit_midtime_plus", 0.001) for r in rows], dtype=float)
    yerr = np.maximum((tmid_min + tmid_plus) * 0.5, 1e-6)

    # Initialisation linéaire (régression pondérée)
    w = 1.0 / yerr**2
    Sxx = (w * cycles * cycles).sum()
    Sx = (w * cycles).sum()
    S = w.sum()
    Sy = (w * tmid).sum()
    Sxy = (w * cycles * tmid).sum()
    det = S * Sxx - Sx * Sx
    P0 = (S * Sxy - Sx * Sy) / det
    T0 = (Sxx * Sy - Sx * Sxy) / det
    pred = T0 + P0 * cycles
    oc = tmid - pred

    if model == "linear":
        ndof = max(len(rows) - 2, 1)
        chi2_red = float(((oc / yerr) ** 2).sum() / ndof)
        return TTVFitResult(
            model="linear",
            period_d=float(P0),
            t0_bjd=float(T0),
            extra={},
            chi2_red=chi2_red,
            rms_minutes=float(np.sqrt(np.mean(oc**2)) * 24 * 60),
            o_minus_c_d=oc,
            cycles=cycles.astype(int),
            midtimes_d=tmid,
        )

    if model == "quadratic":
        from scipy.optimize import curve_fit

        def f_quad(n, T0_, P_, dPdN):
            return T0_ + P_ * n + 0.5 * dPdN * n * n

        popt, _ = curve_fit(
            f_quad,
            cycles,
            tmid,
            p0=[T0, P0, 0.0],
            sigma=yerr,
            absolute_sigma=True,
        )
        oc2 = tmid - f_quad(cycles, *popt)
        ndof = max(len(rows) - 3, 1)
        chi2_red = float(((oc2 / yerr) ** 2).sum() / ndof)
        return TTVFitResult(
            model="quadratic",
            period_d=float(popt[1]),
            t0_bjd=float(popt[0]),
            extra={"dP_per_cycle": float(popt[2])},
            chi2_red=chi2_red,
            rms_minutes=float(np.sqrt(np.mean(oc2**2)) * 24 * 60),
            o_minus_c_d=oc2,
            cycles=cycles.astype(int),
            midtimes_d=tmid,
        )

    if model == "sin":
        from scipy.optimize import curve_fit

        amp0 = float(np.std(oc))
        n_span = float(max(cycles.max() - cycles.min(), 10.0))

        def f_sin(n, T0_, P_, A, N_ttv, phi):
            return T0_ + P_ * n + A * np.sin(2.0 * np.pi * n / N_ttv + phi)

        try:
            popt, _ = curve_fit(
                f_sin,
                cycles,
                tmid,
                p0=[T0, P0, max(amp0, 1e-4), n_span / 5.0, 0.0],
                sigma=yerr,
                absolute_sigma=True,
                maxfev=20000,
            )
        except Exception as exc:  # solveur peut diverger
            raise RuntimeError(f"Fit sinusoïdal O-C en échec : {exc}") from exc

        oc3 = tmid - f_sin(cycles, *popt)
        ndof = max(len(rows) - 5, 1)
        chi2_red = float(((oc3 / yerr) ** 2).sum() / ndof)
        return TTVFitResult(
            model="sin",
            period_d=float(popt[1]),
            t0_bjd=float(popt[0]),
            extra={
                "amplitude_d": float(popt[2]),
                "amplitude_min": float(popt[2] * 24 * 60),
                "N_ttv_cycles": float(popt[3]),
                "phi": float(popt[4]),
            },
            chi2_red=chi2_red,
            rms_minutes=float(np.sqrt(np.mean(oc3**2)) * 24 * 60),
            o_minus_c_d=oc3,
            cycles=cycles.astype(int),
            midtimes_d=tmid,
        )

    raise ValueError(f"Modèle TTV inconnu : {model!r}")


def save_ttv_result(result: TTVFitResult, out_path: Path) -> Path:
    """Sauvegarde le résultat O-C en JSON dans ``TTVFitterFolder``."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": result.model,
        "period_d": result.period_d,
        "t0_bjd": result.t0_bjd,
        "extra": result.extra,
        "chi2_red": result.chi2_red,
        "rms_minutes": result.rms_minutes,
        "cycles": result.cycles.tolist(),
        "midtimes_d": result.midtimes_d.tolist(),
        "o_minus_c_d": result.o_minus_c_d.tolist(),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def load_ttv_result(path: Path) -> TTVFitResult:
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    return TTVFitResult(
        model=payload["model"],
        period_d=float(payload["period_d"]),
        t0_bjd=float(payload["t0_bjd"]),
        extra={k: float(v) for k, v in (payload.get("extra") or {}).items()},
        chi2_red=float(payload.get("chi2_red", 0.0)),
        rms_minutes=float(payload.get("rms_minutes", 0.0)),
        o_minus_c_d=np.asarray(payload.get("o_minus_c_d", []), dtype=float),
        cycles=np.asarray(payload.get("cycles", []), dtype=int),
        midtimes_d=np.asarray(payload.get("midtimes_d", []), dtype=float),
    )


# ────────────────────────────────────────────────────────────────────────────
# 8. Diagnostic d'environnement
# ────────────────────────────────────────────────────────────────────────────
def diagnostics() -> Dict[str, bool]:
    """Renvoie le statut des dépendances optionnelles ; appelé par l'UI."""
    return {
        "batman": BATMAN_AVAILABLE,
        "ultranest": ULTRANEST_AVAILABLE,
        "lightkurve": LIGHTKURVE_AVAILABLE,
        "exotethys": EXOTETHYS_AVAILABLE,
    }
