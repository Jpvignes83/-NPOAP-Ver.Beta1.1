# external_apps/lite — NPOAP AUTONOME Lite

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
python build\assemble_external_apps_lite.py --clean
construire_distribution_autonome.bat
```
