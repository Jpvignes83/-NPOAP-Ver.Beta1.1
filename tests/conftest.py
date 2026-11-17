"""Configuration pytest : rend le paquet racine (core/, gui/, utils/) importable
quel que soit le répertoire de lancement (``pytest tests/`` ou ``python -m pytest``).

Sans cela, ``pytest tests/`` ne trouvait pas ``core`` et les tests étaient
silencieusement ignorés (skip) à cause du ``except ImportError`` des modules de test.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Backend matplotlib sans affichage (CI / serveurs sans écran)
os.environ.setdefault("MPLBACKEND", "Agg")
