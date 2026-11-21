#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit la distribution NPOAP AUTONOME Lite :
  - assemble d'abord external_apps/lite/{core,optionnels,accessories}
  - recopie le runtime (core, gui, …) + lite vendu
  - scripts d'installation cœur + optionnels + WSL very_Lite
  - requirements.txt = requirements_install_autonome.txt (cœur ∪ optionnels)

Sortie : build/distributions/autonome/  (+ ZIP optionnel)
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = Path(__file__).resolve().parent / "distributions" / "autonome"

# Assure que build/ est importable
if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

# Dossiers applicatifs a recopier integralement (hors exclusions)
COPY_DIRS = [
    "core",
    "gui",
    "utils",
    "config",
    "scripts",
    "docs",
    "resources",
    "tests",
    "external_apps",
]

# Fichiers racine a inclure s'ils existent
COPY_ROOT_FILES = [
    "main.py",
    "config.py",
    "VERSION_BETA.txt",
    "README.md",
    "README_INSTALLATION.md",
    "LISTE_INSTALL_OPTIONNELS.txt",
    "requirements.txt",
    "requirements_install_core.txt",
    "requirements_install_optionnels.txt",
    "requirements_install_autonome.txt",
    "installation.bat",
    "install_optionnels.bat",
    "install_wsl.bat",
    "install_ubuntu_wsl.bat",
    "install_ubuntu_wsl_very_lite.bat",
    "install_astrometry_wsl.bat",
    "install_kbmod_wsl.bat",
    "install_cmake.bat",
    "install_msvc_build_tools.bat",
    "install_phoebe_astroenv.bat",
    "install_sora_analysis.bat",
    "INSTALLER_NPOAP_ASTROENV_WINDOWS.bat",
    "INSTALLER_NPOAP_AUTONOME_WINDOWS.bat",
    "INSTALLER_DISTRIBUTION_FULL_WINDOWS.bat",
    "INSTALLER_SORA_ASTROENV.bat",
    "LANCER_NPOAP_ASTROENV.bat",
    "activate_astroenv.bat",
    "ouvrir_astroenv_cmd.bat",
    "repair_astroenv_pip_permissions.bat",
    "test_application_launch.bat",
    "test_installation.py",
    # Scripts PowerShell requis par installation.bat
    "normalize_requirements_utf8.ps1",
    "installation_miniconda_download.ps1",
]

SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".cursor",
    "logs",
    "output",
    "distributions",
    "node_modules",
    ".venv",
    "venv",
}

SKIP_SUFFIXES = {".pyc", ".pyo", ".pyd"}


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR_NAMES:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def copy_tree(src: Path, dst: Path) -> int:
    n = 0
    if not src.exists():
        return 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        if should_skip(item.relative_to(src)):
            continue
        if should_skip(item):
            continue
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        n += 1
    return n


def write_tabs_all_enabled(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    content = """# Configuration des onglets actives
# Distribution AUTONOME : tous les onglets

ENABLED_TABS = {
    'home': True,
    'ephemerides': True,
    'nina_control': True,
    'photometry_exoplanets': True,
    'data_reduction': True,
    'asteroid_photometry': True,
    'transient_photometry': True,
    'data_analysis': True,
    'binary_stars': True,
    'easy_lucky_imaging': True,
    'cluster_analysis': True,
    'spectroscopy': True,
    'catalogues': True,
}
"""
    (config_dir / "tabs_config.py").write_text(content, encoding="utf-8")


def write_dist_readme(out: Path) -> None:
    text = """# NPOAP — Distribution AUTONOME Lite (Beta 1.1)

Archive **autosuffisante** : code cœur, optionnels et accessoires en versions
**Lite** sous `external_apps/lite/`, plus runtime à la racine.

## Layout Lite vendu

| Chemin | Contenu |
|--------|---------|
| `external_apps/lite/core/` | Sources core NPOAP |
| `external_apps/lite/optionnels/` | Requirements + installateurs + WSL very_Lite |
| `external_apps/lite/accessories/shobs_flux/` | SHOBS-FLUX |
| `external_apps/lite/accessories/hops/` | HOPS modifié (`hops-master/`) |

Le runtime (`core/`, `gui/`, …) à la racine reste celui utilisé par `main.py`.
`external_apps/lite/` est la copie vendue autonome (régénérable).

## Installation rapide

1. Installer [Miniconda](https://docs.conda.io/en/latest/miniconda.html) (Python 3.11).
2. Double-cliquer **`INSTALLER_NPOAP_AUTONOME_WINDOWS.bat`**
   (crée `astroenv` + `pip install -r requirements.txt` = cœur ∪ optionnels PyPI).
3. Lancer **`LANCER_NPOAP_ASTROENV.bat`**.

## Optionnels système (hors pip)

- WSL allégé : `install_wsl.bat` puis `install_ubuntu_wsl_very_lite.bat`
- Astrometry / KBMOD : voir `docs/WSL_VERY_LITE.md` et `docs/INSTALL_KBMOD_WSL.md`
- MSVC / CMake : `install_optionnels.bat` ou scripts individuels

## Fichiers requirements

| Fichier | Rôle |
|---------|------|
| `requirements.txt` | Copie du profil autonome (install unique) |
| `requirements_install_autonome.txt` | Source du profil autonome |
| `requirements_install_core.txt` | Cœur seul |
| `requirements_install_optionnels.txt` | Optionnels PyPI seuls |

Non inclus (volontairement) : Prospector/FSPS compilé, KBMOD compilé, indexs
astrometry multi-Go, CuPy. Les *scripts* Lite pour les installer sont dans
`external_apps/lite/optionnels/`.
"""
    (out / "README_DISTRIBUTION_AUTONOME.md").write_text(text, encoding="utf-8")


def make_zip(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir.parent).as_posix())


