# WSL very_Lite pour NPOAP (Beta 1.1)

Analyse des éléments Linux **strictement indispensables** au fonctionnement des parties WSL de NPOAP, et construction d’une distribution **very_Lite** à la place d’Ubuntu Store complète.

## Pourquoi Ubuntu complet est trop gros

`install_ubuntu_wsl.bat` lance `wsl --install -d Ubuntu` (image Microsoft Store). Cette image embarque typiquement :

- métapaquets « server / minimal » étendus ;
- **snapd**, documentation, paquets *Recommends* ;
- outils hors périmètre NPOAP.

NPOAP n’utilise WSL que pour trois fonctions. Tout le reste est du poids mort.

## Ce que NPOAP appelle réellement sous WSL

| Fonction | Point d’entrée | Binaire / stack Linux |
|----------|----------------|------------------------|
| Astrométrie locale | `core/astrometry.py` → `wsl bash -lc "/usr/bin/solve-field ..."` | paquet `astrometry.net` |
| Détection KBMOD | `install_kbmod_wsl.sh` + `scripts/kbmod_wsl_detect.py` | `build-essential`, `cmake`, `git`, Python **conda `astroenv` ≥ 3.11** |
| Prospector / FSPS | `Installation_fsps/` (manuel) + `NPOAP_PROSPECTOR_BACKEND=wsl` | `gfortran`, `cmake`, `git`, `python3-venv` |

Hors WSL (pas dans very_Lite) : NPOAP GUI, Conda Windows `astroenv`, NOVA Astrometry, PHOEBE, SORA, etc.

## Strictement indispensable (système)

### Socle

- `ca-certificates`, `sudo`, `locales`, `curl`/`wget`, `gnupg`

### Compilation partagée (KBMOD + FSPS)

- `build-essential` (gcc/g++/make)
- `cmake`
- `git`
- `gfortran` (FSPS)
- `pkg-config`
- `python3`, `python3-dev`, `python3-pip`, `python3-venv`

### Astrométrie locale

- `astrometry.net` uniquement  
- **Ne pas** installer `astrometry-data-*` par défaut (catalogues = plusieurs Go). Les indexs se choisissent à part selon le champ / le FOV.

### Explicitément exclus

| Élément | Raison |
|---------|--------|
| Ubuntu Desktop / GUI | Inutile sous WSL pour NPOAP |
| snapd / cloud-init étendu | Poids + complexité |
| APT *Recommends* | Installés via `--no-install-recommends` |
| CUDA toolkit | Optionnel GPU KBMOD seulement |
| Miniconda / `astroenv` | Nécessaire **seulement** pour KBMOD ; install séparée |
| Catalogues astrometry | Optionnels et volumineux |
| `apt upgrade` complet | Non requis pour démarrer |

## Taille indicative

| Étape | Ordre de grandeur |
|-------|-------------------|
| Ubuntu Base 24.04 tarball | ~29 Mo |
| Rootfs + toolchain + astrometry.net (sans index) | ~0,6–1,2 Go |
| Ubuntu Store « classique » | souvent 2–4 Go+ avant outils NPOAP |
| + indexs astrometry complets | plusieurs Go supplémentaires |
| + Miniconda + KBMOD | ~0,5–1,5 Go selon deps |

## Installation

Prérequis : WSL2 déjà installé (`install_wsl.bat`, redémarrage si demandé).

```bat
install_ubuntu_wsl_very_lite.bat
```

Profils :

```bat
install_ubuntu_wsl_very_lite.bat full         REM defaut : toolchain + astrometry.net
install_ubuntu_wsl_very_lite.bat core         REM toolchain seule (sans solve-field)
install_ubuntu_wsl_very_lite.bat astrometry   REM idem full
```

Effet :

1. Télécharge `ubuntu-base-24.04.5-base-amd64.tar.gz`
2. `wsl --import Ubuntu-NPOAP-Lite` sous `%LOCALAPPDATA%\NPOAP\WSL\`
3. Exécute `scripts/bootstrap_npoap_wsl_very_lite.sh` (root, `--no-install-recommends`)
4. Crée un utilisateur (nom Windows) avec sudo NOPASSWD et le met en défaut dans `/etc/wsl.conf`

Puis, selon besoin :

```bat
install_astrometry_wsl.bat          REM si vous etiez en profil core
REM Sous WSL : installer Miniconda, puis
REM   conda create -n astroenv python=3.11 -y
install_kbmod_wsl.bat
```

## Intégration `install_optionnels.bat`

La séquence optionnelle propose **very_Lite** à la place d’Ubuntu Store. L’ancien script `install_ubuntu_wsl.bat` reste disponible pour une Ubuntu complète.

## Vérifications

```powershell
wsl -d Ubuntu-NPOAP-Lite -- solve-field --help
wsl -d Ubuntu-NPOAP-Lite -- gfortran --version
wsl -d Ubuntu-NPOAP-Lite -- cmake --version
```

## Désinstallation

```powershell
wsl --unregister Ubuntu-NPOAP-Lite
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\NPOAP\WSL\Ubuntu-NPOAP-Lite"
```
