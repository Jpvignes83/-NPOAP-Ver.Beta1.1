import os
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# Observatoire (valeurs par défaut – modifiables via HomeTab)
# ──────────────────────────────────────────────────────────────
OBSERVATORY = {
    "name": "Deep Sky Chile",
    "lat": -30.52,   
    "lon": -70.82,
    "elev": 1710.0,     # mètres
    "timezone": "Santiago, Chili",
}

# ──────────────────────────────────────────────────────────────
# Chemins de sortie
# ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = BASE_DIR / "output"
PHOTOMETRY_DIR = OUTPUT_DIR / "photometry"
CALIBRATED_DIR = OUTPUT_DIR / "calibrated"
ASTROMETRY_DIR = OUTPUT_DIR / "astrometry"

# ──────────────────────────────────────────────────────────────
# Catalogues (GLADE+ HDF5, etc.) — par défaut %USERPROFILE%\.npoap\catalogues
# Fichier Gladeplus.h5 : copie depuis la distribution dans ce dossier (ou regénération dev : scripts/download_and_convert_glade_catalog.py + requirements_glade_build.txt).
# ──────────────────────────────────────────────────────────────
CATALOGUES_DATA_DIR = Path.home() / ".npoap" / "catalogues"
GLADE_CATALOG_H5_PATH = CATALOGUES_DATA_DIR / "Gladeplus.h5"

# ──────────────────────────────────────────────────────────────
# Paramètres photométrie (aperture par défaut)
# ──────────────────────────────────────────────────────────────
PHOTOMETRY_DEFAULTS = {
    "aperture_radius_fwhm": 1.3,
    "inner_annulus_fwhm": 1.8,
    "outer_annulus_fwhm": 2.5,
    "sigma_clip": 3.0,
    "fwhm_kernel_size": 21,
    "gaia_max_magnitude": 14.0,
    "gaia_cone_radius_arcmin": 15.0,
}

# ──────────────────────────────────────────────────────────────
# KBMOD via WSL (détection Synthetic Tracking)
# ──────────────────────────────────────────────────────────────
# Commande Python sous WSL pour exécuter scripts/kbmod_wsl_detect.py.
# Doit être le même interpréteur que celui où KBMOD est installé (install_kbmod_wsl.bat = conda astroenv par défaut).
KBMOD_WSL_PYTHON = "/home/docke/miniconda3/envs/astroenv/bin/python3"

# ──────────────────────────────────────────────────────────────
# Astrometry.net (clé API locale)
# ──────────────────────────────────────────────────────────────
ASTROMETRY_API_KEY_FILE = Path.home() / ".astrometry_api_key"

# ──────────────────────────────────────────────────────────────


EQUIPMENT_OBSERVATION = {
    "obs_code": "VJEB",           # Code observateur AAVSO (5 caractères max)
    "camera": "CCD",             # Nom de la caméra
    "binning": "1x1",         # Binning (1x1, 2x2, 3x3, 4x4)
    "delim": "tab",             # Délimiteur pour rapports (, ; | : ! / ? ou tab)
    "telescope_diameter_mm": 500.0,  # Diamètre du télescope (mm) – configurable via Accueil
    "focal_length_mm": 1939,  # Focale en millimètres
    "sensor_width_mm": 0.0,   # Largeur capteur (mm) – configurable via Accueil
    "sensor_height_mm": 0.0,  # Hauteur capteur (mm) – configurable via Accueil
    "pixel_size_um": 3.76,  # Taille du pixel en micromètres
    "pixel_scale_arcsec": 0.3800,  # Échelle pixel calculée (arcsec/pixel)
    # Calibration caméra (PTC NPOAP / import profil SHOBS-FLUX ; persisté dans config.json).
    # Si défini, prioritaire sur l'en-tête FITS brut pour la variance / GAIN / RDNOISE.
    "camera_gain_e_per_adu": None,
    "camera_readnoise_e": None,          # e-/pixel
    "camera_dark_e_per_s": None,         # e-/pixel/s
    "camera_linear_limit_adu": None,     # ADU (limite linéaire sûre)
    "camera_saturation_adu": None,       # ADU
    "shobs_camera_profile_id": None,     # id profil ~/.shobs/cameras/
}

