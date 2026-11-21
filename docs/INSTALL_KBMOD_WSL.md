# Installation de KBMOD sous WSL (Windows Subsystem for Linux)

NPOAP sur Windows n'installe pas KBMOD (compilation difficile sous MSVC).  
La detection KBMOD est lancee via WSL avec `scripts/kbmod_wsl_detect.py`, qui ecrit les candidats dans `kbmod_candidates.csv`.

## Prerequis

- WSL 2 avec une distribution Linux (Ubuntu recommandee)
- GPU NVIDIA (optionnel mais recommande)
- CUDA sous WSL si vous utilisez le GPU

## Installation automatique (Windows)

Double-cliquez sur **`install_kbmod_wsl.bat`** à la racine du projet (depuis une copie déjà décompressée). Par défaut, KBMOD est installé **uniquement** dans l’environnement conda **`astroenv`** (`.../envs/astroenv/bin/python3`), pas dans le Python système Ubuntu.

Le script :

1. vérifie que WSL est disponible ;
2. convertit le chemin Windows vers Linux (`wslpath`) ;
3. exécute **`scripts/install_kbmod_wsl.sh`** : `apt install` des outils de build (sauf **`install_kbmod_wsl.bat skip-apt`**), clone récursif de KBMOD dans `~/kbmod`, puis **`pip install -e`** dans **`astroenv`** avec **`coverage>=7.6.1`** pour Numba.

Mot de passe **sudo** possible dans la fenêtre WSL pour les paquets système.

### conda **astroenv** (comportement par défaut)

Sans argument (ou avec le mot **`astroenv`**), recherche du premier chemin parmi **`~/miniconda3`**, **`~/mambaforge`**, **`~/miniforge3`**, **`~/anaconda3`**, env **`astroenv`**. **`KBMOD_WSL_PYTHON`** dans `config.py` doit être ce même chemin (affiché à la fin du script).

```bat
install_kbmod_wsl.bat
install_kbmod_wsl.bat skip-apt
install_kbmod_wsl.bat /home/VOTREUSER/miniconda3/envs/astroenv/bin/python3
```

### Retirer une ancienne installation dans `~/.local` (Python système)

Si vous aviez installé KBMOD avec **`/usr/bin/python3`**, désinstallez-la pour ne garder que **`astroenv`** :

```bash
/usr/bin/python3 -m pip uninstall -y kbmod coverage
```

Ou sous Windows avant le `.bat` : **`set KBMOD_PURGE_USER_KBMOD=1`** puis relancer **`install_kbmod_wsl.bat`** (le script lance cette désinstallation automatiquement avant la vérification d’import).

### Python système Ubuntu (optionnel, non recommandé avec NPOAP conda)

Pour forcer **`/usr/bin/python3`** (ou le premier **`python3`** du PATH) :

```bat
install_kbmod_wsl.bat system
```

Si la détection depuis NPOAP échoue avec « No module named 'kbmod' », **`KBMOD_WSL_PYTHON`** dans `config.py` doit être **exactement** l’interpréteur affiché à la fin du script.

## Etapes d'installation manuelle

### 1) Ouvrir WSL

Depuis PowerShell/CMD:

```powershell
wsl
```

### 2) Mettre a jour Linux

```bash
sudo apt update
sudo apt upgrade -y
```

### 3) Installer les outils de build

```bash
sudo apt install -y build-essential cmake python3-dev python3-pip python3-venv git
```

### 4) (Optionnel) Installer CUDA sous WSL

Suivez la doc NVIDIA: <https://docs.nvidia.com/cuda/wsl-user-guide/>

Exemple Ubuntu:

```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit
```

Si besoin, redemarrez WSL:

1. Quittez WSL: `exit`
2. Dans **PowerShell/CMD Windows (hors WSL)**:

```powershell
wsl --shutdown
```

3. Rouvrez WSL (`wsl` ou `wsl -d Ubuntu`)

### 5) Cloner KBMOD avec sous-modules

```bash
cd ~
git clone --recursive https://github.com/dirac-institute/kbmod.git
cd kbmod
pip3 install --user -e .
```

Si vous avez deja clone sans `--recursive`:

```bash
cd ~/kbmod
git submodule update --init --recursive
pip3 install --user -e .
```

### 6) (Optionnel) Ajouter ~/.local/bin au PATH

```bash
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 7) Verification

```bash
python3 -c "import kbmod.search; from kbmod.core.psf import PSF; print('KBMOD OK')"
```

## Utilisation depuis NPOAP

Dans l'onglet Asteroides:

1. Chargez un dossier FITS
2. Cliquez "Detection KBMOD (via WSL)"
3. Lancez la detection
4. NPOAP execute `wsl python3 .../scripts/kbmod_wsl_detect.py ...`
5. Le script genere `kbmod_candidates.csv`

## Depannage rapide

- Erreur CMake / **`can't copy ... search.cpython-310-...so`** alors que la compilation mentionne **`cpython-312`** : CMake a pris **`/usr/bin/python3`** au lieu du Python conda. Réinstallez avec le script **`install_kbmod_wsl.sh`** à jour (il exporte **`CMAKE_ARGS`** et **`Python3_EXECUTABLE`** vers le même interprète que pip), ou sous WSL :  
  `CMAKE_ARGS="-DPython3_EXECUTABLE=$(which python3) -DPYTHON_EXECUTABLE=$(which python3)" pip install -e ~/kbmod` depuis **`conda activate astroenv`**.
- `No module named 'kbmod'`: KBMOD n'est pas installe dans le `python3` utilise par WSL
- Erreurs **numba** au chargement (`coverage.types`, `Tracer`, etc.) : Numba **0.62+** attend **`coverage>=7.6.1`** (voir [numba#10239](https://github.com/numba/numba/issues/10239)). Ni trop vieux ni une installation incomplete ne convient. Sous WSL : `python3 -m pip install --break-system-packages --user "coverage>=7.6.1"` (Python systeme PEP 668) ou dans conda : `pip install "coverage>=7.6.1"`. Le script `install_kbmod_wsl.sh` applique cette contrainte apres KBMOD.
- `No FITS files in directory`: verifier le chemin WSL (`/mnt/c/...`)
- Erreurs pybind11/CMake: relancer `git submodule update --init --recursive`
- Python 3.13: preferer Python 3.10/3.11

