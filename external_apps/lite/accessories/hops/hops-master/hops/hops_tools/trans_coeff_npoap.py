"""
Chargement des coefficients de transformation NPOAP (répertoire utilisateur
``~/.npoap/Coeftransformation``), aligné sur ``core.transformation_coefficients``.

Si HOPS est exécuté depuis l'arborescence du dépôt NPOAP, les fonctions officielles
sont importées. Sinon, lecture CSV minimale (même conventions de noms de fichiers).
"""

from __future__ import annotations

import csv
import math
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np

__all__ = [
    "apply_transformation_to_inst_mag",
    "delta_mag_from_flux_ratio",
    "effective_transformation_slope",
    "load_transformation_coeff_pack",
    "npoap_transformation_dir",
]


def npoap_transformation_dir() -> Path:
    d = Path.home() / ".npoap" / "Coeftransformation"
    return d


def apply_transformation_to_inst_mag(m_inst: float, slope: float, intercept: float) -> float:
    """``m_cat ≈ slope * m_inst + intercept`` (m_inst = magnitude instrumentale, ex. -2.5 log10 flux)."""
    return float(slope) * float(m_inst) + float(intercept)


def effective_transformation_slope(log) -> float:
    """
    Pente ``a`` appliquée à ``Δ(-2.5 log10(F))`` ; si les coefficients NPOAP ne sont pas activés, retourne 1.
    L'ordonnée ``b`` s'annule pour une différence entre deux magnitudes instrumentales.
    """
    try:
        if not bool(log.get_param("apply_transformation_coefficients")):
            return 1.0
        a = float(log.get_param("transformation_slope"))
        return float(a) if math.isfinite(a) else 1.0
    except Exception:
        return 1.0


