#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construit la distribution NPOAP AUTONOME Lite (complète ou partielle) :
  - assemble d'abord external_apps/lite/{core,optionnels,accessories}
  - recopie le runtime (core, gui, …) + lite vendu
  - applique un profil (--profile) : onglets + requirements + accessoires
  - scripts d'installation cœur + optionnels + WSL very_Lite

Sortie :
  build/distributions/autonome/            (profil full)
  build/distributions/autonome_<profil>/   (profil partiel)
  + ZIP optionnel
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_ROOT = Path(__file__).resolve().parent / "distributions"

# Assure que build/ est importable
if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

from profiles_autonome import get_profile, list_profiles  # noqa: E402

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
        if target.exists():
            try:
                target.chmod(0o666)
            except Exception:
                pass
        shutil.copy2(item, target)
        try:
            target.chmod(0o666)
        except Exception:
            pass
        n += 1
    return n


def _rmtree_force(path: Path) -> None:
    if not path.exists():
        return

    # OneDrive / Windows : lever lecture seule avant suppression
    for p in path.rglob("*"):
        try:
            if p.is_file() or p.is_symlink():
                p.chmod(0o666)
        except Exception:
            pass

    def _onerror(func, p, _exc_info):
        try:
            Path(p).chmod(0o666)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, onerror=_onerror)


def write_tabs_config(config_dir: Path, tabs: dict[str, bool], profile: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Configuration des onglets actives",
        f"# Distribution AUTONOME — profil: {profile}",
        "",
        "ENABLED_TABS = {",
    ]
    for key, val in tabs.items():
        lines.append(f"    {key!r}: {val},")
    lines.append("}")
    lines.append("")
    (config_dir / "tabs_config.py").write_text("\n".join(lines), encoding="utf-8")


def prune_accessories(out: Path, accessories: dict[str, bool]) -> None:
    """Retire les accessoires Lite non demandés par le profil partiel."""
    lite = out / "external_apps" / "lite"
    if not accessories.get("shobs_flux", True):
        for p in (
            lite / "accessories" / "shobs_flux",
            out / "external_apps" / "shobs_flux",
        ):
            if p.exists():
                _rmtree_force(p)
                print(f"  [PRUNE] {p.relative_to(out)}")
    if not accessories.get("hops", True):
        for p in (
            lite / "accessories" / "hops",
            out / "external_apps" / "hops",
            out / "external_apps" / "hopsmodified.zip",
        ):
            if p.exists():
                if p.is_dir():
                    _rmtree_force(p)
                else:
                    p.unlink()
                print(f"  [PRUNE] {p.relative_to(out)}")
    if not accessories.get("optionnels_installers", True):
        # Garde requirements + WSL very_Lite ; retire installateurs lourds optionnels
        opt = lite / "optionnels"
        heavy = [
            "install_kbmod_wsl.bat",
            "install_msvc_build_tools.bat",
            "install_cmake.bat",
            "install_phoebe_astroenv.bat",
            "INSTALLER_SORA_ASTROENV.bat",
            "scripts/install_kbmod_wsl.sh",
            "scripts/kbmod_wsl_detect.py",
            "scripts/ensure_wsl_astroenv_py311.sh",
            "docs/INSTALL_KBMOD_WSL.md",
        ]
        for rel in heavy:
            p = opt / rel
            if p.exists():
                p.unlink()
                print(f"  [PRUNE] {p.relative_to(out)}")


def write_dist_readme(out: Path, profile: str, meta: dict) -> None:
    tabs_on = [k for k, v in meta["tabs"].items() if v]
    text = f"""# NPOAP — Distribution AUTONOME Lite (profil `{profile}`)

{meta["description"]}

## Onglets actifs

{chr(10).join(f"- `{t}`" for t in tabs_on)}

## Requirements pip

`requirements.txt` ← `{meta["requirements"]}`

## Accessoires Lite

| Accessoire | Inclus |
|------------|--------|
| SHOBS-FLUX | {"oui" if meta["accessories"].get("shobs_flux") else "non"} |
| HOPS | {"oui" if meta["accessories"].get("hops") else "non"} |
| Installateurs optionnels (KBMOD/MSVC/…) | {"oui" if meta["accessories"].get("optionnels_installers") else "non"} |

## Installation rapide

1. Installer Miniconda (Python 3.11).
2. `INSTALLER_NPOAP_ASTROENV_WINDOWS.bat` ou `INSTALLER_NPOAP_AUTONOME_WINDOWS.bat`
3. `LANCER_NPOAP_ASTROENV.bat`

## Rebuild

```bat
construire_distribution_autonome.bat {profile}
```

Profils : `full`, `exoplanetes`, `asteroides`, `binaires`.
"""
    (out / "README_DISTRIBUTION_AUTONOME.md").write_text(text, encoding="utf-8")


