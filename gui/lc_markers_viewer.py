# gui/lc_markers_viewer.py
"""
Viewer de la courbe de lumière avec les marqueurs de période du périodogramme
reportés sur la courbe : une couleur par période, transits ajustables à la main.
Après validation : création d'un fichier mid-time.csv par période/couleur.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import pandas as pd
import logging
from pathlib import Path

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.ticker import MaxNLocator, ScalarFormatter

from core.transit_fitter import fit_trapezoid_transit, model_flux, slice_window
from core.wotan_detrend import (
    default_window_length,
    flatten_segment_with_transit_mask,
    is_wotan_available,
    transit_boolean_mask,
)

logger = logging.getLogger(__name__)

PERIOD_COLORS = [
    '#e74c3c', '#27ae60', '#3498db', '#9b59b6', '#f39c12', '#1abc9c',
]

MAX_DISPLAY_POINTS = 80_000
WOTAN_METHOD_CHOICES = ("biweight", "median", "mean", "huber", "lowess")


def _downsample(time, flux, max_pts=MAX_DISPLAY_POINTS):
    n = len(time)
    if n <= max_pts:
        return time, flux
    idx = np.linspace(0, n - 1, max_pts, dtype=int)
    return time[idx], flux[idx]


def _transit_windows(time, period, t0):
    t_min, t_max = time.min(), time.max()
    if period <= 0:
        return []
    e0 = int(np.floor((t_min - t0) / period))
    e1 = int(np.ceil((t_max - t0) / period)) + 1
    return [(ep, t0 + ep * period) for ep in range(e0, e1 + 1) if t_min <= t0 + ep * period <= t_max]


def _pick_transit_mid_time(t, f, tc_calc, half_window):
    """
    Temps du minimum de flux autour de tc_calc, en évitant les creux parasites :
    on ne garde que les points du quartile inférieur du flux dans la fenêtre,
    puis le minimum parmi eux ; sinon minimum global dans la fenêtre.

    Retourne None s'il n'existe aucune mesure (temps + flux finis) dans la fenêtre
    (trou dans la courbe, pas de données) — pas de marqueur / mid-time dans ce cas.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    mask = np.abs(t - tc_calc) <= half_window
    if not np.any(mask):
        return None
    lt = t[mask]
    lf = f[mask]
    ok = np.isfinite(lt) & np.isfinite(lf)
    lt, lf = lt[ok], lf[ok]
    if len(lt) == 0:
        return None
    if len(lt) == 1:
        return float(lt[0])
    q25 = float(np.percentile(lf, 25))
    cand = lf <= q25
    if np.count_nonzero(cand) >= 2:
        idx = np.where(cand)[0]
        j = idx[int(np.argmin(lf[cand]))]
    else:
        j = int(np.argmin(lf))
    return float(lt[j])


