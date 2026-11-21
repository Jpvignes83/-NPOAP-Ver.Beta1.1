#!/usr/bin/env bash
# Assure conda env astroenv sous WSL en Python >= 3.11 (requis pour KBMOD).
# Appele par install_optionnels.bat avant install_kbmod_wsl.bat.
set -euo pipefail

die() {
  echo "[ECHEC] $*" >&2
  exit 1
}

CONDA_SH=""
for c in \
  "$HOME/miniconda3/etc/profile.d/conda.sh" \
  "$HOME/mambaforge/etc/profile.d/conda.sh" \
  "$HOME/miniforge3/etc/profile.d/conda.sh" \
  "$HOME/anaconda3/etc/profile.d/conda.sh"; do
  if [[ -f "$c" ]]; then
    CONDA_SH="$c"
    break
  fi
done

[[ -n "$CONDA_SH" ]] || die "conda introuvable dans WSL. Installez Miniconda sous WSL, puis : conda create -n astroenv python=3.11 -y"

# shellcheck source=/dev/null
source "$CONDA_SH"

need_create=1
if conda env list | grep -E '^astroenv[[:space:]]' >/dev/null 2>&1; then
  pyv="$(conda run -n astroenv python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  echo "[INFO] astroenv WSL actuel: Python ${pyv:-inconnu}"
  major="${pyv%%.*}"
  minor="${pyv#*.}"
  minor="${minor%%.*}"
  if [[ -n "$major" && -n "$minor" ]]; then
    if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 11 ]]; }; then
      need_create=0
    fi
  fi
else
  echo "[INFO] Env astroenv absent sous WSL."
fi

if [[ "$need_create" -eq 0 ]]; then
  echo "[OK] astroenv WSL deja en Python >= 3.11"
  exit 0
fi

echo "[INFO] Recreation de astroenv avec Python 3.11..."
echo "       Commandes equivalentes :"
echo "         conda remove -n astroenv --all -y"
echo "         conda create -n astroenv python=3.11 -y"
echo "         # puis relancer install_kbmod_wsl.bat"

conda env remove -n astroenv -y 2>/dev/null || true
conda create -n astroenv python=3.11 -y
conda run -n astroenv python -V

echo "[OK] conda create -n astroenv python=3.11 -y termine."
echo "[OK] Prochaine etape : install_kbmod_wsl.bat"