def make_zip(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir.parent).as_posix())


def out_dir_for_profile(profile: str) -> Path:
    if profile == "full":
        return DIST_ROOT / "autonome"
    return DIST_ROOT / f"autonome_{profile}"


def build(
    profile: str = "full",
    make_archive: bool = True,
    skip_assemble_lite: bool = False,
) -> Path:
    if not (ROOT / "main.py").exists():
        raise SystemExit(f"main.py introuvable dans {ROOT}")

    meta = get_profile(profile)
    req_name = meta["requirements"]
    req_path = ROOT / req_name
    if not req_path.exists():
        raise SystemExit(f"Manquant: {req_path}")

    out_root = out_dir_for_profile(profile)

    if not skip_assemble_lite:
        print("[AUTONOME] Assemblage external_apps/lite ...")
        from assemble_external_apps_lite import assemble as assemble_lite

        assemble_lite(clean=True)
    else:
        print("[AUTONOME] SKIP assemblage lite (--skip-assemble-lite)")

    if out_root.exists():
        _rmtree_force(out_root)
    out_root.mkdir(parents=True)

    print(f"[AUTONOME] Profil : {profile}")
    print(f"[AUTONOME] Source : {ROOT}")
    print(f"[AUTONOME] Sortie : {out_root}")

    total = 0
    for name in COPY_DIRS:
        src = ROOT / name
        if not src.exists():
            print(f"  [SKIP] dossier absent: {name}")
            continue
        n = copy_tree(src, out_root / name)
        print(f"  [OK] {name}/  ({n} fichiers)")
        total += n

    # external_apps/lite est deja inclus via COPY_DIRS["external_apps"]

    for name in COPY_ROOT_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, out_root / name)
            total += 1
            print(f"  [OK] {name}")
        else:
            print(f"  [SKIP] {name}")

    shutil.copy2(req_path, out_root / "requirements.txt")
    print(f"  [OK] requirements.txt <- {req_name}")

    write_tabs_config(out_root / "config", meta["tabs"], profile)
    print(f"  [OK] config/tabs_config.py (profil {profile})")

    print("  [INFO] Elagage accessoires selon profil...")
    prune_accessories(out_root, meta["accessories"])

    write_dist_readme(out_root, profile, meta)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lite_ok = (out_root / "external_apps" / "lite" / "MANIFEST.json").exists()
    manifest = {
        "profile": profile,
        "description": meta["description"],
        "requirements": req_name,
        "tabs": meta["tabs"],
        "accessories": meta["accessories"],
        "built": stamp,
        "files_copied": total,
        "lite_ok": lite_ok,
    }
    (out_root / "BUILD_AUTONOME.txt").write_text(
        f"NPOAP distribution AUTONOME Lite\n"
        f"Profile: {profile}\n"
        f"Built: {stamp}\n"
        f"Requirements: {req_name}\n"
        f"Root files+dirs copied: {total}\n"
        f"external_apps/lite: {'OK' if lite_ok else 'MISSING'}\n",
        encoding="utf-8",
    )
    (out_root / "BUILD_PROFILE.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    zip_path = None
    if make_archive:
        stamp_file = datetime.now().strftime("%Y%m%d_%H%M")
        suffix = "" if profile == "full" else f"_{profile}"
        zip_path = DIST_ROOT / f"NPOAP_AUTONOME{suffix}_{stamp_file}.zip"
        print(f"[AUTONOME] Compression {zip_path.name} ...")
        make_zip(out_root, zip_path)
        print(f"[AUTONOME] ZIP: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} Mo)")

    print("[AUTONOME] Termine.")
    return zip_path or out_root


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build NPOAP distribution autonome Lite (complet ou partiel)"
    )
    p.add_argument(
        "--profile",
        "-p",
        default="full",
        help="Profil de build (full, core, reduction, exoplanets, …)",
    )
    p.add_argument(
        "--list-profiles",
        action="store_true",
        help="Liste les profils disponibles et quitte",
    )
    p.add_argument("--no-zip", action="store_true", help="Ne pas creer le ZIP")
    p.add_argument(
        "--skip-assemble-lite",
        action="store_true",
        help="Ne pas regenerer external_apps/lite avant copie",
    )
    args = p.parse_args(argv)

    if args.list_profiles:
        print("Profils disponibles :")
        for name, desc in list_profiles():
            print(f"  {name:14s}  {desc}")
        return 0

    try:
        build(
            profile=args.profile,
            make_archive=not args.no_zip,
            skip_assemble_lite=args.skip_assemble_lite,
        )
    except Exception as exc:
        print(f"[AUTONOME] ERREUR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
