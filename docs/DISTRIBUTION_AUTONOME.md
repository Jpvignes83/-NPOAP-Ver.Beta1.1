# Distribution NPOAP AUTONOME Lite

Archive **autosuffisante** : code cœur, codes optionnels et accessoires en
versions **Lite**, vendus sous `external_apps/lite/`. Aucun clone Git n’est
requis pour obtenir ces sources.

## Layout `external_apps/lite/`

| Chemin | Contenu Lite |
|--------|----------------|
| `core/` | Sources NPOAP `core/` (sans `__pycache__`) |
| `optionnels/` | Requirements + installateurs + WSL very_Lite + docs associées |
| `accessories/shobs_flux/` | SHOBS-FLUX runtime |
| `accessories/hops/hops-master/` | HOPS modifié (extrait de `hopsmodified.zip`) |
| `MANIFEST.json` | Inventaire / horodatage d’assemblage |

Le runtime exécutable reste à la **racine** de l’archive (`core/`, `gui/`,
`main.py`, …). `external_apps/lite/` est la copie **vendue** autonome ; les
résolveurs SHOBS/HOPS cherchent d’abord le chemin Lite.

## Contenu archive

| Élément | Inclus |
|---------|--------|
| `core/`, `gui/`, `utils/`, `config/`, `scripts/` | Oui (runtime) |
| `external_apps/lite/{core,optionnels,accessories}` | Oui (vendu Lite) |
| `docs/`, `resources/` | Oui |
| `requirements.txt` | = `requirements_install_autonome.txt` |
| Installateurs Windows + WSL very_Lite | Oui |
| Onglets | Tous activés (`config/tabs_config.py`) |

**Hors archive (volontaire)** : binaires KBMOD, FSPS/Prospector compilés,
indexs astrometry multi-Go, CuPy. Les *scripts* Lite pour les installer sont
dans `external_apps/lite/optionnels/`.

## Produire l’archive (mainteneur)

```bat
construire_distribution_autonome.bat
```

Enchaîne :

1. `python build/assemble_external_apps_lite.py --clean`
2. `python build/build_autonome.py`

Sorties :

- `build/distributions/autonome/`
- `build/distributions/NPOAP_AUTONOME_YYYYMMDD_HHMM.zip`

Sans ZIP / sans réassemblage lite :

```bat
python build\build_autonome.py --no-zip
python build\build_autonome.py --skip-assemble-lite
```

Régénérer uniquement le tree Lite dans le dépôt :

```bat
python build\assemble_external_apps_lite.py --clean
```

## Installation (utilisateur final)

1. Extraire le ZIP
2. Miniconda (Python 3.11)
3. `INSTALLER_NPOAP_AUTONOME_WINDOWS.bat` → `astroenv` + pip autonome
4. `LANCER_NPOAP_ASTROENV.bat`

Compléments système :

```bat
install_wsl.bat
install_ubuntu_wsl_very_lite.bat
install_kbmod_wsl.bat
```

Voir `docs/WSL_VERY_LITE.md`.

## Différence avec les anciens profils

| Profil | Code | Pip |
|--------|------|-----|
| `reduction`, `exoplanets`, … | Sous-ensemble d’onglets | requirements réduit |
| `full` (ancien) | Tous les modules | souvent `requirements.txt` dépôt |
| **`autonome` Lite** | Runtime + **`external_apps/lite`** (core ∪ optionnels ∪ accessories) | cœur **+** optionnels PyPI |
