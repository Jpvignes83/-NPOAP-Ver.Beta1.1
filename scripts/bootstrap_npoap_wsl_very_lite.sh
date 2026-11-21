#!/usr/bin/env bash
# Bootstrap APT minimal pour la distro WSL Ubuntu-NPOAP-Lite.
# Installe UNIQUEMENT ce dont NPOAP a besoin sous Linux :
#   - solve-field (astrometry.net local)
#   - toolchain C++/Fortran (KBMOD + FSPS/Prospector)
#   - git / cmake / python3-venv (clone + builds)
#
# NON inclus (volontairement) :
#   - ubuntu-desktop / snapd / docs
#   - paquets "Recommends"
#   - catalogues astrometry-data-* (multi-Go)
#   - CUDA / Miniconda (etapes optionnelles separees)
#
# Variables :
#   NPOAP_WSL_PROFILE = core | astrometry | full  (defaut: full)
#   NPOAP_WSL_USER    = nom d'utilisateur non-root a creer (optionnel)
#   SKIP_USER_SETUP=1 - ne pas creer d'utilisateur
set -euo pipefail

PROFILE="${NPOAP_WSL_PROFILE:-full}"
export DEBIAN_FRONTEND=noninteractive

die() { echo "[NPOAP-Lite] ERREUR: $*" >&2; exit 1; }

echo "[NPOAP-Lite] Bootstrap very_Lite (profil=${PROFILE})"

# --- Base utilisable (apt + sudo + reseau) ---
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates \
  apt-utils \
  sudo \
  locales \
  curl \
  wget \
  gnupg \
  less \
  nano \
  findutils \
  procps

# Locale minimale (evite warnings Python/apt)
if ! grep -q '^en_US.UTF-8' /etc/locale.gen 2>/dev/null; then
  echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen
fi
locale-gen en_US.UTF-8 >/dev/null
update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 || true

# --- Outils strictement requis pour compiler / cloner ---
# KBMOD : build-essential cmake git python3-dev python3-pip python3-venv
# Prospector/FSPS : + gfortran pkg-config
CORE_PKGS=(
  build-essential
  cmake
  git
  gfortran
  pkg-config
  python3
  python3-dev
  python3-pip
  python3-venv
)

apt-get install -y --no-install-recommends "${CORE_PKGS[@]}"

# --- Astrometry locale (solve-field) ---
# Ne PAS installer astrometry-data-* ici (indexes = Go).
if [[ "$PROFILE" == "astrometry" || "$PROFILE" == "full" ]]; then
  echo "[NPOAP-Lite] Installation astrometry.net (sans catalogues d'index)"
  apt-get install -y --no-install-recommends astrometry.net
fi

# Nettoyage caches APT
apt-get autoremove -y --purge || true
apt-get clean
rm -rf /var/lib/apt/lists/*

# --- Utilisateur non-root (sudo sans mot de passe pour apt NPOAP) ---
if [[ "${SKIP_USER_SETUP:-0}" != "1" ]]; then
  TARGET_USER="${NPOAP_WSL_USER:-}"
  if [[ -z "$TARGET_USER" ]]; then
    # Essaie de reprendre le nom Windows via /mnt/c/Users si present
    if [[ -d /mnt/c/Users ]]; then
      for d in /mnt/c/Users/*; do
        base="$(basename "$d")"
        case "$base" in
          Public|Default|Default\ User|All\ Users|'All Users'|desktop.ini) continue ;;
        esac
        if [[ -d "$d" && "$base" != *" "* ]]; then
          TARGET_USER="$base"
          break
        fi
      done
    fi
  fi
  TARGET_USER="${TARGET_USER:-npoap}"

  if id "$TARGET_USER" >/dev/null 2>&1; then
    echo "[NPOAP-Lite] Utilisateur deja present: $TARGET_USER"
  else
    echo "[NPOAP-Lite] Creation utilisateur: $TARGET_USER"
    useradd -m -s /bin/bash -G sudo "$TARGET_USER"
  fi
  # sudo NOPASSWD : les .bat NPOAP appellent sudo apt sans interaction
  echo "${TARGET_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-npoap-${TARGET_USER}"
  chmod 440 "/etc/sudoers.d/90-npoap-${TARGET_USER}"

  # wsl.conf : user par defaut
  mkdir -p /etc
  cat > /etc/wsl.conf <<EOF
[user]
default=${TARGET_USER}

[boot]
systemd=false
EOF
fi

# Resume disque
echo ""
echo "[NPOAP-Lite] Paquets indispensibles installes."
echo "[NPOAP-Lite] Occupations approximatives :"
df -h / 2>/dev/null | tail -n 1 || true
du -sh /usr 2>/dev/null || true
echo ""
echo "[NPOAP-Lite] Verification rapide :"
command -v solve-field >/dev/null 2>&1 && solve-field --help >/dev/null 2>&1 && echo "  solve-field : OK" || echo "  solve-field : absent (profil core ?)"
command -v gfortran >/dev/null && echo "  gfortran    : OK ($(gfortran --version | head -1))"
command -v cmake >/dev/null && echo "  cmake       : OK ($(cmake --version | head -1))"
command -v git >/dev/null && echo "  git         : OK"
command -v python3 >/dev/null && echo "  python3     : OK ($(python3 -V))"
echo ""
echo "[NPOAP-Lite] Suite optionnelle (hors very_Lite) :"
echo "  - Indexs astrometry : apt install astrometry-data-tycho2 (ou jeux cibles) — GROS"
echo "  - Miniconda WSL + conda create -n astroenv python=3.11  (KBMOD)"
echo "  - install_kbmod_wsl.bat / Installation_fsps/prospector.bat"
echo "[NPOAP-Lite] Termine."