def build(make_archive: bool = True, skip_assemble_lite: bool = False) -> Path:
    if not (ROOT / "main.py").exists():
        raise SystemExit(f"main.py introuvable dans {ROOT}")

    autonome_req = ROOT / "requirements_install_autonome.txt"
    if not autonome_req.exists():
        raise SystemExit(f"Manquant: {autonome_req}")

    # 1) Assembler external_apps/lite (core + optionnels + accessories)
    if not skip_assemble_lite:
        print("[AUTONOME] Assemblage external_apps/lite ...")
        from assemble_external_apps_lite import assemble as assemble_lite

        assemble_lite(clean=True)
    else:
        print("[AUTONOME] SKIP assemblage lite (--skip-assemble-lite)")

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True)

    print(f"[AUTONOME] Source : {ROOT}")
    print(f"[AUTONOME] Sortie : {OUT_ROOT}")

    total = 0
    for name in COPY_DIRS:
        src = ROOT / name
        if not src.exists():
            print(f"  [SKIP] dossier absent: {name}")
            continue
        n = copy_tree(src, OUT_ROOT / name)
        print(f"  [OK] {name}/  ({n} fichiers)")
        total += n

    # Garantit la présence du layout lite même si COPY_DIRS a déjà tout pris
    lite_src = ROOT / "external_apps" / "lite"
    if lite_src.is_dir():
        n = copy_tree(lite_src, OUT_ROOT / "external_apps" / "lite")
        print(f"  [OK] external_apps/lite/ synchronise ({n} fichiers)")
        total += n

    for name in COPY_ROOT_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, OUT_ROOT / name)
            total += 1
            print(f"  [OK] {name}")
        else:
            print(f"  [SKIP] {name}")

    # requirements.txt = profil autonome
    shutil.copy2(autonome_req, OUT_ROOT / "requirements.txt")
    print("  [OK] requirements.txt <- requirements_install_autonome.txt")

    write_tabs_all_enabled(OUT_ROOT / "config")
    print("  [OK] config/tabs_config.py (tous onglets)")

    write_dist_readme(OUT_ROOT)

    # Marqueur de build
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lite_ok = (OUT_ROOT / "external_apps" / "lite" / "MANIFEST.json").exists()
    (OUT_ROOT / "BUILD_AUTONOME.txt").write_text(
        f"NPOAP distribution AUTONOME Lite\n"
        f"Built: {stamp}\n"
        f"Root files+dirs copied: {total}\n"
        f"external_apps/lite: {'OK' if lite_ok else 'MISSING'}\n",
        encoding="utf-8",
    )

    zip_path = None
    if make_archive:
        stamp_file = datetime.now().strftime("%Y%m%d_%H%M")
        zip_path = OUT_ROOT.parent / f"NPOAP_AUTONOME_{stamp_file}.zip"
        print(f"[AUTONOME] Compression {zip_path.name} ...")
        make_zip(OUT_ROOT, zip_path)
        print(f"[AUTONOME] ZIP: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} Mo)")

    print("[AUTONOME] Termine.")
    return zip_path or OUT_ROOT


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build NPOAP distribution autonome Lite")
    p.add_argument("--no-zip", action="store_true", help="Ne pas creer le ZIP")
    p.add_argument(
        "--skip-assemble-lite",
        action="store_true",
        help="Ne pas regenerer external_apps/lite avant copie",
    )
    args = p.parse_args(argv)
    try:
        build(make_archive=not args.no_zip, skip_assemble_lite=args.skip_assemble_lite)
    except Exception as exc:
        print(f"[AUTONOME] ERREUR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
