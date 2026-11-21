"""
Helpers Tkinter / matplotlib pour tâches lancées en arrière-plan.

Évite ``Tcl_AsyncDelete`` et ``main thread is not in main loop`` lorsque le GC
détruit des objets Tk (figures matplotlib, PhotoImage, Variable) depuis un
thread worker pendant un traitement lourd (calibration, empilement, etc.).
"""
from __future__ import annotations

import gc
import logging
from collections.abc import Callable
from typing import Any

import tkinter as tk
from tkinter import TclError

logger = logging.getLogger(__name__)


def install_tk_safe_destructors() -> None:
    """
    Ignore proprement les erreurs Tcl dans ``Variable.__del__`` / ``Image.__del__``
    quand l'interpréteur ou la boucle principale n'est plus disponible.
    """
    try:
        if not getattr(tk.Variable, "_npoap_safe_del_installed", False):
            _orig_var_del = tk.Variable.__del__

            def _safe_var_del(self, _orig=_orig_var_del):
                try:
                    _orig(self)
                except (RuntimeError, TclError):
                    pass

            tk.Variable.__del__ = _safe_var_del
            tk.Variable._npoap_safe_del_installed = True
    except Exception:
        pass

    try:
        if hasattr(tk, "Image") and not getattr(tk.Image, "_npoap_safe_del_installed", False):
            _orig_img_del = tk.Image.__del__

            def _safe_img_del(self, _orig=_orig_img_del):
                try:
                    _orig(self)
                except (RuntimeError, TclError):
                    pass

            tk.Image.__del__ = _safe_img_del
            tk.Image._npoap_safe_del_installed = True
    except Exception:
        pass


def release_matplotlib_tk_refs() -> None:
    """Ferme les figures matplotlib et collecte le GC sur le thread appelant (UI)."""
    try:
        import matplotlib.pyplot as plt

        plt.close("all")
    except Exception:
        pass
    gc.collect()


def background_thread_entry() -> None:
    """À appeler au début d'un worker : évite le GC pendant le traitement lourd."""
    gc.disable()


def background_thread_exit(schedule_main_cleanup: Callable[[], Any]) -> None:
    """
    Réactive le GC et planifie le nettoyage matplotlib/Tk sur le thread principal.
    """
    gc.enable()
    try:
        schedule_main_cleanup()
    except Exception as exc:
        logger.debug("Planification nettoyage post-worker : %s", exc)