# Clés equipment caméra persistées dans config.json
CAMERA_EQUIPMENT_KEYS = (
    "camera_gain_e_per_adu",
    "camera_readnoise_e",
    "camera_dark_e_per_s",
    "camera_linear_limit_adu",
    "camera_saturation_adu",
    "shobs_camera_profile_id",
)

# Caractérisation on-sky (SHOBS-FLUX Sky / import profil système) → config.json bloc ``onsky``
ONSKY_CALIBRATION = {
    "band": None,                      # bande principale (ex. TG, V, CV)
    "zero_point": None,                # mag pour 1 e-/s à airmass 1
    "extinction_k": None,              # mag/airmass
    "seeing_fwhm_arcsec": None,
    "sky_mag_arcsec2": None,
    "scintillation_cy": None,
    "overhead_s": None,
    "shobs_system_profile_id": None,
    "bands": {},                       # {band: {zero_point, extinction_k, ...}}
}

ONSKY_NUMERIC_KEYS = (
    "zero_point",
    "extinction_k",
    "seeing_fwhm_arcsec",
    "sky_mag_arcsec2",
    "scintillation_cy",
    "overhead_s",
)

# ──────────────────────────────────────────────────────────────
# Affiliations (modifiables via HomeTab)
# ──────────────────────────────────────────────────────────────
AFFILIATIONS = []  # Liste de dicts: [{"text": "...", "selected": bool}]

# ──────────────────────────────────────────────────────────────
# Astro-COLIBRI (recherche transitoires, cone search)
# UID optionnel : inscription gratuite sur astro-colibri.com, 100 req/jour
# Renseignez votre identifiant ci-dessous (ou via « Sauvegarder » dans l’UI).
# ──────────────────────────────────────────────────────────────
ASTRO_COLIBRI_UID = 'WRwmrDmXDQc6yUVCCQSUBD63gtk2'


def persist_astro_colibri_uid(uid: str) -> None:
    """
    Enregistre l’UID Astro-COLIBRI dans ce fichier (config.py) et met à jour la valeur en mémoire.
    Utilisé par l’onglet transitoires et l’onglet observations de la nuit.
    """
    import re
    import sys

    s = (uid or "").strip()
    mod = sys.modules[__name__]
    mod.ASTRO_COLIBRI_UID = s

    config_path = Path(__file__).resolve()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        pattern = r"^(ASTRO_COLIBRI_UID\s*=\s*).*$"
        replacement = r"\g<1>" + repr(s)
        new_content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
        if new_content != content:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(new_content)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# TNS (Transient Name Server) API Configuration
# User-Agent: "user" (compte utilisateur) ou "bot" (compte bot)
# ──────────────────────────────────────────────────────────────
# Chaque utilisateur doit saisir et sauvegarder son TNS ID / nom ; laisser vides dans la distribution.
TNS_CONFIG = {
    "tns_marker_type": "user",   # "user" | "bot"
    "tns_id": "",                # TNS ID utilisateur (à remplir par l'utilisateur)
    "tns_name": "",              # Nom utilisateur TNS (à remplir par l'utilisateur)
    "bot_id": "",                # ID du bot (pour type "bot")
    "api_key": "",               # Clé API TNS (à configurer via GUI)
    "bot_name": "NPOAP",
    "use_sandbox": False,
}


