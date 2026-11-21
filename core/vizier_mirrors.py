# core/vizier_mirrors.py
"""Miroirs VizieR / Sesame — contournement si le CDS Strasbourg est en panne (404)."""

from __future__ import annotations

import logging
import threading
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Miroirs recommandés par le CDS lorsque Strasbourg est indisponible :
# - IDIA (Afrique du Sud) : https://vizier.idia.ac.za/
# - CfA Harvard : https://vizier.cfa.harvard.edu/
# CDS Strasbourg en dernier : /viz-bin/votable y renvoie parfois 404.
_VIZIER_MIRROR_CANDIDATES: Tuple[str, ...] = (
    "vizier.idia.ac.za",
    "vizier.cfa.harvard.edu",
    "vizier.nao.ac.jp",
    "vizier.hia.nrc.ca",
    "vizier.ast.cam.ac.uk",
    "vizier.china-vo.org",
    "vizier.iucaa.ernet.in",
    "vizier.cds.unistra.fr",
)

# Sous-ensemble accepté par astroquery.vizier.conf.server (ConfigItem option list).
_ASTROQUERY_ALLOWED_SERVERS = frozenset(
    {
        "vizier.cds.unistra.fr",
        "vizier.cfa.harvard.edu",
        "vizier.nao.ac.jp",
        "vizier.hia.nrc.ca",
        "vizier.ast.cam.ac.uk",
        "vizier.iucaa.ernet.in",
        "vizier.china-vo.org",
    }
)

# Sesame (résolution de noms) — miroirs publiés par le CDS.
_SESAME_URLS: Tuple[str, ...] = (
    "https://vizier.idia.ac.za/viz-bin/nph-sesame/",
    "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/",
    "https://cds.unistra.fr/cgi-bin/nph-sesame/",
)

_lock = threading.Lock()
_cached_host: Optional[str] = None
_patched_vizier = False
_patched_sesame = False


def _probe_votable_mirror(host: str, timeout: float = 12.0) -> bool:
    """POST minimal sur /viz-bin/votable — True si une VOTable est renvoyée."""
    try:
        import requests
    except ImportError:
        return False
    url = f"https://{host}/viz-bin/votable"
    try:
        resp = requests.post(
            url,
            data={"-source": "I/355/gaiadr3", "-out.max": "1"},
            timeout=timeout,
        )
    except Exception as exc:
        logger.debug("VizieR probe %s : %s", host, exc)
        return False
    if resp.status_code != 200:
        logger.debug("VizieR probe %s : HTTP %s", host, resp.status_code)
        return False
    head = (resp.content or b"")[:400].lstrip()
    return head.startswith(b"<?xml") or b"<VOTABLE" in head.upper()


def pick_working_vizier_mirror(
    candidates: Optional[Sequence[str]] = None,
    *,
    force: bool = False,
) -> str:
    """
    Retourne un hôte VizieR qui répond correctement à /viz-bin/votable.

    Met en cache le premier miroir valide (thread-safe).
    """
    global _cached_host
    with _lock:
        if _cached_host and not force:
            return _cached_host
        hosts: List[str] = list(candidates or _VIZIER_MIRROR_CANDIDATES)
        last_err = ""
        for host in hosts:
            if _probe_votable_mirror(host):
                _cached_host = host
                logger.info("VizieR : miroir actif = %s", host)
                return host
            last_err = host
        fallback = "vizier.cfa.harvard.edu"
        if "vizier.idia.ac.za" in hosts:
            fallback = "vizier.idia.ac.za"
        elif hosts:
            fallback = hosts[0]
        _cached_host = fallback
        logger.warning(
            "VizieR : aucun miroir n'a répondu correctement "
            "(dernier testé=%s) — utilisation de %s",
            last_err,
            fallback,
        )
        return fallback


def ensure_sesame_mirrors() -> Tuple[str, ...]:
    """
    Oriente Astropy Sesame vers IDIA puis Harvard (recommandation CDS).

    Réf. CDS : https://vizier.idia.ac.za/viz-bin/Sesame
               https://vizier.cfa.harvard.edu/viz-bin/Sesame
    """
    global _patched_sesame
    urls = _SESAME_URLS
    try:
        from astropy.coordinates.name_resolve import sesame_url

        sesame_url.set(list(urls))
        _patched_sesame = True
        logger.info("Sesame : miroirs = %s", ", ".join(urls))
    except Exception as exc:
        logger.debug("Impossible de configurer sesame_url : %s", exc)
    return urls


def ensure_astroquery_vizier_mirror(*, force_probe: bool = False) -> str:
    """
    Force astroquery.vizier à utiliser un miroir fonctionnel (IDIA / Harvard…).

    Nécessaire car ``VizierClass.__init__`` fige ``vizier_server=conf.server``
    à l'import : changer ``conf.server`` après coup ne suffit pas, et SORA
    instancie ``Vizier(...)`` sans passer ``vizier_server=``.

    Note : ``vizier.idia.ac.za`` n'est pas dans la liste ConfigItem d'astroquery,
    mais fonctionne via ``VIZIER_SERVER`` (patch ``__init__``).
    """
    global _patched_vizier
    ensure_sesame_mirrors()
    host = pick_working_vizier_mirror(force=force_probe)

    try:
        from astroquery.vizier import VizierClass, conf
    except ImportError:
        return host

    if host in _ASTROQUERY_ALLOWED_SERVERS:
        try:
            conf.server = host
        except Exception as exc:
            logger.debug("Impossible d'écrire conf.server=%s : %s", host, exc)
    else:
        # IDIA etc. : garder Harvard dans conf pour les outils qui lisent conf.server
        try:
            conf.server = "vizier.cfa.harvard.edu"
        except Exception:
            pass

    try:
        VizierClass.VIZIER_SERVER = host  # type: ignore[attr-defined]
    except Exception:
        pass

    if not _patched_vizier:
        _orig_init = VizierClass.__init__

        def _init_with_mirror(self, *args, **kwargs):
            if "vizier_server" not in kwargs:
                kwargs["vizier_server"] = pick_working_vizier_mirror()
            return _orig_init(self, *args, **kwargs)

        def _server_to_url_mirror(self, return_type="votable"):
            # Force le miroir actif à chaque requête (ignore le défaut CDS figé).
            active = pick_working_vizier_mirror()
            try:
                self.VIZIER_SERVER = active
            except Exception:
                pass
            assert return_type in (
                "votable",
                "asu-tsv",
                "asu-fits",
                "asu-text",
                "asu-binfits",
            )
            return f"https://{active}/viz-bin/{return_type}"

        VizierClass.__init__ = _init_with_mirror  # type: ignore[method-assign]
        VizierClass._server_to_url = _server_to_url_mirror  # type: ignore[method-assign]
        _patched_vizier = True
        logger.debug("astroquery.vizier patché (miroir VizieR IDIA/Harvard)")

    return host
