#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assemble external_apps/lite/ pour une distribution AUTONOME Lite.

Layout cible :
  external_apps/lite/
    core/           — sources NPOAP core (sans __pycache__)
    optionnels/     — requirements + installateurs optionnels + WSL very_Lite
    accessories/    — shobs_flux + hops (extrait du zip)
    MANIFEST.json
    README.md

Usage (racine dépôt) :
  python build/assemble_external_apps_lite.py
  python build/assemble_external_apps_lite.py --clean
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LITE_ROOT = ROOT / "external_apps" / "lite"

SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".cursor",
    "node_modules",
    ".venv",
    "venv",
    "logs",
    "output",
    "runtime_logs",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".pyd"}

# Installateurs / scripts optionnels (versions Lite = scripts seuls, pas de binaires)
OPTIONNELS_ROOT_FILES = [
    "requirements_install_optionnels.txt",
    "requirements_install_core.txt",
    "requirements_install_autonome.txt",
    "LISTE_INSTALL_OPTIONNELS.txt",
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
    "INSTALLER_SORA_ASTROENV.bat",
]

OPTIONNELS_SCRIPTS = [
    "scripts/bootstrap_npoap_wsl_very_lite.sh",
    "scripts/install_kbmod_wsl.sh",
    "scripts/ensure_wsl_astroenv_py311.sh",
    "scripts/kbmod_wsl_detect.py",
]

OPTIONNELS_DOCS = [
    "docs/WSL_VERY_LITE.md",
    "docs/INSTALL_KBMOD_WSL.md",
    "docs/DISTRIBUTION_AUTONOME.md",
]


def should_skip(rel: Path) -> bool:
    if any(p in SKIP_DIR_NAMES for p in rel.parts):
        return True
    if rel.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def _rmtree_force(path: Path) -> None:
    """Supprime un arbre même si des fichiers sont en lecture seule (OneDrive)."""
    if not path.exists():
        return

    def _onerror(func, p, _exc_info):
        try:
            Path(p).chmod(0o666)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, onerror=_onerror)


def copy_tree_lite(src: Path, dst: Path) -> int:
    """Recopie src → dst en excluant caches / artefacts lourds."""
    n = 0
    if not src.exists():
        return 0
    _rmtree_force(dst)
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        if should_skip(rel):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        try:
            target.chmod(0o666)
        except Exception:
            pass
        n += 1
    return n


def extract_hops_lite(dst_hops: Path) -> int:
    """Extrait hopsmodified.zip vers accessories/hops/hops-master (layout NPOAP)."""
    zip_path = ROOT / "external_apps" / "hopsmodified.zip"
    if not zip_path.exists():
        print(f"  [SKIP] {zip_path.name} absent")
        return 0

    if dst_hops.exists():
        shutil.rmtree(dst_hops)
    dst_hops.mkdir(parents=True, exist_ok=True)

    n = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            # Normalise vers hops/hops-master/...
            parts = name.split("/")
            if parts and parts[0] == "hops":
                rel = "/".join(parts[1:])  # hops-master/...
            elif parts and parts[0] == "hops-master":
                rel = name
            else:
                rel = "hops-master/" + name.split("/")[-1] if "/" not in name else name
            if not rel or rel.endswith("/"):
                continue
            # Ignore caches dans le zip
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            target = dst_hops / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
    return n


def write_readme(lite: Path) -> None:
    text = """# external_apps/lite — NPOAP AUTONOME Lite

Versions **Lite** vendues pour une distribution **totalement autonome**
(pas de clone Git requis pour le code applicatif et les accessoires).

| Dossier | Contenu |
|---------|---------|
| `core/` | Sources `core/` NPOAP (sans `__pycache__`) |
| `optionnels/` | Requirements + installateurs optionnels + WSL very_Lite |
| `accessories/shobs_flux/` | SHOBS-FLUX runtime (sans caches) |
| `accessories/hops/` | HOPS modifié extrait (`hops-master/`) |

## Runtime NPOAP

L’application continue d’importer `core/` et `gui/` à la **racine** de la
distribution (copies de travail). `external_apps/lite/` est la **source
vendue** Lite ; le build autonome synchronise racine ↔ lite.

Chemins accessoires résolus dans l’ordre :

1. `external_apps/lite/accessories/...`
2. `external_apps/...` (compat anciennes copies)

## Régénérer

```bat
python build\\assemble_external_apps_lite.py --clean
construire_distribution_autonome.bat
```
"""
    (lite / "README.md").write_text(text, encoding="utf-8")


def assemble(clean: bool = False) -> dict:
    if clean and LITE_ROOT.exists():
        _rmtree_force(LITE_ROOT)
    LITE_ROOT.mkdir(parents=True, exist_ok=True)

    stats: dict = {"built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    # --- core lite ---
    n = copy_tree_lite(ROOT / "core", LITE_ROOT / "core")
    stats["core_files"] = n
    print(f"  [OK] lite/core/  ({n} fichiers)")

    # --- optionnels lite ---
    opt = LITE_ROOT / "optionnels"
    _rmtree_force(opt)
    opt.mkdir(parents=True)
    n_opt = 0
    for name in OPTIONNELS_ROOT_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, opt / Path(name).name)
            n_opt += 1
    for rel in OPTIONNELS_SCRIPTS:
        src = ROOT / rel
        if src.exists():
            dst = opt / "scripts" / Path(rel).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_opt += 1
    for rel in OPTIONNELS_DOCS:
        src = ROOT / rel
        if src.exists():
            dst = opt / "docs" / Path(rel).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_opt += 1
    stats["optionnels_files"] = n_opt
    print(f"  [OK] lite/optionnels/  ({n_opt} fichiers)")

    # --- accessories ---
    acc = LITE_ROOT / "accessories"
    acc.mkdir(parents=True, exist_ok=True)

    n_shobs = 0
    shobs_src = ROOT / "external_apps" / "shobs_flux"
    # Si déjà migré sous lite, utiliser cette source
    if not shobs_src.is_dir() and (LITE_ROOT / "accessories" / "shobs_flux").is_dir():
        shobs_src = LITE_ROOT / "accessories" / "shobs_flux"
    if shobs_src.is_dir() and shobs_src.resolve() != (acc / "shobs_flux").resolve():
        n_shobs = copy_tree_lite(shobs_src, acc / "shobs_flux")
    elif (acc / "shobs_flux").is_dir():
        n_shobs = sum(1 for _ in (acc / "shobs_flux").rglob("*") if _.is_file())
    stats["shobs_flux_files"] = n_shobs
    print(f"  [OK] lite/accessories/shobs_flux/  ({n_shobs} fichiers)")

    n_hops = extract_hops_lite(acc / "hops")
    stats["hops_files"] = n_hops
    print(f"  [OK] lite/accessories/hops/  ({n_hops} fichiers)")

    write_readme(LITE_ROOT)
    (LITE_ROOT / "MANIFEST.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  [OK] lite/MANIFEST.json")
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Assemble external_apps/lite (NPOAP AUTONOME Lite)")
    p.add_argument("--clean", action="store_true", help="Efface lite/ avant assemblage")
    args = p.parse_args(argv)
    print(f"[LITE] Racine : {ROOT}")
    print(f"[LITE] Cible  : {LITE_ROOT}")
    try:
        assemble(clean=args.clean)
    except Exception as exc:
        print(f"[LITE] ERREUR: {exc}")
        return 1
    print("[LITE] Termine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