def delta_mag_from_flux_ratio(
    f_num: np.ndarray,
    f_den: np.ndarray,
    sig_num: np.ndarray,
    sig_den: np.ndarray,
    slope: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Différentiel de magnitude aligné sur le rapport de flux HOPS :
    ``Delta m = slope * (-2.5 * log10(F_num / F_den))``.

    Même dénominateur que le rapport de flux cible / somme (ou slices comparaisons) : on obtient
    l'équivalent d'une différence de magnitudes instrumentales, multipliée par ``slope`` ; les
    ordonnées ``b`` d'un modèle ``a*m_inst+b`` s'annulent pour une telle différence.

    (Pour des combinaisons non linéaires du type magnitude de la somme des flux, ce n'est pas
    identique à la moyenne des magnitudes par étoile ; ici on reste dans le domaine du rapport
    de flux déjà utilisé par HOPS.)
    """
    tiny = np.float64(1e-30)
    fn = np.maximum(np.asarray(f_num, dtype=np.float64), tiny)
    fd = np.maximum(np.asarray(f_den, dtype=np.float64), tiny)
    k = np.float64(-2.5 / np.log(10.0))
    dm = np.float64(slope) * k * (np.log10(fn) - np.log10(fd))
    sig_inst = np.abs(k) * np.sqrt(
        (np.asarray(sig_num, dtype=np.float64) / fn) ** 2
        + (np.asarray(sig_den, dtype=np.float64) / fd) ** 2
    )
    sig = np.abs(np.float64(slope)) * sig_inst
    return dm, sig


def _repo_with_core() -> Optional[Path]:
    here = Path(__file__).resolve()
    for d in here.parents:
        if (d / "core" / "transformation_coefficients.py").is_file():
            return d
    return None


def _safe_coeff_csv_token(s: str) -> str:
    t = re.sub(r"[^\w.\-]+", "_", str(s), flags=re.UNICODE).strip("_")
    return t[:80] if t else "unknown"


def _norm_obs_filter(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())


def _filters_match(obs_ui: str, obs_journal: str) -> bool:
    a = _norm_obs_filter(obs_ui)
    b = _norm_obs_filter(obs_journal)
    if not a or not b:
        return False
    return a == b or a in b or b in a


_REF_LABELS = {
    "gaia_g": "Gaia G",
    "gaia_bp": "Gaia BP",
    "gaia_rp": "Gaia RP",
    "johnson_b": "Johnson B (APASS DR9)",
    "johnson_v": "Johnson V (APASS DR9)",
    "johnson_rc": "Johnson Rc (APASS g′r′ → Lupton 2005)",
}


def _ref_band_label_for_id(ref_band_id: str) -> str:
    return _REF_LABELS.get(ref_band_id, str(ref_band_id))


def _ref_band_id_for_observer_filter(obs_filter: str) -> str:
    n = _norm_obs_filter(obs_filter)
    if not n:
        return "gaia_g"
    if "rp" in n or n in ("grp", "g_rp", "gaia_rp"):
        return "gaia_rp"
    if "bp" in n or n in ("gbp", "g_bp", "gaia_bp"):
        return "gaia_bp"
    if n in (
        "johnson_rc",
        "johnsonr",
        "rc",
        "r_c",
        "cousinsr",
        "cousins_rc",
        "r",
        "rcousins",
    ):
        return "johnson_rc"
    if n in ("johnson_v", "johnsonv", "v"):
        return "johnson_v"
    if n in ("johnson_b", "johnsonb", "b"):
        return "johnson_b"
    if n in ("gaia_g", "gaiag", "gg", "g", "gaia"):
        return "gaia_g"
    return "gaia_g"


def _pair_csv_path(obs_filter: str, ref_band_id: str) -> Path:
    root = npoap_transformation_dir()
    obs_t = _safe_coeff_csv_token(obs_filter)
    ref_t = _safe_coeff_csv_token(_ref_band_label_for_id(ref_band_id))
    return root / f"{obs_t}__{ref_t}.csv"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _parse_row_coeff(row: dict[str, str], ref_band_id: str, obs_filter: str):
    rid = (row.get("ref_band_id") or "").strip()
    if rid and rid != ref_band_id:
        return None
    jf = row.get("obs_filter") or ""
    if jf and not _filters_match(obs_filter, jf):
        return None
    try:
        a = float(row["slope"])
        b = float(row["intercept"])
    except (KeyError, ValueError, TypeError):
        return None
    if not (math.isfinite(a) and math.isfinite(b)):
        return None
    ts = (row.get("timestamp_utc") or "")[:19]
    rms = row.get("rms", "")
    desc = f"{ts}, RMS={rms}"
    return a, b, desc


def _load_standalone(obs_filter: str, ref_band_id: str):
    obs_filter = (obs_filter or "").strip()
    if not obs_filter:
        return None
    pp = _pair_csv_path(obs_filter, ref_band_id)
    for row in reversed(_read_csv_rows(pp)):
        r = _parse_row_coeff(row, ref_band_id, obs_filter)
        if r is None:
            continue
        a, b, desc = r
        return {
            "slope": a,
            "intercept": b,
            "summary": f"{pp.name} @ {desc}",
            "ref_band_id": ref_band_id,
            "source": str(pp),
        }
    jp = npoap_transformation_dir() / "coefficients_journal.csv"
    rows = list(reversed(_read_csv_rows(jp)))
    for row in rows:
        rid = (row.get("ref_band_id") or "").strip()
        if rid != ref_band_id:
            continue
        jf = row.get("obs_filter") or ""
        if not _filters_match(obs_filter, jf):
            continue
        r = _parse_row_coeff(row, ref_band_id, obs_filter)
        if r is None:
            continue
        a, b, desc = r
        return {
            "slope": a,
            "intercept": b,
            "summary": f"{jp.name} @ {desc}",
            "ref_band_id": ref_band_id,
            "source": str(jp),
        }
    return None


def load_transformation_coeff_pack(obs_filter: str) -> dict | None:
    """
    Retourne un dict ``slope``, ``intercept``, ``summary``, ``ref_band_id``, ``source``
    ou ``None`` si aucun jeu de coefficients n'est trouvé pour ce filtre.
    """
    obs_filter = (obs_filter or "").strip()
    if not obs_filter:
        return None

    root = _repo_with_core()
    if root is not None:
        rpath = str(root)
        if rpath not in sys.path:
            sys.path.insert(0, rpath)
        try:
            from core.transformation_coefficients import (
                load_latest_transformation_coefficient,
                ref_band_id_for_observer_filter,
            )

            ref_id = ref_band_id_for_observer_filter(obs_filter)
            out = load_latest_transformation_coefficient(obs_filter, ref_band_id=ref_id)
            if out is None:
                return None
            a, b, desc, _mag_std = out
            return {
                "slope": float(a),
                "intercept": float(b),
                "summary": desc,
                "ref_band_id": ref_id,
                "source": "npoap.core",
            }
        except Exception:
            pass

    ref_id = _ref_band_id_for_observer_filter(obs_filter)
    return _load_standalone(obs_filter, ref_id)
