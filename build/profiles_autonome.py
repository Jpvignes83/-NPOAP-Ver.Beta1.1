#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Profils de build pour la distribution AUTONOME Lite.

1. full
2. exoplanetes  — Accueil, Observation, NINA, HOPS, ExoPlanetPie
3. asteroides   — Accueil, Observation, NINA, Astéroïdes
4. binaires     — Accueil, Observation, NINA, Étoiles binaires
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ALL_TAB_KEYS = (
    "home",
    "ephemerides",
    "nina_control",
    "data_reduction",
    "photometry_exoplanets",
    "asteroid_photometry",
    "occultations",
    "transient_photometry",
    "binary_stars",
    "easy_lucky_imaging",
    "variable_stars",
    "cluster_analysis",
    "spectroscopy",
    "catalogues",
    "data_analysis",
)


def _tabs(*enabled: str) -> dict[str, bool]:
    wanted = set(enabled) | {"home"}
    return {k: (k in wanted) for k in ALL_TAB_KEYS}


PROFILES: dict[str, dict[str, Any]] = {
    "full": {
        "description": "Complet : tous les onglets + pip autonome (cœur ∪ optionnels)",
        "requirements": "requirements_install_autonome.txt",
        "tabs": {k: True for k in ALL_TAB_KEYS},
        "accessories": {
            "shobs_flux": True,
            "hops": True,
            "optionnels_installers": True,
        },
    },
    "exoplanetes": {
        "description": (
            "Exoplanètes : Accueil, Observation, NINA, Réduction, "
            "Photométrie Exoplanètes (ExoPlanetPie / HOPS)"
        ),
        "requirements": "requirements_install_core.txt",
        "tabs": _tabs(
            "home",
            "ephemerides",
            "nina_control",
            "data_reduction",  # calibration / flux utiles à ExoPlanetPie
            "photometry_exoplanets",
            "data_analysis",
        ),
        "accessories": {
            "shobs_flux": True,
            "hops": True,
            "optionnels_installers": False,
        },
    },
    "asteroides": {
        "description": "Astéroïdes : Accueil, Observation, NINA, Photométrie astéroïdes",
        "requirements": "requirements_install_core.txt",
        "tabs": _tabs(
            "home",
            "ephemerides",
            "nina_control",
            "data_reduction",
            "asteroid_photometry",
        ),
        "accessories": {
            "shobs_flux": True,
            "hops": False,
            "optionnels_installers": True,  # KBMOD WSL scripts
        },
    },
    "binaires": {
        "description": "Binaires : Accueil, Observation, NINA, Étoiles binaires",
        "requirements": "requirements_install_core.txt",
        "tabs": _tabs(
            "home",
            "ephemerides",
            "nina_control",
            "data_reduction",
            "binary_stars",
        ),
        "accessories": {
            "shobs_flux": False,
            "hops": False,
            "optionnels_installers": True,  # PHOEBE éventuel
        },
    },
}

# Alias FR / typos fréquents → clé canonique
ALIASES = {
    "exoplanets": "exoplanetes",
    "exoplanet": "exoplanetes",
    "asteroids": "asteroides",
    "asteroid": "asteroides",
    "binaries": "binaires",
    "binary": "binaires",
    "etoiles": "binaires",
}


def list_profiles() -> list[tuple[str, str]]:
    return [(name, meta["description"]) for name, meta in PROFILES.items()]


def get_profile(name: str) -> dict[str, Any]:
    key = (name or "full").strip().lower()
    key = ALIASES.get(key, key)
    if key not in PROFILES:
        known = ", ".join(PROFILES)
        raise KeyError(f"Profil inconnu: {name!r}. Disponibles: {known}")
    return deepcopy(PROFILES[key])