class LCMarkersViewer(tk.Toplevel):
    """
    Fenêtre affichant la courbe de lumière avec les périodes (marqueurs du périodogramme)
    reportées en couleurs. Ajustement manuel des mid-times par clic.
    Export : un mid-time.csv par période (couleur).
    """

    def __init__(
        self,
        parent,
        time,
        flux,
        periods,
        filename_prefix="",
        extra_export_columns=None,
        on_export_callback=None,
        on_validate_tc_callback=None,
        on_skip_tc_callback=None,
        expected_epoch=None,
    ):
        super().__init__(parent)
        self.title("Courbe de lumière")
        self.geometry("1450x880")
        self.minsize(1280, 820)

        time = np.asarray(time, dtype=float)
        flux = np.asarray(flux, dtype=float)
        self.time_full = time
        self.flux_full = flux
        self.time, self.flux = _downsample(time, flux)
        self.t0_display = float(np.min(time))
        self.filename_prefix = str(filename_prefix or "")
        self.extra_export_columns = dict(extra_export_columns or {})
        self.on_export_callback = on_export_callback
        self.on_validate_tc_callback = on_validate_tc_callback
        self.on_skip_tc_callback = on_skip_tc_callback
        self.expected_epoch = None if expected_epoch is None else int(expected_epoch)

        # Liste de {period, t0, depth, duration, color, mid_times}
        self.periods_data = []
        for i, P in enumerate(periods):
            P = float(P)
            # Pas d'estimation de profondeur: depth fixé à 0.0
            t0 = float(np.nanmin(time)) if len(time) else 0.0
            depth = 0.0
            duration = max(0.01, P * 0.05)
            self.periods_data.append({
                'period': P,
                't0': t0,
                'depth': depth,
                'duration': duration,
                'color': PERIOD_COLORS[i % len(PERIOD_COLORS)],
                'mid_times': {},
            })

        self.selected_index = tk.IntVar(value=0)
        self.display_relative = tk.BooleanVar(value=True)
        self._fit_half_win_var = tk.StringVar(value="")
        self._fit_width_var = tk.StringVar(value="")
        self._fit_ing_var = tk.StringVar(value="0.25")
        self._fit_slope_var = tk.BooleanVar(value=True)
        self._fit_status_var = tk.StringVar(value="")
        self._fit_epoch_var = tk.StringVar(value="")
        self._wotan_var = tk.BooleanVar(value=False)
        self._wotan_wl_var = tk.StringVar(value="")
        self._wotan_method_var = tk.StringVar(value="biweight")
        self._wotan_ok = is_wotan_available()
        self._last_fit = None
        self._last_fit_idx = None
        self._last_fit_epoch = None
        self._build_ui()

    @staticmethod
    def _unpack_mid_time_value(value):
        """
        Normalise un enregistrement mid-time.
        Compatibilité:
          - ancien format: (tc, err)
          - nouveau format: (tc, err, source) avec source in {"auto","manual"}
        """
        if isinstance(value, (tuple, list)):
            if len(value) >= 3:
                return float(value[0]), float(value[1]), str(value[2])
            if len(value) == 2:
                return float(value[0]), float(value[1]), "auto"
        return float(value), 0.0, "auto"

    def _build_ui(self):
        main = ttk.Frame(self, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(main)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        if callable(self.on_validate_tc_callback):
            ttk.Button(
                toolbar,
                text="✅ Valider Tc (séquentiel)",
                command=self._validate_tc_sequential,
            ).pack(side=tk.LEFT, padx=2)
            ttk.Button(
                toolbar,
                text="⏭ Passer (skip)",
                command=self._skip_tc_sequential,
            ).pack(side=tk.LEFT, padx=2)
            ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Checkbutton(
            toolbar,
            text="Abscisses : jours depuis le début",
            variable=self.display_relative,
            command=self._redraw,
        ).pack(side=tk.LEFT, padx=2)

        left = ttk.Frame(main, padding=6)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        self.listbox = tk.Listbox(left, height=12, width=32, selectmode=tk.SINGLE, font=("Consolas", 9))
        self.listbox.pack(fill=tk.Y, pady=2)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        fit_fr = ttk.LabelFrame(left, text="Fit Tc", padding=6)
        fit_fr.pack(fill=tk.X, pady=(8, 2))
        ttk.Label(fit_fr, text="Époque").pack(anchor=tk.W)
        self._fit_epoch_combo = ttk.Combobox(
            fit_fr,
            textvariable=self._fit_epoch_var,
            values=[],
            state="readonly",
            width=22,
        )
        self._fit_epoch_combo.pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(fit_fr, text="Demi-fenêtre (j)").pack(anchor=tk.W)
        ttk.Entry(fit_fr, textvariable=self._fit_half_win_var, width=12).pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(fit_fr, text="Largeur transit T14 (j)").pack(anchor=tk.W)
        ttk.Entry(fit_fr, textvariable=self._fit_width_var, width=12).pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(fit_fr, text="Ingress (fraction)").pack(anchor=tk.W)
        ttk.Entry(fit_fr, textvariable=self._fit_ing_var, width=12).pack(anchor=tk.W, pady=(0, 4))
        ttk.Checkbutton(fit_fr, text="Ajuster pente baseline", variable=self._fit_slope_var).pack(anchor=tk.W, pady=(0, 4))
        ttk.Checkbutton(fit_fr, text="Appliquer Wotan avant fit", variable=self._wotan_var).pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(fit_fr, text="Fenêtre Wotan (j), vide=auto").pack(anchor=tk.W)
        self._wotan_wl_entry = ttk.Entry(fit_fr, textvariable=self._wotan_wl_var, width=12)
        self._wotan_wl_entry.pack(anchor=tk.W, pady=(0, 3))
        ttk.Label(fit_fr, text="Méthode Wotan").pack(anchor=tk.W)
        self._wotan_method_combo = ttk.Combobox(
            fit_fr,
            textvariable=self._wotan_method_var,
            values=WOTAN_METHOD_CHOICES,
            state="readonly",
            width=12,
        )
        self._wotan_method_combo.pack(anchor=tk.W, pady=(0, 4))
        if not self._wotan_ok:
            self._wotan_wl_entry.state(["disabled"])
            self._wotan_method_combo.state(["disabled"])
            self._wotan_var.set(False)
        ttk.Button(fit_fr, text="Lancer fit Tc", command=self._open_transit_fit_dialog).pack(fill=tk.X, pady=(0, 3))
        ttk.Button(fit_fr, text="Appliquer Tc fit", command=self._apply_inline_fit).pack(fill=tk.X)
        ttk.Label(fit_fr, textvariable=self._fit_status_var, font=("", 8), wraplength=240, foreground="gray").pack(anchor=tk.W, pady=(4, 0))

        for i, d in enumerate(self.periods_data):
            self.listbox.insert(tk.END, f"P={d['period']:.5f} j")
        self.listbox.selection_set(0)
        self._refresh_fit_epoch_controls()

        fig_frame = ttk.Frame(main)
        fig_frame.pack(fill=tk.BOTH, expand=True)
        self.fig = plt.Figure(figsize=(9, 5), facecolor='white')
        self.ax = self.fig.add_subplot(111, facecolor='white')
        self.canvas = FigureCanvasTkAgg(self.fig, master=fig_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.nav_toolbar = NavigationToolbar2Tk(self.canvas, fig_frame)
        self.nav_toolbar.update()
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self._redraw()

    def _on_select(self, event):
        sel = self.listbox.curselection()
        if sel:
            self.selected_index.set(sel[0])
            self._refresh_fit_epoch_controls()

    def _refresh_listbox(self):
        """Met à jour la liste des périodes avec le nombre actuel de mid-times."""
        self.listbox.delete(0, tk.END)
        for i, d in enumerate(self.periods_data):
            self.listbox.insert(tk.END, f"P={d['period']:.5f} j")
        self.listbox.selection_set(min(self.selected_index.get(), len(self.periods_data) - 1))
        self._refresh_fit_epoch_controls()

    def _refresh_fit_epoch_controls(self):
        idx = self.selected_index.get()
        if idx < 0 or idx >= len(self.periods_data):
            self._fit_epoch_combo.configure(values=[])
            self._fit_epoch_var.set("")
            return
        d = self.periods_data[idx]
        P = float(d.get("period") or 0.1)
        dur = float(d.get("duration") or max(0.02, P * 0.05))
        if not self._fit_half_win_var.get().strip():
            self._fit_half_win_var.set(f"{max(0.02, min(P * 0.08, 0.6)):.6f}")
        if not self._fit_width_var.get().strip():
            self._fit_width_var.set(f"{dur:.6f}")
        mts = d.get("mid_times") or {}
        keys = sorted(mts.keys())
        values = [str(int(ep)) for ep in keys]
        self._fit_epoch_combo.configure(values=values)
        if values:
            if self.expected_epoch is not None and str(int(self.expected_epoch)) in values:
                self._fit_epoch_var.set(str(int(self.expected_epoch)))
            elif self._fit_epoch_var.get() not in values:
                self._fit_epoch_var.set(values[0])
        else:
            self._fit_epoch_var.set("")

    def _fill_all_mid_times(self):
        """Recalcule tous les mid-times automatiquement via minimum local autour de chaque transit théorique."""
        if self.time_full is None or len(self.time_full) == 0:
            messagebox.showinfo("Valider", "Aucune courbe chargée.")
            return
        t = np.asarray(self.time_full, dtype=float)
        f = np.asarray(self.flux_full, dtype=float)
        if len(t) != len(f) or len(t) == 0:
            messagebox.showinfo("Valider", "Données LC invalides.")
            return
        total_added = 0
        for d in self.periods_data:
            P, T0 = d['period'], d['t0']
            if not np.isfinite(P) or not np.isfinite(T0):
                continue
            # Recalcule tous les points pour éviter de conserver d'anciens mid-times incohérents
            # (ex: issus d'un ancien mode de validation à l'épheméride).
            mid_times = {}
            # Fenêtre de recherche autour du transit théorique: 5% de P, bornée.
            half_window = max(0.01, min(P * 0.05, 0.4))
            for epoch, tc_calc in _transit_windows(self.time_full, P, T0):
                tc_obs = _pick_transit_mid_time(t, f, tc_calc, half_window)
                if tc_obs is not None:
                    mid_times[epoch] = (tc_obs, 0.0, "auto")
                    total_added += 1
            d['mid_times'] = mid_times
        self._refresh_listbox()
        self._redraw()
        messagebox.showinfo(
            "Valider",
            f"Mid-times auto-recalculés (fenêtres avec données uniquement). {total_added} point(s). "
            "Les époques sans mesure de flux dans la fenêtre sont ignorées. "
            "Vous pouvez encore ajuster un point en cliquant sur la courbe."
        )

    # Nombre max de bandes de transit dessinées par période (évite fond rouge avec ~1000 transits)
    MAX_DRAWN_TRANSITS = 200

    def _redraw(self):
        self.ax.clear()
        self.ax.set_facecolor('white')
        rel = self.display_relative.get()
        t0 = self.t0_display
        # Courbe en premier (toujours visible)
        if self.time is not None and self.flux is not None:
            x = (self.time - t0) if rel else self.time
            self.ax.plot(x, self.flux, 'k.', markersize=2.2, alpha=0.8)
        # Puis bandes et lignes (limité pour ne pas remplir tout l'écran)
        for i, d in enumerate(self.periods_data):
            P, T0 = d['period'], d['t0']
            if not np.isfinite(P) or not np.isfinite(T0):
                continue
            color = d['color']
            mid_times = d.get('mid_times') or {}
            n_drawn = 0
            # Uniquement les époques réellement validées (données de flux dans la fenêtre ou clic manuel)
            for epoch in sorted(mid_times.keys()):
                if n_drawn >= self.MAX_DRAWN_TRANSITS:
                    break
                tc_obs, _, _ = self._unpack_mid_time_value(mid_times[epoch])
                x_tc = (tc_obs - t0) if rel else tc_obs
                if not np.isfinite(x_tc):
                    continue
                half = max(P * 0.02, 0.01)
                self.ax.axvspan(x_tc - half, x_tc + half, alpha=0.25, color=color)
                self.ax.axvline(x_tc, color=color, lw=1.2, alpha=0.9)
                n_drawn += 1
        self.ax.set_ylabel("Flux (rel.)")
        if rel:
            self.ax.set_xlabel("Jours depuis le début")
            title = f"Courbe de lumière – t₀ = {t0:.2f}"
        else:
            self.ax.set_xlabel("Temps (BJD-TDB ou JD)")
            title = "Courbe de lumière"
        self.ax.set_title(title)
        self.ax.grid(True, alpha=0.3)
        if self.time is not None:
            x_min = (self.time.min() - t0) if rel else self.time.min()
            x_max = (self.time.max() - t0) if rel else self.time.max()
            self.ax.set_xlim(x_min, x_max)
        self.ax.xaxis.set_major_locator(MaxNLocator(nbins=8, integer=False))
        fmt = ScalarFormatter()
        fmt.set_scientific(False)
        fmt.set_powerlimits((-10, 10))
        self.ax.xaxis.set_major_formatter(fmt)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _on_click(self, event):
        # Si l'utilisateur est en mode zoom/pan, ne pas déclencher
        # l'ajout/modification de transit par clic.
        mode = getattr(self.nav_toolbar, 'mode', None) or getattr(self.nav_toolbar, '_active', None)
        if mode is not None and str(mode).strip().upper() not in ("", "NONE"):
            return

        if event.inaxes != self.ax or event.xdata is None or self.time is None:
            return
        rel = self.display_relative.get()
        t0 = self.t0_display
        t_click = event.xdata + t0 if rel else event.xdata
        idx = self.selected_index.get()
        if idx < 0 or idx >= len(self.periods_data):
            return
        d = self.periods_data[idx]
        P, T0 = d['period'], d['t0']
        epoch = int(round((t_click - T0) / P))
        d.setdefault('mid_times', {})[epoch] = (t_click, 0.0, "manual")
        self.listbox.delete(idx)
        self.listbox.insert(idx, f"P={d['period']:.5f} j")
        self.listbox.selection_set(idx)
        self._refresh_fit_epoch_controls()
        self._redraw()

    def _open_transit_fit_dialog(self):
        """Lance un fit trapézoïdal inline et trace le modèle sur la courbe."""
        idx = self.selected_index.get()
        if idx < 0 or idx >= len(self.periods_data):
            self._fit_status_var.set("Sélectionnez une période.")
            return
        d = self.periods_data[idx]
        mid_times = d.get("mid_times") or {}
        if not mid_times:
            # Mode séquentiel: éviter d'exiger un clic manuel avant le fit.
            # On crée un seed automatique sur l'époch attendue (si connue),
            # sinon sur l'époch au centre temporel de la LC.
            P = float(d.get("period") or 0.0)
            T0 = float(d.get("t0") or 0.0)
            if not (np.isfinite(P) and P > 0 and np.isfinite(T0)):
                self._fit_status_var.set("Paramètres de période invalides.")
                return
            t = np.asarray(self.time_full, dtype=float)
            f = np.asarray(self.flux_full, dtype=float)
            if len(t) == 0 or len(f) == 0 or len(t) != len(f):
                self._fit_status_var.set("Courbe de lumière invalide.")
                return
            t_mid = float(np.nanmedian(t))
            # Seed temporel TOUJOURS basé sur la LC locale (évite Tc hors champ
            # quand expected_epoch est une époch globale très éloignée).
            epoch_seed_local = int(round((t_mid - T0) / P))
            tc_calc = T0 + epoch_seed_local * P
            # Clé d'époch conservée pour la traçabilité globale si disponible.
            epoch_seed = int(self.expected_epoch) if self.expected_epoch is not None else int(epoch_seed_local)
            half_window = max(0.01, min(P * 0.05, 0.4))
            tc_obs = _pick_transit_mid_time(t, f, tc_calc, half_window)
            if tc_obs is None:
                tc_obs = float(tc_calc)
            d.setdefault("mid_times", {})[int(epoch_seed)] = (float(tc_obs), 0.0, "auto")
            self._refresh_listbox()
            self._redraw()
            mid_times = d.get("mid_times") or {}

        epoch_txt = (self._fit_epoch_var.get() or "").strip()
        if epoch_txt:
            try:
                epoch = int(epoch_txt)
            except ValueError:
                epoch = None
        else:
            epoch = None
        if epoch is not None and epoch not in mid_times:
            epoch = None
        if epoch is None and self.expected_epoch is not None and self.expected_epoch in mid_times:
            epoch = int(self.expected_epoch)
        elif epoch is None and self.expected_epoch is not None and mid_times:
            epoch = int(min(mid_times.keys(), key=lambda e: abs(int(e) - self.expected_epoch)))
        elif epoch is None and mid_times:
            epoch = int(sorted(mid_times.keys())[0])
        else:
            pass
        if epoch is None:
            self._fit_status_var.set("Aucune époque disponible pour le fit.")
            return
        tc, _, _ = self._unpack_mid_time_value(mid_times[epoch])

        P = float(d.get("period") or 0.1)
        dur = float(d.get("duration") or max(0.02, P * 0.05))
        if not self._fit_half_win_var.get().strip():
            self._fit_half_win_var.set(f"{max(0.02, min(P * 0.08, 0.6)):.6f}")
        if not self._fit_width_var.get().strip():
            self._fit_width_var.set(f"{dur:.6f}")
        try:
            hw = float(self._fit_half_win_var.get().replace(",", "."))
            width = float(self._fit_width_var.get().replace(",", "."))
            ing = float(self._fit_ing_var.get().replace(",", "."))
        except ValueError:
            self._fit_status_var.set("Valeurs fit invalides.")
            return

        t, f, e = slice_window(self.time_full, self.flux_full, None, float(tc), hw)
        if len(t) < 8:
            self._fit_status_var.set("Pas assez de points (élargir demi-fenêtre).")
            return
        self._last_used_wotan = False
        f_fit = f
        e_fit = e
        wotan_note = ""
        if self._wotan_var.get():
            if not self._wotan_ok:
                self._fit_status_var.set("Module wotan absent.")
                return
            wl_user = None
            s = (self._wotan_wl_var.get() or "").strip().replace(",", ".")
            if s:
                try:
                    wl_user = float(s)
                    if wl_user <= 0:
                        raise ValueError
                except ValueError:
                    self._fit_status_var.set("Fenêtre Wotan invalide.")
                    return
            method = (self._wotan_method_var.get() or "biweight").strip().lower()
            if method not in WOTAN_METHOD_CHOICES:
                method = "biweight"
            try:
                f_fit, _trend, _mask, scale = flatten_segment_with_transit_mask(
                    t, f, float(tc), width,
                    window_length=wl_user,
                    method=method,
                    break_tolerance=0.0,
                    edge_cutoff=0.0,
                    mask_edge_factor=1.15,
                )
            except Exception as ex:
                logger.exception("Wotan flatten inline")
                self._fit_status_var.set(f"Wotan échec: {ex}")
                return
            self._last_used_wotan = True
            if e is not None:
                e_fit = e / max(scale, 1e-15)
            wl_eff = wl_user if wl_user is not None else default_window_length(t)
            wotan_note = f" | Wotan ({method}, fen.≈{wl_eff:.4f} j)"

        out = fit_trapezoid_transit(
            t,
            f_fit,
            e_fit,
            t0_init=float(tc),
            half_window=hw,
            width_fixed=width,
            ingress_ratio=ing,
            fit_slope=self._fit_slope_var.get(),
        )
        if not out.get("success"):
            self._fit_status_var.set(out.get("message", "Échec fit"))
            return

        self._last_fit = out
        self._last_fit_idx = int(idx)
        self._last_fit_epoch = int(epoch)
        # Met à jour la courbe avec le modèle local
        self._redraw()
        t_ref = out["t_ref"]
        ti = np.linspace(float(np.min(t)), float(np.max(t)), max(200, len(t) * 3))
        tm_fine = model_flux(
            ti,
            out["t0"],
            out["depth"],
            out["a0"],
            out["a1"],
            out["width"],
            out["ingress_ratio"],
            t_ref,
        )
        rel = self.display_relative.get()
        t0_disp = self.t0_display
        x_ti = (ti - t0_disp) if rel else ti
        x_tc0 = (float(tc) - t0_disp) if rel else float(tc)
        x_tcf = (out["t0"] - t0_disp) if rel else out["t0"]
        if self._last_used_wotan:
            mvis = transit_boolean_mask(t, float(tc), width, edge_factor=1.15)
            if np.any(mvis):
                t_lo = float(np.min(t[mvis]))
                t_hi = float(np.max(t[mvis]))
                x_lo = (t_lo - t0_disp) if rel else t_lo
                x_hi = (t_hi - t0_disp) if rel else t_hi
                self.ax.axvspan(x_lo, x_hi, alpha=0.12, color="0.5")
        self.ax.plot(x_ti, tm_fine, "r-", lw=1.6, alpha=0.9)
        self.ax.axvline(x_tc0, color="C1", ls="--", lw=1.0, alpha=0.8)
        self.ax.axvline(x_tcf, color="C2", ls="-", lw=1.2, alpha=0.9)
        self.canvas.draw_idle()
        self._fit_status_var.set(
            f"Tc fit={out['t0']:.6f} ± {out['t0_err']:.6f} j | RMS={out['rms']:.6f}{wotan_note}"
        )

    def _apply_inline_fit(self):
        """Applique le dernier Tc ajusté inline à la période/époch courante."""
        if not self._last_fit or not self._last_fit.get("success"):
            self._fit_status_var.set("Lancez d'abord un fit réussi.")
            return
        idx = self._last_fit_idx
        epoch = self._last_fit_epoch
        if idx is None or epoch is None or idx < 0 or idx >= len(self.periods_data):
            self._fit_status_var.set("Contexte fit invalide.")
            return
        d = self.periods_data[idx]
        d.setdefault("mid_times", {})[int(epoch)] = (
            float(self._last_fit["t0"]),
            float(self._last_fit.get("t0_err") or 0.0),
            "fit",
        )
        self._refresh_listbox()
        self._redraw()
        self._fit_status_var.set(
            f"Tc appliqué à l'époque {epoch}: {self._last_fit['t0']:.6f} j"
        )

    def _validate_tc_sequential(self):
        """Valide un Tc unique pour le mode séquentiel et le transmet au callback."""
        idx = self.selected_index.get()
        if idx < 0 or idx >= len(self.periods_data):
            logger.info("Validation Tc ignorée: aucune période sélectionnée.")
            return
        d = self.periods_data[idx]
        mid_times = d.get("mid_times") or {}
        if not mid_times:
            logger.info("Validation Tc ignorée: aucun mid-time disponible.")
            return

        epoch_use = None
        if self.expected_epoch is not None and self.expected_epoch in mid_times:
            epoch_use = int(self.expected_epoch)
        elif self.expected_epoch is not None:
            epoch_use = int(min(mid_times.keys(), key=lambda e: abs(int(e) - self.expected_epoch)))
        else:
            t_mid = float(np.nanmedian(self.time_full)) if self.time_full is not None and len(self.time_full) else 0.0
            p = float(d.get("period", 0.0))
            t0 = float(d.get("t0", 0.0))
            if np.isfinite(p) and p > 0:
                ep_guess = int(round((t_mid - t0) / p))
                epoch_use = int(min(mid_times.keys(), key=lambda e: abs(int(e) - ep_guess)))
            else:
                epoch_use = int(sorted(mid_times.keys())[0])

        tc, err, source = self._unpack_mid_time_value(mid_times[epoch_use])
        payload = {
            "Epoch": int(epoch_use),
            "Mid_time": float(tc),
            "Uncertainty": float(err),
            "Depth": float(d.get("depth") or 0.0),
            "Period": float(d.get("period") or 0.0),
            "Source": str(source),
        }
        if self.extra_export_columns:
            payload.update(self.extra_export_columns)
        if callable(self.on_validate_tc_callback):
            try:
                self.on_validate_tc_callback(payload)
                self.destroy()
            except Exception:
                logger.exception("Callback validation Tc échoué")
                messagebox.showerror("Validation Tc", "Erreur pendant l'écriture du Tc.")

    def _skip_tc_sequential(self):
        """Ignore la LC courante sans enregistrer de Tc."""
        try:
            if callable(self.on_skip_tc_callback):
                self.on_skip_tc_callback()
        finally:
            self.destroy()

    def _export(self):
        out_dir = filedialog.askdirectory(title="Dossier pour les fichiers mid-time.csv")
        if not out_dir:
            return
        out_path = Path(out_dir)
        exported = []
        for i, d in enumerate(self.periods_data):
            mid_times = d.get('mid_times') or {}
            if not mid_times:
                continue
            P = d['period']
            depth = d.get('depth') or 0
            label = f"P{P:.4f}j".replace('.', '_')
            rows = []
            for ep, raw in sorted(mid_times.items()):
                tc, err, _ = self._unpack_mid_time_value(raw)
                row = {
                    "Epoch": ep,
                    "Mid_time": tc,
                    "Uncertainty": err,
                    "Depth": depth,
                    "Period": float(P),
                }
                if self.extra_export_columns:
                    row.update(self.extra_export_columns)
                rows.append(row)
            df = pd.DataFrame(rows)
            # O-C demandé: T0 = premier mid-time exporté, P = période retenue (marqueur périodogramme, sans ajustement).
            ep = df["Epoch"].values.astype(float)
            mt = df["Mid_time"].values.astype(float)
            P_ref = float(d["period"])
            if np.isfinite(P_ref) and len(df) >= 1 and np.all(np.isfinite(ep)) and np.all(np.isfinite(mt)):
                ep0 = ep[0]
                T0_ref = mt[0]
                tc_linear = T0_ref + (ep - ep0) * P_ref
                oc_days = mt - tc_linear
                df["O-C_minutes"] = oc_days * (24 * 60)
            else:
                df["O-C_minutes"] = 0.0
            base_cols = ["Epoch", "Mid_time", "O-C_minutes", "Uncertainty", "Depth", "Period"]
            extra_cols = [c for c in self.extra_export_columns.keys() if c in df.columns]
            df = df[base_cols + extra_cols]
            fname = f"mid-time_{self.filename_prefix}{label}.csv"
            filepath = out_path / fname
            df.to_csv(filepath, index=False)
            exported.append(fname)
        if exported:
            messagebox.showinfo("Export", "Fichiers créés :\n" + "\n".join(exported))
            if callable(self.on_export_callback):
                try:
                    self.on_export_callback()
                except Exception:
                    logger.exception("Callback post-export échoué")
        else:
            messagebox.showinfo("Export", "Aucun mid-time ajusté. Cliquez sur la courbe (période sélectionnée) pour en ajouter.")

    def _export_selected(self):
        """Exporte uniquement les mid-times MANUELS de la période sélectionnée."""
        idx = self.selected_index.get()
        if idx < 0 or idx >= len(self.periods_data):
            messagebox.showinfo("Export sélection", "Aucune période sélectionnée.")
            return

        d = self.periods_data[idx]
        mid_times = d.get('mid_times') or {}
        if not mid_times:
            messagebox.showinfo(
                "Export sélection",
                "La période sélectionnée ne contient aucun mid-time.\n"
                "Ajoutez des points par clic ou utilisez « Valider tous les transits »."
            )
            return
        manual_rows = []
        for ep, raw in sorted(mid_times.items()):
            tc, err, source = self._unpack_mid_time_value(raw)
            if str(source).lower() == "manual":
                manual_rows.append((ep, tc, err))
        if not manual_rows:
            messagebox.showinfo(
                "Export sélection",
                "Aucun mid-time manuel dans cette période.\n"
                "Cliquez sur la courbe pour créer des points manuels."
            )
            return

        out_dir = filedialog.askdirectory(title="Dossier pour le mid-time.csv de la période sélectionnée")
        if not out_dir:
            return
        out_path = Path(out_dir)

        P = d['period']
        depth = d.get('depth') or 0
        label = f"P{P:.4f}j".replace('.', '_')
        rows = []
        for ep, tc, err in manual_rows:
            row = {
                "Epoch": ep,
                "Mid_time": tc,
                "Uncertainty": err,
                "Depth": depth,
                "Period": float(P),
            }
            if self.extra_export_columns:
                row.update(self.extra_export_columns)
            rows.append(row)
        df = pd.DataFrame(rows)

        ep = df["Epoch"].values.astype(float)
        mt = df["Mid_time"].values.astype(float)
        P_ref = float(d["period"])
        if np.isfinite(P_ref) and len(df) >= 1 and np.all(np.isfinite(ep)) and np.all(np.isfinite(mt)):
            ep0 = ep[0]
            T0_ref = mt[0]
            tc_linear = T0_ref + (ep - ep0) * P_ref
            oc_days = mt - tc_linear
            df["O-C_minutes"] = oc_days * (24 * 60)
        else:
            df["O-C_minutes"] = 0.0

        base_cols = ["Epoch", "Mid_time", "O-C_minutes", "Uncertainty", "Depth", "Period"]
        extra_cols = [c for c in self.extra_export_columns.keys() if c in df.columns]
        df = df[base_cols + extra_cols]
        fname = f"mid-time_{self.filename_prefix}{label}.csv"
        filepath = out_path / fname
        df.to_csv(filepath, index=False)
        messagebox.showinfo(
            "Export sélection",
            f"Fichier créé (mid-times manuels uniquement) :\n{filepath}\n"
            f"Lignes exportées : {len(df)}"
        )
        if callable(self.on_export_callback):
            try:
                self.on_export_callback()
            except Exception:
                logger.exception("Callback post-export sélection échoué")
