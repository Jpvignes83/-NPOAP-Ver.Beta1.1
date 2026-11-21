# 🔭 Mode d'emploi pratique — Workflow ExoPlanetPie natif

> Panneau **droit** de l'onglet *🔭 Photométrie Exoplanètes*.
> Implémentation Python native de la chaîne **batman + ultranest + ExoTETHyS**,
> alimentée par **ExoClock / NASA Exoplanet Archive** et **lightkurve (MAST)**.

Pour la description détaillée et exhaustive du workflow, voir le manuel
utilisateur, section **§4.8 — Workflow ExoPlanetPie natif**
(`docs/MANUEL_UTILISATEUR.md`).

---

## Vue d'ensemble

Le panneau droit contient un **notebook en 8 sous-onglets (A → H)** qui suivent
la chaîne logique d'une analyse de transit, **depuis la donnée brute jusqu'au
diagramme O − C**. Vous pouvez les parcourir séquentiellement la première fois,
puis revenir librement aux étapes intermédiaires.

```
A. Satellite Data ──→ B. NASA / AAVSO ──→ C. Get Planet ──→ D. Prepare Data ──→
                                                                      │
                                ┌─────────────────────────────────────┘
                                ↓
                E. Transit Fitter ──→ F. Transit Merger ──→ G. TTV ──→ H. Visualizer
```

Tous les résultats sont enregistrés sous `output/exoplanetpie/` à la **racine de
votre installation NPOAP** (jamais sous `Program Files`, donc pas de souci UAC).

---

## Étapes pas à pas

### **C. Get Planet** *(à faire en premier si vous partez de zéro)*

Récupération automatique des paramètres de la planète :

1. Saisir le nom (ex. `WASP-12 b`, `HD 189733 b`, `TOI-216.01`, `Kepler-7 b`).
2. Cliquer sur **« ExoClock »** (rapide, cache communautaire ARIEL) **ou**
   **« NASA Archive »** (table `pscomppars`, repli automatique sur les
   variantes `TOI-216.01 → TOI-216 b` si nécessaire).
3. Les champs (Teff, log g, [Fe/H], R★, M★, P, T0, Rp/R★, a/R★, i, e, ω,
   durée T14) se remplissent.
4. Bouton **« Appliquer ces paramètres »** — **étape indispensable** : sans
   cela, le fit n'aura pas de planète de référence.

> 💡 Les valeurs restent éditables manuellement si vous souhaitez forcer une
> valeur de la littérature.

### **A. Satellite Data** *(téléchargement MAST TESS / Kepler)*

Pour récupérer une lightcurve depuis l'archive **MAST** (rapide, pas besoin
d'images locales) :

1. Saisir la cible (mêmes formes que ci-dessus ; TESS comprend les TIC ID).
2. **Mission** : `TESS`, `Kepler`, `K2` ou vide (tous).
3. Bouton **« Rechercher »** → tableau des secteurs / quarters disponibles.
4. Cocher les lignes voulues, puis **« Télécharger sélection »**.
5. Sorties en CSV (`BJD, flux, flux_err`) sous
   `output/exoplanetpie/1_RawFiles/<planète>/`.

> ⚠️ Le premier téléchargement d'un secteur peut prendre **plusieurs minutes** ;
> les fichiers sont ensuite mis en cache par `lightkurve` dans
> `%USERPROFILE%\.lightkurve\cache`.

### **B. NASA / AAVSO** *(import manuel d'une courbe locale)*

Alternative si vous avez déjà une lightcurve produite par HOPS, AAVSO ou un
autre pipeline :

1. **« Importer CSV… »** : sélection du fichier.
2. Choix des colonnes **BJD / flux / erreur** dans le menu déroulant.
3. La courbe est ajoutée au pool de données, comme si elle venait de MAST.

### **D. Prepare Data** *(slicing en cycles)*

Découpage de la lightcurve longue en transits individuels, **un cycle par
fenêtre** :

1. **Sélectionner** la source téléchargée (A) ou importée (B).
2. Saisir la **demi-fenêtre** en jours (par défaut `0.2` j, soit ± 4 h 48 min
   autour du T0 attendu).
3. Bouton **« Découper »** → un cycle par CSV dans
   `output/exoplanetpie/2_MidtimesFiles/<lc_id>/cycle_<NNNNN>.csv`.

> 💡 La fenêtre doit englober la **base hors transit** des deux côtés (pour le
> détrendage) — typiquement 2 à 3 × la durée T14.

### **E. Transit Fitter** *(le cœur du workflow)*

Ajustement bayésien **batman + ultranest** d'un cycle individuel :

1. **Sélectionner** un cycle dans la liste (issu de D).
2. **Filtre** : TESS, Kepler, Johnson V/B, Cousins R/I, Sloan g/r/i,
   Gaia G/BP/RP, …
3. **Modèle stellaire LDC** : `Phoenix_2018` par défaut → chaîne de repli
   automatique `Stagger_2018` → `Atlas_2000` si Teff/log g/[Fe/H] sont hors
   grille.
4. **Détrendage** : `wotan biweight` avec masque transit (durée T14) — par
   défaut activé.
5. **N_live** (ultranest) : 200 par défaut. Pour un **test rapide** mettre 50
   (≈ 1 min) ; pour publication, garder 200 (≈ 5–20 min / cycle).
6. Bouton **« Lancer le fit »** → la barre de progression
   `[ultranest] Sampling N live points from prior …` apparaît dans la console
   NPOAP (et dans le fichier `logs/npoap_<pid>.log`).