def _positive_float(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _nonneg_float(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def get_camera_gain_e_per_adu():
    """
    Retourne le gain caméra (e-/ADU) issu de la PTC / SHOBS / config.json, ou None.
    """
    return _positive_float(EQUIPMENT_OBSERVATION.get("camera_gain_e_per_adu"))


def get_camera_readnoise_e():
    """Bruit de lecture (e-/pixel) depuis config.json / profil SHOBS, ou None."""
    return _nonneg_float(EQUIPMENT_OBSERVATION.get("camera_readnoise_e"))


def get_camera_dark_e_per_s():
    """Courant d'obscurité (e-/pixel/s) depuis config.json / profil SHOBS, ou None."""
    return _nonneg_float(EQUIPMENT_OBSERVATION.get("camera_dark_e_per_s"))


def get_camera_linear_limit_adu():
    """Limite linéaire (ADU) depuis config.json / profil SHOBS, ou None."""
    return _positive_float(EQUIPMENT_OBSERVATION.get("camera_linear_limit_adu"))


def get_camera_saturation_adu():
    """Saturation (ADU) depuis config.json / profil SHOBS, ou None."""
    return _positive_float(EQUIPMENT_OBSERVATION.get("camera_saturation_adu"))


def refresh_camera_equipment_from_config_json() -> None:
    """
    Relit ``config.json`` (bloc equipment) et met à jour les constantes caméra en mémoire.
    Appelé au chargement Accueil et avant la calibration.
    """
    import json

    path = BASE_DIR / "config.json"
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        eq = data.get("equipment") or {}
        if not isinstance(eq, dict):
            return
        EQUIPMENT_OBSERVATION["camera_gain_e_per_adu"] = _positive_float(eq.get("camera_gain_e_per_adu"))
        EQUIPMENT_OBSERVATION["camera_readnoise_e"] = _nonneg_float(eq.get("camera_readnoise_e"))
        EQUIPMENT_OBSERVATION["camera_dark_e_per_s"] = _nonneg_float(eq.get("camera_dark_e_per_s"))
        EQUIPMENT_OBSERVATION["camera_linear_limit_adu"] = _positive_float(eq.get("camera_linear_limit_adu"))
        EQUIPMENT_OBSERVATION["camera_saturation_adu"] = _positive_float(eq.get("camera_saturation_adu"))
        pid = eq.get("shobs_camera_profile_id")
        EQUIPMENT_OBSERVATION["shobs_camera_profile_id"] = (
            str(pid).strip() if pid is not None and str(pid).strip() else None
        )
        if "camera" in eq and str(eq.get("camera") or "").strip():
            EQUIPMENT_OBSERVATION["camera"] = str(eq.get("camera")).strip()
        if "binning" in eq and eq.get("binning") is not None:
            try:
                b = int(eq.get("binning"))
                if b >= 1:
                    EQUIPMENT_OBSERVATION["binning"] = f"{b}x{b}"
            except (TypeError, ValueError):
                pass
    except Exception:
        pass


def refresh_camera_gain_from_config_json() -> None:
    """Alias conservé : recharge caméra + on-sky depuis config.json."""
    refresh_camera_equipment_from_config_json()
    refresh_onsky_from_config_json()


def persist_camera_equipment(updates: dict) -> None:
    """
    Fusionne des champs caméra dans ``config.json`` (bloc equipment) et en mémoire.
    Passez une valeur ``None`` pour retirer une clé numérique connue.
    """
    import json

    if not isinstance(updates, dict) or not updates:
        return

    path = BASE_DIR / "config.json"
    data: dict = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    eq = data.get("equipment")
    if not isinstance(eq, dict):
        eq = {}

    for key, raw in updates.items():
        if key == "camera":
            if raw is None or str(raw).strip() == "":
                continue
            EQUIPMENT_OBSERVATION["camera"] = str(raw).strip()
            eq["camera"] = EQUIPMENT_OBSERVATION["camera"]
            continue
        if key == "binning":
            try:
                b = int(raw)
            except (TypeError, ValueError):
                continue
            if b < 1:
                continue
            EQUIPMENT_OBSERVATION["binning"] = f"{b}x{b}"
            eq["binning"] = b
            continue
        if key == "shobs_camera_profile_id":
            if raw is None or str(raw).strip() == "":
                EQUIPMENT_OBSERVATION["shobs_camera_profile_id"] = None
                eq.pop("shobs_camera_profile_id", None)
            else:
                EQUIPMENT_OBSERVATION["shobs_camera_profile_id"] = str(raw).strip()
                eq["shobs_camera_profile_id"] = EQUIPMENT_OBSERVATION["shobs_camera_profile_id"]
            continue
        if key not in CAMERA_EQUIPMENT_KEYS:
            continue
        if key == "camera_gain_e_per_adu":
            v = _positive_float(raw)
        elif key in ("camera_linear_limit_adu", "camera_saturation_adu"):
            v = _positive_float(raw)
        elif key in ("camera_readnoise_e", "camera_dark_e_per_s"):
            v = _nonneg_float(raw)
        else:
            v = None if raw is None else str(raw)
        EQUIPMENT_OBSERVATION[key] = v
        if v is None:
            eq.pop(key, None)
        else:
            eq[key] = v

    data["equipment"] = eq
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def persist_camera_gain_e_per_adu(gain_e_per_adu) -> None:
    """
    Enregistre le gain (e-/ADU) dans ``config.json`` (merge) et en mémoire.
    Passez None pour retirer la surcharge (retour à l'en-tête FITS brut).
    """
    persist_camera_equipment({"camera_gain_e_per_adu": gain_e_per_adu})


def get_extinction_k(band: str | None = None):
    """Extinction (mag/airmass) on-sky / config, ou None."""
    if band:
        b = (ONSKY_CALIBRATION.get("bands") or {}).get(str(band).upper()) or {}
        v = _nonneg_float(b.get("extinction_k"))
        if v is not None:
            return v
    return _nonneg_float(ONSKY_CALIBRATION.get("extinction_k"))


def get_zero_point(band: str | None = None):
    """Zero point (mag pour 1 e-/s à X=1) on-sky / config, ou None."""
    if band:
        b = (ONSKY_CALIBRATION.get("bands") or {}).get(str(band).upper()) or {}
        v = _finite_any(b.get("zero_point"))
        if v is not None:
            return v
    return _finite_any(ONSKY_CALIBRATION.get("zero_point"))


def get_seeing_fwhm_arcsec():
    return _positive_float(ONSKY_CALIBRATION.get("seeing_fwhm_arcsec"))


def _finite_any(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def refresh_onsky_from_config_json() -> None:
    """Relit le bloc ``onsky`` de config.json en mémoire."""
    import json

    path = BASE_DIR / "config.json"
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        block = data.get("onsky") or {}
        if not isinstance(block, dict):
            return
        for key in ONSKY_NUMERIC_KEYS:
            ONSKY_CALIBRATION[key] = _finite_any(block.get(key))
        band = block.get("band")
        ONSKY_CALIBRATION["band"] = str(band).strip().upper() if band else None
        pid = block.get("shobs_system_profile_id")
        ONSKY_CALIBRATION["shobs_system_profile_id"] = (
            str(pid).strip() if pid is not None and str(pid).strip() else None
        )
        bands = block.get("bands")
        ONSKY_CALIBRATION["bands"] = bands if isinstance(bands, dict) else {}
    except Exception:
        pass


def persist_onsky_calibration(updates: dict) -> None:
    """Fusionne des champs on-sky dans ``config.json`` (bloc ``onsky``) et en mémoire."""
    import json

    if not isinstance(updates, dict) or not updates:
        return

    path = BASE_DIR / "config.json"
    data: dict = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    block = data.get("onsky")
    if not isinstance(block, dict):
        block = {}

    if "bands" in updates and isinstance(updates["bands"], dict):
        ONSKY_CALIBRATION["bands"] = dict(updates["bands"])
        block["bands"] = ONSKY_CALIBRATION["bands"]

    if "band" in updates:
        b = updates["band"]
        ONSKY_CALIBRATION["band"] = str(b).strip().upper() if b else None
        if ONSKY_CALIBRATION["band"]:
            block["band"] = ONSKY_CALIBRATION["band"]
        else:
            block.pop("band", None)

    if "shobs_system_profile_id" in updates:
        pid = updates["shobs_system_profile_id"]
        if pid is None or str(pid).strip() == "":
            ONSKY_CALIBRATION["shobs_system_profile_id"] = None
            block.pop("shobs_system_profile_id", None)
        else:
            ONSKY_CALIBRATION["shobs_system_profile_id"] = str(pid).strip()
            block["shobs_system_profile_id"] = ONSKY_CALIBRATION["shobs_system_profile_id"]

    for key in ONSKY_NUMERIC_KEYS:
        if key not in updates:
            continue
        v = _finite_any(updates[key])
        ONSKY_CALIBRATION[key] = v
        if v is None:
            block.pop(key, None)
        else:
            block[key] = v

    data["onsky"] = block
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# NINA Advanced API (contrôle HTTP depuis NPOAP)
# ──────────────────────────────────────────────────────────────
NINA_DEFAULTS = {
    "host": "127.0.0.1",
    "port": 1888,
    "protocol": "http",
    "capture_duration_s": 30.0,
    "capture_gain": 56.0,
    "slew_center": False,
    "seq_filters": "G,BP,RP",
    "seq_frames_per_filter": 3,
    "seq_cool_camera": True,
    "seq_cool_target_c": -5.0,
    "seq_park_at_end": True,
    "seq_connect_at_start": True,
    "seq_start_guider": False,
    "seq_auto_focus": False,
}


def get_nina_config() -> dict:
    """Lit la section ``nina`` de config.json (fusionnée avec NINA_DEFAULTS)."""
    import json

    out = dict(NINA_DEFAULTS)
    path = BASE_DIR / "config.json"
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        block = data.get("nina")
        if isinstance(block, dict):
            out.update({k: v for k, v in block.items() if v is not None})
    except Exception:
        pass
    try:
        out["port"] = int(out["port"])
    except (TypeError, ValueError):
        out["port"] = NINA_DEFAULTS["port"]
    try:
        out["capture_duration_s"] = float(out["capture_duration_s"])
    except (TypeError, ValueError):
        out["capture_duration_s"] = NINA_DEFAULTS["capture_duration_s"]
    try:
        out["capture_gain"] = float(out["capture_gain"])
    except (TypeError, ValueError):
        out["capture_gain"] = NINA_DEFAULTS["capture_gain"]
    for bool_key in (
        "slew_center",
        "seq_cool_camera",
        "seq_park_at_end",
        "seq_connect_at_start",
        "seq_start_guider",
        "seq_auto_focus",
    ):
        if bool_key in out:
            out[bool_key] = bool(out[bool_key])
    try:
        out["seq_frames_per_filter"] = int(out.get("seq_frames_per_filter", 3))
    except (TypeError, ValueError):
        out["seq_frames_per_filter"] = 3
    try:
        out["seq_cool_target_c"] = float(out.get("seq_cool_target_c", -5.0))
    except (TypeError, ValueError):
        out["seq_cool_target_c"] = -5.0
    out["seq_filters"] = str(out.get("seq_filters") or "")
    out["protocol"] = str(out.get("protocol") or "http").lower()
    out["host"] = str(out.get("host") or NINA_DEFAULTS["host"]).strip()
    return out


def persist_nina_config(**fields) -> None:
    """Fusionne les champs fournis dans la section ``nina`` de config.json."""
    import json

    block = get_nina_config()
    for key, value in fields.items():
        if value is not None:
            block[key] = value
    path = BASE_DIR / "config.json"
    data: dict = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data["nina"] = block
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass
