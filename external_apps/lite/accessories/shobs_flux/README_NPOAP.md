# SHOBS-FLUX dans NPOAP

Copie runtime de **SHOBS-FLUX 1.0.1** (Shiloh Hill Observatory Optical System Characterization).

- Licence : **GNU GPL-3.0+** (voir `LICENSE`)
- Citation : DOI [10.5281/zenodo.24115980](https://doi.org/10.5281/zenodo.24115980) (`CITATION.cff`)
- Upstream : https://github.com/SHOBS-S/SHOBS-FLUX

## Rôle dans NPOAP

**Phase 1** — application séparée + pont profils :

1. lancement via Accueil / Réduction ;
2. import `~/.shobs/cameras/` → `config.json`.

**Phase 2** — APIs scientifiques embarquées dans Réduction (section **1b**) :

- Bench (`bench.run_bench`) → gain, RN, linéarité, full well ;
- Darks (`darks.run_darks`) → courant d’obscurité ;
- Check image (`image_check.check_image`) ;
- Plan de tir (`bench.plan_ladder` / `plan_text`).

**Phase 3** — Sky / système :

- Dossier de lights (`sky_folder` + `onsky`) → ZP, extinction, seeing, ciel, C_Y ;
- Relance depuis `~/.shobs/onsky/` ;
- Profil système `~/.shobs/systems/` + bloc `onsky` dans `config.json` ;
- Photométrie NPOAP : `get_extinction_k()` dans `compute_zero_point`.

**Phase 4** — Historique & rapport :

- Chaque Bench / Dark / Check / Sky est enregistré dans `~/.shobs/flux_runs.sqlite` ;
- Dialogue **Historique / Rapport** : tendances, export CSV/PNG, rapport système PDF
  (complet ou partagé sans chemins locaux).

Wrappers NPOAP : `core/shobs_flux_runtime.py`, `core/shobs_flux_analysis.py`,
`core/shobs_flux_history.py`.
Les résultats mettent à jour `config.json` et les profils `~/.shobs/`.

Les tests, générateurs synthétiques et captures d’écran du manuel n’ont pas été
vendus ici ; le manuel Markdown est dans `docs/manual/`.

## Lancement manuel

```text
python flux_app.py
```

Dépendances : NumPy, SciPy, Astropy, Matplotlib, Tkinter (déjà dans l’astroenv NPOAP).