7. **Résultats** : T0 ajusté ± σ, Rp/R★ ± σ, χ²_r, log-évidence, traces et
   plot folded sous `output/exoplanetpie/3_FitResults/<planète>/cycle_<NNNNN>_*.{json,png,pdf}`.

> ⚠️ Le message `WARNING: metallicity is out of the range` est **bénin** :
> la chaîne de repli prendra le relais sur un autre modèle stellaire.
>
> ⚠️ Le `ValueError: I/O operation on closed file` qui peut apparaître pendant
> le téléchargement est **bénin** (interaction `colorama` × `lightkurve` ×
> threads sous Windows) et est intercepté par le logger NPOAP.

### **F. Transit Merger** *(agrégation N cycles)*

Construction du fichier `midtimes.csv` exploitable par TTV :

1. **« Charger un dossier de fits »** → liste tous les `cycle_*_fit.json` du
   répertoire choisi.
2. **Cocher** les cycles à conserver (décocher les mauvais : χ²_r > 5, σ
   aberrante, etc.).
3. Bouton **« Exporter mid-times CSV… »** → fichier final dans
   `output/exoplanetpie/3_MidTimes/`, colonnes :
   `ok, cycle, transit_midtime, transit_midtime_min, transit_midtime_plus`.

### **G. TTV** *(diagramme O − C)*

C'est ici qu'est greffé le bouton **« Aide (manuel)… »** à droite, qui ouvre
directement le manuel utilisateur sur §4.8.

1. **« Charger mid-times… »** : sélectionner le CSV produit en F.
2. **Modèle** :
   - `linear` (P + T0) → calibration des éphémérides ;
   - `quadratic` (dérive temporelle) → recherche d'orbital decay ou effet
     marée ;
   - `sin` (modulation périodique) → signature d'une **planète additionnelle**
     ou d'une **lune**.
3. Bouton **« Fit O-C »** → graphique O − C en minutes vs cycle ; χ²_r et RMS
   affichés dans le titre.
4. **« Enregistrer résultat… »** →
   `output/exoplanetpie/4_TTV/<planète>/ttv_<modèle>.json`.

> 💡 Pour aller plus loin (analyse N-body, ajustement REBOUND, MCMC dédié), le
> `midtimes.csv` est directement importable dans l'onglet
> **📈 Analyse de Données → 7.2 Recherche & Analyse TTV** (voir manuel
> utilisateur).

### **H. Visualizer** *(relire un résultat existant)*

Ouvre n'importe quel `ttv_*.json` sauvegardé en G et redessine le diagramme
O − C — utile pour comparer plusieurs hypothèses ou présenter un résultat sans
relancer le fit.

---

## 🛠️ Workflow type — 1 nuit d'observation à 1 figure O − C

```
1. C. Get Planet      → "TOI-216.01" → ExoClock → Appliquer
2. A. Satellite Data  → TESS, secteurs 2/3 → Télécharger
3. D. Prepare Data    → demi-fenêtre 0.2 j → Découper (≈ 18 cycles)
4. E. Transit Fitter  → Pour chaque cycle :
                          filtre TESS, n_live=200 → Lancer
                          (1 cycle ≈ 5–20 min)
5. F. Transit Merger  → Charger dossier 3_FitResults
                        → décocher 2 cycles bruités → Exporter
6. G. TTV             → Charger mid-times
                        → modèle linear puis quadratic → Comparer χ²_r
```

## 🚀 Astuces

| Astuce | Effet |
|---|---|
| **Filtre = TESS** plutôt que `JOHNSON_V` quand vous travaillez TESS | LDC parfaitement adaptés au passband satellite |
| **Démarrer avec `n_live=50`** | Permet de valider le slicing + LDC + détrendage en 1 min/cycle avant de relancer à 200 pour publication |
| **Si ExoClock renvoie [Fe/H]=0.0 douteux** | Bascule **C → NASA Archive** pour comparer (`st_met` y est plus complet) |
| **Plusieurs filtres pour la même planète** | F. Merger sait fusionner des fits issus de filtres différents (chaque ligne reste taggée du filtre origine) |
| **Fit qui n'avance pas (> 30 min/cycle)** | Vérifier que la fenêtre D contient bien le baseline hors transit, et que le détrendage wotan ne « mange » pas le transit (vérifier T14) |

## 📁 Arborescence finale `output/exoplanetpie/`

```
1_RawFiles/<planète>/         CSV bruts MAST (lightkurve)
2_MidtimesFiles/<lc_id>/      CSV slicés par cycle
3_FitResults/<planète>/       JSON + PNG + PDF par cycle (batman + ultranest)
3_MidTimes/                   midtimes.csv agrégés (F. Merger)
4_TTV/<planète>/              ttv_*.json + oc_diagram (G + H)
```

Tous ces fichiers sont **portables** : vous pouvez zipper le répertoire d'une
planète et l'envoyer à un collaborateur, ou le relire 6 mois plus tard via
**H. Visualizer**.

---

## 🔗 Liens utiles

- Manuel utilisateur complet : `docs/MANUEL_UTILISATEUR.md` (§4.8)
- Remerciements bibliothèques : `docs/ACKNOWLEDGEMENTS.md`
  (batman-package, ExoTETHyS, ultranest, lightkurve, wotan)
- Installation : `docs/MANUEL_INSTALLATION.md`
- Backend Python : `core/exoplanetpie_pipeline.py`

---

*NPOAP — Workflow ExoPlanetPie natif (panneau droit de l'onglet
*🔭 Photométrie Exoplanètes*).*
