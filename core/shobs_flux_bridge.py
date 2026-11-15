"""Pont NPOAP ↔ SHOBS-FLUX : lancement et import des profils caméra ``~/.shobs``.

SHOBS-FLUX (GPL-3) vit dans ``external_apps/shobs_flux/``. Les profils mesurés
sont lus depuis le dossier de données SHOBS partagé (``~/.shobs/cameras/``) et
injectés dans ``config.EQUIPMENT_OBSERVATION`` / ``config.json``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Clés profil SHOBS → clés équipement NPOAP
_PROFILE_TO_EQUIPMENT = {
    "gain_e_per_adu": "camera_gain_e_per_adu",
    "read_noise_e": "camera_readnoise_e",
    "dark_current_e_per_px_s": "camera_dark_e_per_s",
    "linear_limit_adu": "camera_linear_limit_adu",
    "saturation_adu": "camera_saturation_adu",
}

CAMERA_FORMAT = "shobs-camera-profile"


def npoap_root() -> Path:
    return Path(__file__).resolve().parent.parent


def shobs_flux_dir() -> Path:
    return npoap_root() / "external_apps" / "shobs_flux"


def shobs_flux_app() -> Path:
    return shobs_flux_dir() / "flux_app.py"


def is_installed() -> bool:
    return shobs_flux_app().is_file()


def shobs_data_dir() -> Path:
    env = (os.environ.get("SHOBS_DATA_HOME") or "").strip()
    if env:
        return Path(env)
    return Path.home() / ".shobs"


def cameras_dir() -> Path:
    return shobs_data_dir() / "cameras"


def _finite(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _record_value(rec: Any) -> float | None:
    if not isinstance(rec, dict):
        return _finite(rec)
    if rec.get("source") == "none":
        return None
    return _finite(rec.get("value"))


@dataclass(frozen=True)
class CameraProfileSummary:
    profile_id: str
    path: Path
    camera_name: str
    gain_setting: float | None
    offset: float | None
    binning: int | None
    gain_e_per_adu: float | None
    read_noise_e: float | None
    dark_current_e_per_s: float | None
    linear_limit_adu: float | None
    saturation_adu: float | None
    sources: dict[str, str]

    def label(self) -> str:
        g = f"g{self.gain_setting:g}" if self.gain_setting is not None else "g?"
        o = f"o{self.offset:g}" if self.offset is not None else "o?"
        b = f"bin{self.binning}" if self.binning is not None else "bin?"
        gain = f"{self.gain_e_per_adu:.4g} e-/ADU" if self.gain_e_per_adu is not None else "gain —"
        return f"{self.camera_name} · {g}/{o}/{b} · {gain}"


def load_camera_profile(path: Path | str) -> dict:
    p = Path(path)
    with open(p, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        raise ValueError(f"Profil invalide (pas un objet JSON) : {p}")
    if doc.get("format") != CAMERA_FORMAT:
        raise ValueError(f"Format inattendu {doc.get('format')!r} (attendu {CAMERA_FORMAT})")
    return doc


def summarize_camera_doc(doc: dict, path: Path | None = None) -> CameraProfileSummary:
    cam = doc.get("camera") if isinstance(doc.get("camera"), dict) else {}
    mode = doc.get("mode") if isinstance(doc.get("mode"), dict) else {}
    vals = doc.get("values") if isinstance(doc.get("values"), dict) else {}
    sources: dict[str, str] = {}
    extracted: dict[str, float | None] = {}
    for shobs_key, _eq_key in _PROFILE_TO_EQUIPMENT.items():
        rec = vals.get(shobs_key)
        extracted[shobs_key] = _record_value(rec)
        if isinstance(rec, dict) and rec.get("source"):
            sources[shobs_key] = str(rec.get("source"))
    pid = str(doc.get("profile_id") or (path.stem if path else "unknown"))
    binning = mode.get("binning")
    try:
        bin_i = int(binning) if binning is not None else None
    except (TypeError, ValueError):
        bin_i = None
    return CameraProfileSummary(
        profile_id=pid,
        path=path or Path(),
        camera_name=str(cam.get("instrume") or pid),
        gain_setting=_finite(mode.get("gain_setting")),
        offset=_finite(mode.get("offset")),
        binning=bin_i,
        gain_e_per_adu=extracted.get("gain_e_per_adu"),
        read_noise_e=extracted.get("read_noise_e"),
        dark_current_e_per_s=extracted.get("dark_current_e_per_px_s"),
        linear_limit_adu=extracted.get("linear_limit_adu"),
        saturation_adu=extracted.get("saturation_adu"),
        sources=sources,
    )


def list_camera_profiles() -> list[CameraProfileSummary]:
    d = cameras_dir()
    if not d.is_dir():
        return []
    out: list[CameraProfileSummary] = []
    for path in sorted(d.glob("*.json")):
        try:
            doc = load_camera_profile(path)
            out.append(summarize_camera_doc(doc, path))
        except Exception:
            continue
    return out


def equipment_from_summary(summary: CameraProfileSummary) -> dict[str, Any]:
    """Dictionnaire ``equipment`` partiel prêt pour ``persist_camera_equipment``."""
    eq: dict[str, Any] = {
        "shobs_camera_profile_id": summary.profile_id,
        "camera": summary.camera_name,
    }
    mapping = {
        "camera_gain_e_per_adu": summary.gain_e_per_adu,
        "camera_readnoise_e": summary.read_noise_e,
        "camera_dark_e_per_s": summary.dark_current_e_per_s,
        "camera_linear_limit_adu": summary.linear_limit_adu,
        "camera_saturation_adu": summary.saturation_adu,
    }
    for k, v in mapping.items():
        if v is not None:
            eq[k] = v
    if summary.binning is not None and summary.binning >= 1:
        eq["binning"] = summary.binning
    return eq


def apply_camera_profile_to_npoap(summary: CameraProfileSummary) -> dict[str, Any]:
    """Persiste le profil choisi dans la config NPOAP ; retourne le dict equipment écrit."""
    from config import persist_camera_equipment

    eq = equipment_from_summary(summary)
    persist_camera_equipment(eq)
    return eq


def hops_snippet_from_summary(summary: CameraProfileSummary, *, telescope: str = "") -> str:
    """Bloc texte prêt à coller dans HOPS (champs usuels)."""
    lines = [
        "=== HOPS (depuis profil SHOBS-FLUX) ===",
        f"Camera Name: {summary.camera_name}",
    ]
    if telescope:
        lines.append(f"Telescope Name: {telescope}")
    if summary.gain_e_per_adu is not None:
        src = summary.sources.get("gain_e_per_adu", "")
        lines.append(
            f"Camera gain in e/ADU: {summary.gain_e_per_adu:.6g}"
            + (f"  # {src}" if src else "")
        )
    sat_share = None
    if (
        summary.linear_limit_adu is not None
        and summary.saturation_adu is not None
        and summary.saturation_adu > 0
    ):
        # HOPS demande une fraction relative à sa limite 65535 ; on donne aussi la limite linéaire.
        sat_share = min(1.0, float(summary.linear_limit_adu) / 65535.0)
        lines.append(
            f"Saturation limit (rel. to 65535, from linear limit): {sat_share:.4f}"
        )
    elif summary.saturation_adu is not None and summary.saturation_adu > 0:
        sat_share = min(1.0, float(summary.saturation_adu) / 65535.0)
        lines.append(f"Saturation limit (rel. to 65535): {sat_share:.4f}")
    if summary.binning is not None:
        # HOPS : binning logiciel 2 pour OSC couleur souvent ; ici on reporte le bin capteur.
        lines.append(f"Binning (camera): {summary.binning}")
    if summary.read_noise_e is not None:
        lines.append(f"# Read noise (e-): {summary.read_noise_e:.4g} (NPOAP/SHOBS, pas un champ HOPS)")
    if summary.dark_current_e_per_s is not None:
        lines.append(
            f"# Dark current (e-/px/s): {summary.dark_current_e_per_s:.4g} (NPOAP/SHOBS)"
        )
    lines.append(f"# Profil: {summary.profile_id}")
    return "\n".join(lines) + "\n"


def launch_shobs_flux() -> subprocess.Popen:
    """Démarre SHOBS-FLUX dans un processus séparé (même interpréteur Python)."""
    if not is_installed():
        raise FileNotFoundError(
            f"SHOBS-FLUX introuvable : {shobs_flux_app()}"
        )
    app = shobs_flux_app()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(
        [sys.executable, str(app)],
        cwd=str(app.parent),
        creationflags=creationflags,
    )


SYSTEM_FORMAT = "shobs-system-profile"


@dataclass(frozen=True)
class SystemProfileSummary:
    profile_id: str
    path: Path
    telescope_name: str
    camera_profile: str
    focal_mm: float | None
    bands: tuple[str, ...]
    zero_point: float | None
    extinction_k: float | None
    seeing_fwhm_arcsec: float | None

    def label(self) -> str:
        zp = f"ZP={self.zero_point:.3g}" if self.zero_point is not None else "ZP —"
        k = f"k={self.extinction_k:.3g}" if self.extinction_k is not None else "k —"
        bands = ",".join(self.bands) if self.bands else "?"
        return f"{self.telescope_name} · {bands} · {zp} · {k}"


def load_system_profile(path: Path | str) -> dict:
    p = Path(path)
    with open(p, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("format") != SYSTEM_FORMAT:
        raise ValueError(f"Profil système invalide : {p}")
    return doc


def summarize_system_doc(doc: dict, path: Path | None = None) -> SystemProfileSummary:
    tel = doc.get("telescope") if isinstance(doc.get("telescope"), dict) else {}
    bands_map = doc.get("bands") if isinstance(doc.get("bands"), dict) else {}
    band_names = tuple(sorted(bands_map.keys()))
    # bande préférée : celle avec un ZP measured
    zp = k = seeing = None
    for _band, slot in bands_map.items():
        if not isinstance(slot, dict):
            continue
        zv = _record_value(slot.get("zero_point"))
        if zv is not None and zp is None:
            zp = zv
            k = _record_value(slot.get("extinction_k"))
            seeing = _record_value(slot.get("fwhm_in_focus"))
    return SystemProfileSummary(
        profile_id=str(doc.get("profile_id") or (path.stem if path else "unknown")),
        path=path or Path(),
        telescope_name=str(tel.get("name") or doc.get("profile_id") or "Telescope"),
        camera_profile=str(doc.get("camera_profile") or ""),
        focal_mm=_finite(tel.get("focal_mm")),
        bands=band_names,
        zero_point=zp,
        extinction_k=k,
        seeing_fwhm_arcsec=seeing,
    )


def list_system_profiles() -> list[SystemProfileSummary]:
    d = shobs_data_dir() / "systems"
    if not d.is_dir():
        return []
    out: list[SystemProfileSummary] = []
    for path in sorted(d.glob("*.json")):
        try:
            doc = load_system_profile(path)
            out.append(summarize_system_doc(doc, path))
        except Exception:
            continue
    return out


def apply_system_profile_to_npoap(summary: SystemProfileSummary) -> dict[str, Any]:
    """Importe un profil système SHOBS → bloc ``onsky`` de config.json."""
    from config import persist_onsky_calibration
    from core.shobs_flux_analysis import onsky_from_system_profile

    doc = load_system_profile(summary.path)
    payload = onsky_from_system_profile(doc)
    persist_onsky_calibration(payload)
    return payload


def status_text() -> str:
    if not is_installed():
        return "SHOBS-FLUX non installé (external_apps/shobs_flux manquant)."
    n = len(list_camera_profiles())
    ns = len(list_system_profiles())
    data = shobs_data_dir()
    return f"SHOBS-FLUX prêt · {n} caméra(s), {ns} système(s) dans {data}"
