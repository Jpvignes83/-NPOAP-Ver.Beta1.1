# Remerciements (Acknowledgments)

NPOAP utilise de nombreuses bibliothèques et outils open-source de la communauté scientifique. Nous tenons à remercier les développeurs et contributeurs suivants :

## Mises à jour depuis hier 08:00 (crédits techniques)

- **Sous-onglet 🌟 Étoiles Variables** (onglet **⭐ Etoiles**, distribution **`binary_stars`**) : remerciements à l’**AAVSO** pour le catalogue **VSX** et le format **Extended File Format** de soumission des observations ; à **VizieR/CDS** et **astroquery** pour l’accès VSX et **Gaia DR3** (comparateurs photométriques) ; à la communauté **Astropy** / **photutils** pour la photométrie par ouvertures et les conversions temporelles **BJD-TDB**.
- **Profil de distribution `binary_stars` (option 4)** : inclut désormais **Étoiles Binaires**, **Easy Lucky Imaging** et **Étoiles Variables** sous un même onglet **⭐ Etoiles**.
- **Workflow ExoPlanetPie natif** (panneau droit de l'onglet *Photométrie Exoplanètes*) : remerciements aux mainteneurs de **`batman-package`** (Laura Kreidberg), **`ExoTETHyS`** (Giuseppe Morello et al., UCL Exoplanets), **`ultranest`** (Johannes Buchner) et **`lightkurve`** (équipes Kepler/TESS GO Office, NASA Ames / STScI). Ces bibliothèques rendent possible la ré-implémentation Python native de la chaîne `batman + ultranest + ExoTETHyS` directement dans NPOAP (catalogues **ExoClock** / **NASA Exoplanet Archive**, courbes TESS / Kepler via **MAST**), sans dépendre d'un binaire externe.
- **Nouveau profil de distribution `photometrie_exoplanetes`** : *Accueil + Photométrie Exoplanètes uniquement*, généré par `build/build_distribution.py` (option **8** de `construire_distribution.bat`). Permet de redistribuer une version allégée (~17 paquets pip, sans `ccdproc`/`reproject`/`phoebe`/`sora-astro`/`sncosmo`) centrée sur HOPS + workflow natif.
- **Prospector + FSPS via WSL** : la voie Linux (`Installation_fsps\prospector.bat` + `install_prospector_wsl.sh`) est désormais le chemin principal pour un FSPS fonctionnel.
- **WSL / shell robustness** : remerciements aux communautés **WSL**, **Bash** et **CMake** pour les pratiques de robustesse (gestion des fins de ligne, quoting, exécution non interactive) qui ont permis de stabiliser le flux d'installation.
- **STDPipe/ASTRiDE/photutils** : remerciements aux mainteneurs pour la compatibilité continue ; NPOAP applique désormais une dégradation propre quand certains couples de versions ne sont pas alignés.
- **Écosystème packaging Python** : `setuptools`, `pip`, `conda`, `scikit-build-core` et l'outillage autour des wheels/compilation ont joué un rôle central dans le diagnostic et la stabilisation multi-environnements.
- **ExoClock (mai 2026)** : catalogue en ligne **`planets_json`** et module pip **`exoclock`** pour les éphémérides de nuit et HOPS ; **`exoclock`** fait partie du profil d’installation **cœur** (`requirements_install_core.txt`).
- **NINA** : logiciel d’acquisition et d’automatisation (https://nighttime-imaging.eu/) ; l’onglet **Contrôle NINA** de NPOAP s’appuie sur l’**API avancée HTTP** fournie par NINA et ses contributeurs.

## Crédits NPOAP / HOPS-modified

- **Responsable de l'intégration HOPS-modified** : J.P Vignes
- **Contact** : jeanpascal.vignes@gmail.com

## Bibliothèques Python principales

### Calcul scientifique
- **NumPy** : Bibliothèque fondamentale pour le calcul numérique (https://numpy.org/)
- **SciPy** : Bibliothèque scientifique pour Python, incluant optimisation, statistiques, traitement du signal (https://scipy.org/)
- **Pandas** : Manipulation et analyse de données structurées (https://pandas.pydata.org/)

### Astronomie
- **Astropy** : Bibliothèque Python pour l'astronomie (https://www.astropy.org/)
  - Utilisée pour la manipulation des images FITS, les coordonnées célestes, les transformations WCS, et les calculs astronomiques
  - Développée par la communauté Astropy

- **photutils** : Outils de photométrie astronomique (https://photutils.readthedocs.io/)
  - Utilisée pour la détection d'étoiles, la photométrie par ouverture, et l'estimation du fond de ciel
  - Développée dans le cadre du projet Astropy

- **astroquery** : Interface Python pour les services astronomiques en ligne (https://astroquery.readthedocs.io/)
  - Utilisée pour interroger les catalogues Gaia (Vizier), **VSX** (étoiles variables dans le champ), SB9, DEBCat et les éphémérides JPL Horizons
  - Développée dans le cadre du projet Astropy

- **reproject** : Reprojection d'images astronomiques (https://reproject.readthedocs.io/)
  - Utilisée pour l’**alignement WCS** des images en réduction (onglet Réduction de Données) : reprojection de chaque image sur le WCS de référence pour supprimer les décalages avant empilement
  - Utilisée pour l'alignement et la réorientation d'images lors de la soustraction d'images dans l'onglet Photométrie Transitoires
  - Permet la mise à l'échelle, le repositionnement et la correction d'orientation (notamment pour les images de l'hémisphère sud)
  - Développée dans le cadre du projet Astropy

### Visualisation
- **Matplotlib** : Bibliothèque de visualisation (https://matplotlib.org/)
  - Utilisée pour l'affichage graphique des images, courbes de lumière, et périodogrammes

- **Cartopy** : cartographie et projections pour Python (https://scitools.org.uk/cartopy/)
  - Utilisée par la bibliothèque **SORA** pour tracer les cartes d’occultation (`plot_occ_map`) lorsque vous utilisez l’onglet **🌑 Occultation** de NPOAP

### Occultations stellaires (prédictions et cartes)
- **SORA (paquet PyPI `sora-astro`)** : *Stellar Occultation Reduction and Analysis* — prédiction d’occultations, cartes, analyse de courbes et géométrie des événements (https://github.com/riogroup/SORA ; documentation : https://sora.readthedocs.io/)
  - Développée et maintenue par le **Rio Group** et collaborateurs ; NPOAP l’emploie dans l’onglet **🌑 Occultation** (prédictions, carte centrée sur le site d’observation, métadonnées d’erreur pour les bandes d’incertitude lorsque disponibles)

- **Occultation Manager / occultation-tools** (Michael Camilleri) : dépôt d’outils pour l’observation automatisée d’occultations et la validation temporelle ; inclut des modèles de séquences **SharpCap** (dont *Just Record* et templates UTC avec compte à rebours) (https://github.com/labstercam/occultation-tools ; licence BSD-3-Clause)
  - L’export **SharpCap (.scs)** depuis NPOAP cite ce dépôt dans les en-têtes du fichier et reprend la structure générale du modèle *Just Record* (attente locale, enregistrement sur une durée en secondes) ; pour des séquences complètes (GOTO, UTC, etc.), les templates du dépôt restent la référence

### Étoiles binaires
- **PHOEBE2** : Bibliothèque Python pour la modélisation d'étoiles binaires à éclipses (https://phoebe-project.org/)
  - Utilisée pour la modélisation et l'analyse des systèmes binaires dans l'onglet "Étoiles Binaires"
  - Développée par le projet PHOEBE

### Analyse de données
- **emcee** : Bibliothèque MCMC pour l'ajustement de modèles (https://emcee.readthedocs.io/)
  - Utilisée pour l'analyse des variations de temps de transit (TTV)

- **statsmodels** : Bibliothèque d'analyse statistique (https://www.statsmodels.org/)
  - Utilisée pour les analyses statistiques avancées des courbes de lumière

- **pylightcurve** : Bibliothèque Python pour la modélisation et l'analyse de courbes de lumière d'exoplanètes (https://github.com/ucl-exoplanets/pylightcurve)
  - Développée par l'équipe UCL Exoplanets (University College London)
  - Utilisée pour la modélisation des transits d'exoplanètes, le calcul des coefficients d'assombrissement du limbe, et l'ajustement flexible de courbes de lumière multi-époques
  - Licence MIT

- **batman-package** : modèle analytique de transit (Mandel & Agol 2002 ; Kreidberg 2015) (https://github.com/lkreidberg/batman)
  - Auteure : **Laura Kreidberg** (Center for Astrophysics | Harvard & Smithsonian)
  - Utilisée dans le **workflow ExoPlanetPie natif** de NPOAP (panneau droit de l'onglet *Photométrie Exoplanètes*) pour générer les modèles de transit ajustés par **ultranest** ; calcul accéléré en C des courbes de lumière de transit primaire / secondaire avec assombrissement du limbe arbitraire
  - **Citation** : Kreidberg (2015), *PASP*, 127, 1161 ; DOI [10.1086/683602](https://doi.org/10.1086/683602)
  - Licence MIT

- **ExoTETHyS** : *Exoplanetary Transits Estimates by Hands of Yourself's Stars* — coefficients d'assombrissement du limbe stellaire à partir des grilles **Phoenix**, **Stagger**, **Atlas** (https://github.com/ucl-exoplanets/ExoTETHyS)
  - Auteurs : **Giuseppe Morello** et collaborateurs (UCL Exoplanets)
  - Utilisé dans le **workflow ExoPlanetPie natif** de NPOAP pour le calcul des LDC en loi **Claret-4** sur les filtres TESS, Kepler, Johnson, Cousins, Sloan, Gaia, etc. ; NPOAP implémente une **chaîne de repli** automatique (Phoenix_2018 → Stagger_2018 → Atlas_2000 → Phoenix_2012 → Atlas_1993) ainsi qu'un *clipping* des paramètres stellaires (Teff, log g, [Fe/H]) avant l'appel
  - **Citation** : Morello, Tsiaras, Howarth, Homeier (2020), *AJ*, 159, 75 ; DOI [10.3847/1538-3881/ab63dc](https://doi.org/10.3847/1538-3881/ab63dc)
  - Licence GPL-3.0

- **lightkurve** : Bibliothèque Python pour l'analyse de courbes TESS / Kepler / K2 (https://lightkurve.github.io/lightkurve/)
  - Développée par les **Kepler/TESS Guest Observer Office** (NASA Ames / STScI) et la communauté open-source
  - Utilisée dans le **workflow ExoPlanetPie natif** de NPOAP pour la recherche (`search_lightcurve`) et le téléchargement des courbes TESS / Kepler depuis le **MAST**, l'application des *quality bitmasks* et l'export CSV (BJD, flux, erreur) vers `output/exoplanetpie/1_RawFiles/`
  - **Citation** : Lightkurve Collaboration (2018), ASCL: 1812.013
  - Licence MIT

- **Wōtan (wotan)** : détrendage robuste de séries temporelles pour la photométrie de transits et, plus généralement, les courbes de lumière (https://github.com/hippke/wotan)
  - Développé par **Michael Hippke** et collaborateurs ; interface Python unifiée pour de nombreux estimateurs (biweight, médiane, splines, etc.)
  - Utilisé dans NPOAP en **option** dans le viewer d’affinage du temps de transit central (Analyse de données → période → courbe avec marqueurs) : `flatten` avec **masque transit** dérivé du Tc courant et de la largeur T14 saisie, puis normalisation locale hors transit
  - Utilisé également dans le **workflow ExoPlanetPie natif** (panneau droit de l'onglet *Photométrie Exoplanètes*) pour la normalisation / détrendage des courbes TESS/Kepler avant l'ajustement bayésien batman + ultranest
  - Utilisé également dans l’onglet **Photométrie astéroïdes** (analyse de courbe de lumière, cadre **Détrendage**) : méthodes **Wōtan biweight** et **Wōtan median** sur toute la série, via le module `core/asteroid_lc_detrend.py` (fenêtre temporelle en jours, automatique ou saisie ; les options Wōtan n’apparaissent que si le paquet `wotan` est installé)
  - **Citation** : Hippke, David, Mulders & Heller (2019), *AJ*, 158, 143 ; DOI [10.3847/1538-3881/ab3984](https://doi.org/10.3847/1538-3881/ab3984) ; arXiv:1906.00966
  - Licence MIT

- **HOPS (HOlomon Photometric Software)** : logiciel de photométrie exoplanètes intégré dans l'onglet Photométrie Exoplanètes
  - Auteurs : **Angelos Tsiaras** et **Konstantinos Karpouzas**
  - Copyright (c) 2017 Angelos Tsiaras and Konstantinos Karpouzas
  - Licence MIT
  - Les écrans d’export vers **ExoClock**, **ETD** et **AAVSO** renvoient notamment vers la base **Exoplanet Transit Database (ETD)** hébergée sur **VarAstro** (https://var.astro.cz/fr/Exoplanets)

- **SHOBS-FLUX** (Shiloh Hill Observatory Optical System Characterization) : caractérisation caméra / télescope (PTC, linéarité, dark current, zero point, extinction, seeing)
  - Vendoring runtime dans `external_apps/shobs_flux/` ; lancement depuis Accueil / Réduction de données
  - Import des profils caméra `~/.shobs/cameras/` vers `config.json` (gain, RN, dark, limite linéaire)
  - APIs embarquées (Réduction §1b) : Bench, Dark current, Check image, plan de tir PTC, **Sky** (ZP / extinction / seeing) via `core/shobs_flux_analysis.py`
  - **Historique** (`flux_runs.sqlite`) et **rapport système PDF** via `core/shobs_flux_history.py` / dialogue Accueil & Réduction
  - L’extinction mesurée (`config.json` bloc `onsky`) remplace le facteur fixe 0.1 mag/airmass dans `compute_zero_point` (pipelines exoplanètes / astéroïdes)
  - Licence **GNU GPL-3.0+**
  - DOI concept : [10.5281/zenodo.24115980](https://doi.org/10.5281/zenodo.24115980)
  - Upstream : https://github.com/SHOBS-S/SHOBS-FLUX

- **exoclock** : bibliothèque Python liée au projet **ExoClock** (éphémérides et catalogue d’exoplanètes en transit pour la mission ARIEL et le suivi au sol)
  - Utilisée dans la chaîne **HOPS** et, dans NPOAP, comme source complémentaire dans l’onglet **Observation de la nuit** (agrégation avec la NASA Exoplanet Archive)
  - Site du projet : https://www.exoclock.space/

### Simulation N-body
- **rebound** : Bibliothèque de simulation N-body pour systèmes planétaires (https://rebound.readthedocs.io/)
  - Utilisée pour les simulations gravitationnelles dans l'analyse de systèmes multiples (onglet Analyse de Données)
  - Permet de modéliser les interactions gravitationnelles entre planètes
  - **Citation** : Pour obtenir la citation exacte de rebound, utilisez :
    ```python
    import rebound
    sim = rebound.Simulation()
    sim.cite()
    ```
  - Référence principale : Rein & Spiegel (2015), "IAS15: a fast, adaptive, high-order integrator for gravitational dynamics, accurate to machine precision over a billion orbits", *MNRAS*, 446, 1424

- **ultranest** : Bibliothèque d'échantillonnage bayésien avec nested sampling (https://johannesbuchner.github.io/UltraNest/)
  - Auteur : **Johannes Buchner**
  - Utilisée pour le fitting bayésien des modèles N-body aux observations TTV (onglet Analyse de Données) **et** pour l'ajustement bayésien des transits dans le **workflow ExoPlanetPie natif** (panneau droit de l'onglet *Photométrie Exoplanètes*)
  - Alternative robuste aux méthodes MCMC pour l'estimation de paramètres
  - Utilise l'algorithme MLFriends (Buchner, 2014; 2019) pour le nested sampling Monte Carlo
  - Permet de dériver les distributions de probabilité a posteriori et l'évidence bayésienne
  - Référence : Buchner (2021), "UltraNest - a robust, general purpose Bayesian inference engine", *JOSS*, 6 (60), 3001

### Photométrie de transitoires
- **STDPipe** : Simple Transient Detection Pipeline (https://stdpipe.readthedocs.io/)
  - Auteur principal : Sergey Karpov
  - Utilisée pour la photométrie des transitoires : astrométrie automatique, soustraction d'images, détection de transitoires, photométrie calibrée
  - Fournit des méthodes avancées de détection (segmentation, DAOStarFinder, IRAFStarFinder)
  - Permet le téléchargement d'images de référence depuis Pan-STARRS, SDSS, DES
  - Licence MIT

- **sncosmo** : SuperNova Cosmology package (https://sncosmo.readthedocs.io/)
  - Utilisé dans l’onglet **Photométrie Transitoires** (boîte SN Ia) pour l’ajustement **SALT2/SALT3** des courbes de lumière
  - Utilisé avec les passbands Gaia (`gaia::g`, `gaia::gbp`, `gaia::grp`) et indicateurs de qualité de fit
  - Développé et maintenu par la communauté astronomique open-source (BSD)

### Autres bibliothèques
- **Pillow (PIL)** : Bibliothèque de traitement d'images (https://python-pillow.org/)
  - Utilisée pour le traitement et la manipulation d'images

- **reportlab** : Bibliothèque de génération de PDF (https://www.reportlab.com/)
  - Utilisée pour la génération de documentation PDF

- **requests** : Bibliothèque HTTP pour Python (https://requests.readthedocs.io/)
  - Utilisée pour les requêtes HTTP vers les services en ligne

- **specutils** : Bibliothèque Python pour l'analyse de données spectroscopiques (https://specutils.readthedocs.io/)
  - Utilisée pour la représentation, le chargement, la manipulation et l'analyse de spectres d'étoiles
  - Développée dans le cadre du projet Astropy

- **synphot** : Bibliothèque de photométrie synthétique (https://synphot.readthedocs.io/)
  - Utilisée pour les calculs de photométrie synthétique avec filtres U, B, V, R, I
  - Développée dans le cadre du projet Astropy

### Analyse de populations stellaires et spectroscopie avancée

- **Prospector** : Code Python pour inférer les propriétés des populations stellaires à partir de données photométriques et spectroscopiques (https://github.com/bd-j/prospector)
  - Utilisé pour l'analyse de spectres de galaxies et l'inférence de propriétés stellaires (âge, métallicité, extinction, redshift)
  - Utilise l'inférence bayésienne avec des modèles de populations stellaires simples (SSP - Simple Stellar Population)
  - Développé par l'équipe BD-J (Benjamin Johnson et collaborateurs)
  - **Important** : Le package `prospector` sur PyPI est un autre outil. La version astronomique doit être installée depuis GitHub : `pip install git+https://github.com/bd-j/prospector.git`

- **sedpy** : Bibliothèque Python pour la manipulation de SED (Spectral Energy Distribution) (https://github.com/bd-j/sedpy)
  - Utilisée par Prospector pour créer et manipuler des SED
  - **Important** : Doit être installée depuis GitHub (pas PyPI) pour avoir le module `observate` requis par Prospector
  - Développée par l'équipe BD-J

- **FSPS (Flexible Stellar Population Synthesis)** : Code Fortran avec bindings Python pour générer des modèles de populations stellaires (https://github.com/cconroy20/fsps)
  - Utilisé par Prospector comme moteur pour générer les templates SSP
  - Nécessite CMake et gfortran pour la compilation
  - Peut être installé depuis GitHub : `git clone https://github.com/dfm/python-fsps.git` puis `pip install .`
  - Développé par Charlie Conroy et collaborateurs

## Services et catalogues externes

## Remerciements spécifiques - Réduction / PTC

- **N.I.N.A. (Nighttime Imaging 'N' Astronomy)** : logiciel d'acquisition utilisé par de nombreux utilisateurs NPOAP pour préparer des sequences flats/bias (dont les sequences PTC).  
  Site : https://nighttime-imaging.eu/

- **Méthode Photon Transfer Curve (PTC)** : la fonctionnalité PTC de l'onglet Réduction s'appuie sur la pratique standard de caractérisation des détecteurs CCD/CMOS (relation variance-signal).  
  Référence historique courante : Janesick, *Photon Transfer* (SPIE Press).

### Catalogues astrométriques et photométriques
- **Gaia DR3** : Catalogue astrométrique de l'Agence Spatiale Européenne (ESA)
  - Utilisé comme référence astrométrique et photométrique (https://www.cosmos.esa.int/web/gaia)
  - Fournit positions précises, magnitudes, couleurs pour des millions d'étoiles

### Catalogues d'étoiles binaires et variables

- **VSX (AAVSO Variable Star Index)** : Catalogue des étoiles variables (https://www.aavso.org/vsx/)
  - Utilisé dans le sous-onglet **🌟 Étoiles Variables** pour la requête de champ, l’affichage des paramètres VSX et l’identification de la cible
  - Utilisé également pour la recherche de paramètres de systèmes binaires variables (onglet **Étoiles Binaires**)

- **AAVSO (American Association of Variable Star Observers)** : Organisation et standards de photométrie des étoiles variables (https://www.aavso.org/)
  - Le module `core/variable_star_aavso_export.py` produit des fichiers **CSV** compatibles **AAVSO Extended File Format** pour la soumission ou l’archivage des courbes de lumière
  - Documentation du format : https://www.aavso.org/aavso-extended-file-format

- **Gaia DR3 (ESA)** : comparateurs photométriques dans le sous-onglet **Étoiles Variables** (sélection T1 + étoiles de comparaison via VizieR, cône 45′, filtre |G − G_T1|)

- **SB9 (Ninth Catalog of Spectroscopic Binary Orbits)** : Catalogue d'orbites de binaires spectroscopiques (https://sb9.astro.ulb.ac.be/)
  - Utilisé pour récupérer les paramètres orbitaux de systèmes binaires spectroscopiques

- **DEBCat** : Database of Eclipsing Binaries Catalog (http://www.astro.keele.ac.uk/jkt/debcat/)
  - Utilisé pour les paramètres détaillés de systèmes binaires à éclipses

- **Washington Double Star Catalog (WDS)** : Catalogue des étoiles doubles de l'US Naval Observatory (https://crf.usno.navy.mil/wds/)
  - Format de référence pour les rapports de mesure de séparation binaire
  - Utilisé pour générer les rapports au format standard WDS dans l'onglet Easy Lucky Imaging

- **Minor Planet Center (MPC)** : Centre de données pour les astéroïdes et comètes (https://www.minorplanetcenter.net/)
  - **NEA.txt** : Catalogue des astéroïdes géocroiseurs (Near-Earth Asteroids)
  - **AllCometEls.txt** : Catalogue des éléments orbitaux de toutes les comètes
  - Utilisés dans l'onglet "Catalogues" → "Astéroïdes & Comètes" pour la sélection et le tri d'objets
  - Utilisés dans l’onglet **Observation de la nuit** ; les éphémérides détaillées et la magnitude apparente affichée (**Mag vis**) proviennent du service en ligne MPC (**MPES**, `cgi.minorplanetcenter.net`)

### Services d'astrométrie
- **Astrometry.net / NOVA** : Service d'astrométrie automatique (http://astrometry.net/, https://nova.astrometry.net/)
  - Utilisé pour la résolution de champs stellaires (plate solving) via NOVA (service en ligne) et solve-field (installation locale)
  - Développé par l'équipe Astrometry.net

### Services d'éphémérides
- **JPL Horizons** : Service d'éphémérides du Jet Propulsion Laboratory (NASA)
  - Utilisé pour obtenir les éphémérides des astéroïdes et planètes (https://ssd.jpl.nasa.gov/horizons/)

### Services de catalogues
- **Vizier** : Service de catalogues astronomiques du Centre de données astronomiques de Strasbourg (CDS)
  - Utilisé pour interroger les catalogues Gaia, **VSX**, et autres catalogues astronomiques (https://vizier.cds.unistra.fr/)
  - Module NPOAP `core/vizier_fov_query.py` : projection des objets catalogue sur le plan image (overlays VSX, comparateurs Gaia)

- **IRSA Dust Tools (IPAC/Caltech)** : service de poussière Galactique (SFD)  
  - Utilisé via `astroquery.irsa_dust` pour récupérer `E(B-V)` sur la ligne de visée (RA/Dec) dans la boîte SN Ia de l’onglet transitoires  
  - URL : https://irsa.ipac.caltech.edu/applications/DUST/

- **TESS EBS (Eclipsing Binary Stars)** : Catalogue des étoiles binaires à éclipses observées par TESS (https://tessebs.villanova.edu/)
  - Utilisé dans l'onglet "Catalogues" pour l'extraction de données d'étoiles binaires

- **Exoplanet.eu** : Base de données d'exoplanètes (https://exoplanet.eu/)
  - Utilisé dans l'onglet "Catalogues" pour l'extraction de données d'exoplanètes

### Images de référence
- **Pan-STARRS** : Panoramic Survey Telescope and Rapid Response System
  - Utilisé pour télécharger des images de référence profondes pour la soustraction d'images (https://panstarrs.stsci.edu/)

- **SDSS** : Sloan Digital Sky Survey
  - Utilisé pour télécharger des images de référence pour la soustraction d'images (https://www.sdss.org/)

- **DES** : Dark Energy Survey
  - Utilisé pour télécharger des images de référence pour les champs de l'hémisphère sud (https://www.darkenergysurvey.org/)

### Bases de données d'exoplanètes
- **NASA Exoplanet Archive** : Base de données d'exoplanètes (https://exoplanetarchive.ipac.caltech.edu/)
  - Utilisée pour les éphémérides et paramètres des exoplanètes (dont requêtes **TAP** sur la table `pscomppars` pour les planètes en transit dans l’onglet **Observation de la nuit**)

- **ExoClock** : projet communautaire de suivi des éphémérides d’exoplanètes en transit (https://www.exoclock.space/)
  - Catalogue **`planets_json`** interrogé en HTTP pour l’onglet **Observation de la nuit** ; module Python **`exoclock`** pour HOPS, le repli hors-ligne et les fonctions avancées (locate_planet, conversions temporelles)

- **VarAstro — Exoplanet Transit Database (ETD)** : portail de la section « étoiles variables et exoplanètes » de la Société astronomique tchèque (https://var.astro.cz/fr/Exoplanets)
  - L’interface web et l’API catalogue sont des services tiers ; l’accès API typique requiert une authentification — NPOAP désactive la source ETD tant qu’aucune session valide n’est disponible


## Outils et frameworks

- **NINA (Nighttime Imaging 'N' Astronomy)** : suite d’acquisition et d’automatisation pour l’astrophotographie de fond de ciel (https://nighttime-imaging.eu/)
  - NPOAP communique avec NINA via son **API avancée HTTP** (pilotage distant : connexion équipement, slew, capture, séquences) depuis l’onglet **Contrôle NINA** ; l’utilisateur doit installer et configurer NINA séparément sur le PC télescope

- **Python** : Langage de programmation (https://www.python.org/)
  - Langage principal de développement

- **Conda/Miniconda** : Système de gestion d'environnements et de paquets (https://docs.conda.io/)
  - Utilisé pour la gestion des environnements Python et des dépendances

- **Tkinter** : Bibliothèque d'interface graphique (incluse dans Python)
  - Utilisée pour l'interface utilisateur graphique

- **WSL (Windows Subsystem for Linux)** : Système pour exécuter Linux sur Windows (Microsoft)
  - Utilisé pour l'installation locale d'Astrometry.net sur Windows

## Techniques et méthodologies

- **Zero-Aperture-Astrometry** (Ben Sharkey) : Outil et méthodologie pour dériver des positions astrométriques zero-aperture à partir d’observations (https://github.com/bensharkey/Zero-Aperture-Astrometry)
  - La méthode zero-aperture de NPOAP (onglet Photométrie Astéroïdes) s’en inspire : fit linéaire pondéré des positions (ou des résidus moyens RA/Dec) en fonction de l’aperture photométrique, extrapolation à aperture = 0, et correction du WCS
  - Utilisé pour les observations au format ADES (PSV/XML) dans le projet original ; NPOAP adapte l’approche aux images FITS (plusieurs apertures en pixels, résidus moyens par aperture, puis extrapolation)
  - Licence GPL-3.0

- **REDUC** : Techniques de réduction d'images inspirées du tutoriel REDUC (http://www.astrosurf.com/hfosaf/reduc/tutoriel.htm)
  - **BestOf** : Tri et sélection des meilleures images selon leur qualité (FWHM, SNR, contraste)
  - **ELI (Easy Lucky Imaging)** : Empilement d'images avec alignement sub-pixel pour améliorer la résolution
  - **Centroiding** : Mesure précise des positions d'étoiles par centroïde
  - Utilisées dans l'onglet Easy Lucky Imaging pour le traitement d'images d'étoiles binaires

## Références bibliographiques

### Astrométrie
- **Farnocchia et al. (2022)** : "International Asteroid Warning Network Timing Campaign: 2019 XS", *Planetary Science Journal*, 3:156
  - Guide de référence pour les améliorations astrométriques implémentées dans NPOAP
  - DOI: https://doi.org/10.3847/PSJ/ac7224

### Étoiles binaires
- **Prša (2018)** : "Modeling and Analysis of Eclipsing Binary Stars: The Theory and Design Principles of PHOEBE"
  - Référence principale pour l'intégration de PHOEBE2
  - DOI: 10.1088/978-0-7503-1287-5

- **Laurent (2022)** : "La séparation linéaire utilisée pour déterminer le caractère physique d'une étoile double visuelle"
  - Article publié dans Étoiles Doubles - n°05 (Décembre 2022)
  - Auteur : Philippe Laurent (SAF - Commission des Étoiles Doubles, Président de l'Association Astronomie en Provence)
  - Méthode utilisée pour identifier les couples d'étoiles binaires physiques à partir des données Gaia DR3
  - Implémentée dans l'onglet "Catalogues" → "Étoiles Binaires" pour la création de catalogues de binaires physiques

### Simulation N-body
- **Rein & Spiegel (2015)** : "IAS15: a fast, adaptive, high-order integrator for gravitational dynamics, accurate to machine precision over a billion orbits", *Monthly Notices of the Royal Astronomical Society*, 446, 1424
  - Intégrateur utilisé par rebound pour les simulations N-body
  - DOI: https://doi.org/10.1093/mnras/stu2254

- **Rein & Liu (2012)** : "REBOUND: an open-source multi-purpose N-body code for collisional dynamics", *Astronomy & Astrophysics*, 537, A128
  - Article principal sur la bibliothèque rebound
  - DOI: https://doi.org/10.1051/0004-6361/201118085

### Échantillonnage bayésien
- **Buchner (2021)** : "UltraNest - a robust, general purpose Bayesian inference engine", *JOSS*, 6 (60), 3001
  - Article principal sur la bibliothèque UltraNest
  - URL: https://johannesbuchner.github.io/UltraNest/

- **Buchner (2014, 2019)** : MLFriends - Nested sampling Monte Carlo algorithm
  - Algorithme utilisé par UltraNest pour le nested sampling
  - Permet de dériver les distributions de probabilité a posteriori et l'évidence bayésienne

### Modélisation et ajustement de transits exoplanétaires (workflow ExoPlanetPie natif)

- **Mandel & Agol (2002)** : "Analytic Light Curves for Planetary Transit Searches", *ApJ*, 580, L171
  - Formules analytiques pour les courbes de transit avec assombrissement du limbe
  - DOI: [10.1086/345520](https://doi.org/10.1086/345520) — base théorique de `batman-package`

- **Kreidberg (2015)** : "batman: BAsic Transit Model cAlculatioN in Python", *PASP*, 127, 1161
  - Article principal de la bibliothèque batman utilisée par le workflow ExoPlanetPie natif
  - DOI: [10.1086/683602](https://doi.org/10.1086/683602)

- **Morello, Tsiaras, Howarth & Homeier (2020)** : "ExoTETHyS: Tools for Exoplanetary Transits around Host Stars", *AJ*, 159, 75
  - Article principal de la bibliothèque ExoTETHyS (coefficients de limb-darkening Claret-4 sur grilles Phoenix/Stagger/Atlas)
  - DOI: [10.3847/1538-3881/ab63dc](https://doi.org/10.3847/1538-3881/ab63dc)

- **Claret (2000)** : "A new non-linear limb-darkening law for LTE stellar atmosphere models", *A&A*, 363, 1081
  - Loi à quatre coefficients utilisée par ExoTETHyS et le workflow ExoPlanetPie natif

- **Lightkurve Collaboration (2018)** : "Lightkurve: Kepler and TESS time series analysis in Python", *Astrophysics Source Code Library*, ascl:1812.013
  - Bibliothèque utilisée pour les requêtes MAST et le téléchargement des courbes TESS / Kepler

- **dynesty** : Bibliothèque Python pour le nested sampling dynamique (https://dynesty.readthedocs.io/)
  - Utilisée par Prospector pour l'inférence bayésienne (alternative à emcee)
  - Permet l'estimation de l'évidence bayésienne et des distributions a posteriori
  - Référence : Speagle (2020), "Dynesty: a dynamic nested sampling package for estimating Bayesian posteriors and evidences", *MNRAS*, 493, 3132

**Notes** : 
- Pour obtenir la citation complète et à jour de rebound avec toutes les références, exécutez dans Python :
  ```python
  import rebound
  sim = rebound.Simulation()
  sim.cite()
  ```
- UltraNest utilise l'algorithme MLFriends (Buchner, 2014; 2019) pour le nested sampling Monte Carlo, permettant de dériver les distributions de probabilité a posteriori et l'évidence bayésienne.

## Licences

NPOAP est développé en utilisant des bibliothèques sous diverses licences open-source (principalement BSD, MIT, et Apache 2.0). Nous respectons les licences de toutes les bibliothèques utilisées.

Pour plus d'informations sur les licences spécifiques, consultez :
- Les fichiers LICENSE ou COPYRIGHT de chaque bibliothèque
- Les sites web officiels des projets mentionnés ci-dessus

## Remerciements spéciaux

Nous remercions particulièrement :
- L’**AAVSO** et les mainteneurs du catalogue **VSX** pour l’index des étoiles variables et les standards de soumission des observations
- Le **Rio Group** et les contributeurs de **SORA** (`sora-astro`) pour les capacités de prédiction et de cartographie d’occultations
- **Michael Camilleri** pour le dépôt **occultation-tools** (documentation et modèles autour de SharpCap et du timing)
- **Ben Sharkey** pour le projet Zero-Aperture-Astrometry et la méthodologie d’extrapolation zero-aperture
- Les équipes du **NASA Exoplanet Archive** / **IPAC** et du **Minor Planet Center** pour l’accès aux catalogues et services d’éphémérides
- Le projet **ExoClock** (groupe de travail éphémérides ARIEL) et les contributeurs du module **exoclock**
- La **Section étoiles variables et exoplanètes** de la **Société astronomique tchèque** pour **VarAstro** et la base **ETD**
- La communauté **Astropy** pour leurs outils fondamentaux
- L'équipe **STDPipe** (Sergey Karpov) pour leur pipeline de détection de transitoires
- Les développeurs de **sncosmo** pour l’écosystème d’ajustement des supernovae Ia (SALT2/SALT3)
- L'équipe **PHOEBE** pour leur bibliothèque de modélisation d'étoiles binaires
- L'équipe **BD-J** (Benjamin Johnson et collaborateurs) pour Prospector et sedpy, outils essentiels pour l'analyse spectroscopique avancée
- L'équipe **FSPS** (Charlie Conroy et collaborateurs) pour leur code de synthèse de populations stellaires
- L'équipe **UCL Exoplanets** pour **pylightcurve** et **ExoTETHyS** (Giuseppe Morello, Angelos Tsiaras et collaborateurs)
- **Laura Kreidberg** pour **batman-package**, modèle analytique de transit indispensable au workflow ExoPlanetPie natif
- **Johannes Buchner** pour **UltraNest** (nested sampling MLFriends), utilisé dans les ajustements bayésiens TTV et le workflow ExoPlanetPie natif
- Les équipes **Kepler / TESS Guest Observer Office** (NASA Ames / STScI) et la communauté **lightkurve** pour l'accès au MAST et l'écosystème d'analyse TESS / Kepler
- **Michael Hippke** et collaborateurs pour **Wōtan** (wotan), outil de référence pour le détrendage de courbes de lumière de transits
- La communauté astronomique open-source pour ses contributions continues et le partage de connaissances qui rendent des outils comme NPOAP possibles

---

**NPOAP - Acknowledgments**

*Merci à tous les développeurs et contributeurs de ces projets open-source qui rendent NPOAP possible.*

