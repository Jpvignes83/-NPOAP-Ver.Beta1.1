# gui/variable_stars_tab.py
"""
Sous-onglet Photométrie d'étoiles variables : visualisation FITS, requête VSX,
photométrie différentielle et export AAVSO.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, Toplevel
from tkinter.scrolledtext import ScrolledText

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import Ellipse
from astropy.io import fits
from astropy.coordinates import SkyCoord
from astropy.visualization import ZScaleInterval
from astropy.wcs import WCS
import astropy.units as u
import config
from core.photometry_pipeline import PhotometryPipeline
from core.variable_star_aavso_export import (
    bin_lightcurve_points,
    build_lightcurve_table,
    compute_phases,
    export_aavso_extended_format,
)
from core.vizier_fov_query import (
    ASTROQUERY_VIZIER,
    CDSCLIENT_AVAILABLE,
    FovOverlayObject,
    overlay_contains_pixel,
    query_fov_overlays,
    wcs_from_image_hdu,
)
from gui.manual_help import add_manual_help_header
from gui.target_selector import launch_target_selection

logger = logging.getLogger(__name__)

FILTER_CHOICES = ("V", "B", "R", "I", "CV", "CR", "SU", "SG", "SR", "SI", "SZ", "G", "GAIA")
# Magnitude de référence max (plus petit = plus brillant) pour afficher une variable VSX
VSX_DISPLAY_MAG_MAX = 14.0


def _parse_vsx_magnitude(details: dict) -> Optional[float]:
    """
    Magnitude la plus brillante déclarée dans VSX (min des champs max/min disponibles).
    Les clés VizieR VSX sont souvent « max » / « min » (pas MagMax).
    """
    mags: list[float] = []
    for key in ("max", "min", "MagMax", "MagMin", "mag", "Mag"):
        if key not in details:
            continue
        try:
            v = float(str(details[key]).strip())
            if np.isfinite(v):
                mags.append(v)
        except (TypeError, ValueError):
            continue
    if not mags:
        return None
    return float(min(mags))


def _vsx_passes_display_mag_filter(details: dict, mag_limit: float = VSX_DISPLAY_MAG_MAX) -> bool:
    """Conserve l'objet si magnitude G absente ou plus brillante que mag_limit (mag < limit)."""
    mag = _parse_vsx_magnitude(details)
    if mag is None:
        return True
    bands: list[str] = []
    for key in ("n_max", "n_min", "n_MagMax", "n_MagMin", "filter", "Filter"):
        if key in details and str(details[key]).strip():
            bands.append(str(details[key]).strip().upper())
    if bands and not any("G" in b for b in bands):
        return True
    return mag < float(mag_limit)


def _filter_vsx_overlays(
    overlays: List[FovOverlayObject],
    mag_limit: float = VSX_DISPLAY_MAG_MAX,
) -> List[FovOverlayObject]:
    kept: List[FovOverlayObject] = []
    for obj in overlays:
        if obj.category != "variable":
            kept.append(obj)
            continue
        if _vsx_passes_display_mag_filter(obj.details, mag_limit):
            kept.append(obj)
    return kept


def _vsx_detail_field(details: dict, *keys: str) -> str:
    for key in keys:
        if key in details:
            val = str(details[key]).strip()
            if val:
                return val
    return ""


def _vsx_coord_from_details(details: dict) -> Optional[SkyCoord]:
    for ra_k, dec_k in (
        ("RAJ2000", "DEJ2000"),
        ("_RAJ2000", "_DEJ2000"),
        ("RA_ICRS", "DE_ICRS"),
        ("RA", "DEC"),
        ("RA", "Dec"),
    ):
        ra_s = _vsx_detail_field(details, ra_k)
        dec_s = _vsx_detail_field(details, dec_k)
        if not ra_s or not dec_s:
            continue
        try:
            ra_f = float(ra_s)
            dec_f = float(dec_s)
            if np.isfinite(ra_f) and np.isfinite(dec_f):
                if ra_f > 24.0:
                    return SkyCoord(ra_f, dec_f, unit=(u.deg, u.deg), frame="icrs")
        except (TypeError, ValueError):
            pass
        try:
            return SkyCoord(ra_s, dec_s, unit=(u.hourangle, u.deg), frame="icrs")
        except Exception:
            try:
                return SkyCoord(float(ra_s), float(dec_s), unit=(u.deg, u.deg), frame="icrs")
            except Exception:
                continue
    return None


def _format_vsx_hmsdms(coord: SkyCoord) -> tuple[str, str]:
    ra_s = coord.ra.to_string(unit=u.hourangle, sep=" ", precision=0, pad=True)
    dec_s = coord.dec.to_string(
        unit=u.deg, sep=" ", precision=0, alwayssign=True, pad=True
    )
    return ra_s, dec_s


def _format_vsx_magnitude_line(label: str, mag: str, band: str, limit_flag: str) -> str:
    if not mag:
        return f"{label} : —"
    text = mag
    if limit_flag:
        text = f"{limit_flag}{text}"
    if band:
        text = f"{text} ({band})"
    return f"{label} : {text}"


def format_vsx_detail_text(obj: FovOverlayObject) -> str:
    """Texte structuré pour la fenêtre Détail (VSX)."""
    d = obj.details
    lines: list[str] = []

    label = _vsx_detail_field(d, "Name", "ID", "identifier", "OID") or obj.label
    lines.append(f"Libellé : {label}")

    coord = _vsx_coord_from_details(d)
    if coord is not None:
        ra_s, dec_s = _format_vsx_hmsdms(coord)
        lines.append(f"RA  : {ra_s}")
        lines.append(f"Dec : {dec_s}")
    else:
        lines.append("RA  : —")
        lines.append("Dec : —")

    vtype = _vsx_detail_field(d, "Type", "type", "Variability_Type", "VAR_TYPE")
    lines.append(f"Type variable : {vtype or '—'}")

    sp = _vsx_detail_field(d, "Sp", "SpType", "Spect_Type", "spectral_type", "SpType")
    lines.append(f"Type spectral : {sp or '—'}")

    period = _vsx_detail_field(d, "Period", "period", "Per")
    l_period = _vsx_detail_field(d, "l_Period", "Period_Limit", "u_Period")
    if period:
        try:
            pval = float(period)
            ptxt = f"{pval:.8g} j" if np.isfinite(pval) else period
        except (TypeError, ValueError):
            ptxt = period
        if l_period:
            ptxt = f"{l_period}{ptxt}"
        lines.append(f"Période : {ptxt}")
    else:
        lines.append("Période : —")

    lines.append(
        _format_vsx_magnitude_line(
            "Mag. max",
            _vsx_detail_field(d, "max", "MagMax"),
            _vsx_detail_field(d, "n_max", "Max_Mag_Passband"),
            _vsx_detail_field(d, "l_max"),
        )
    )
    lines.append(
        _format_vsx_magnitude_line(
            "Mag. min",
            _vsx_detail_field(d, "min", "MagMin"),
            _vsx_detail_field(d, "n_min", "Min_Mag_Passband"),
            _vsx_detail_field(d, "l_min"),
        )
    )
    return "\n".join(lines)


class VariableStarsTab(ttk.Frame):
    """Photométrie d'étoiles variables dans le panneau Étoiles."""

    def __init__(self, parent_notebook, base_dir=None):
        super().__init__(parent_notebook, padding=6)
        self.base_dir = Path(base_dir) if base_dir else Path.home()

        self.image_dir: Optional[Path] = None
        self.fits_files: List[Path] = []
        self.current_index = 0
        self.current_data: Optional[np.ndarray] = None
        self.current_header = None
        self.current_wcs: Optional[WCS] = None

        self.ref_image: Optional[str] = None
        self.target_coord: Optional[SkyCoord] = None
        self.target_mag: Optional[float] = None
        self.comp_coords: list = []
        self.current_selections = None
        self.results_csv: Optional[Path] = None
        self.lc_df: Optional[pd.DataFrame] = None

        self._catalog_overlays: List[FovOverlayObject] = []
        self._catalog_fetch_gen = 0
        self._selected_vsx_index: Optional[int] = None

        self.pipeline = PhotometryPipeline()
        self._build_ui()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        add_manual_help_header(self, "10-etoiles-variables")

        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(
            header,
            text="Photométrie d'étoiles variables",
            font=("Helvetica", 13, "bold"),
        ).pack(side=tk.LEFT)

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=4)
        right = ttk.Frame(paned, padding=4)
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        try:
            paned.pane(left, minsize=280)
        except tk.TclError:
            pass

        self._build_left_controls(left)
        self._build_right_viewer(right)

    def _build_left_controls(self, parent: ttk.Frame) -> None:
        # --- Répertoire ---
        dir_frame = ttk.LabelFrame(parent, text="Images FITS", padding=6)
        dir_frame.pack(fill=tk.X, pady=4)
        self.dir_var = tk.StringVar()
        ttk.Entry(dir_frame, textvariable=self.dir_var).pack(fill=tk.X, pady=2)
        ttk.Button(dir_frame, text="📁 Choisir le répertoire", command=self._browse_directory).pack(
            fill=tk.X, pady=2
        )
        self.dir_status = ttk.Label(dir_frame, text="Aucun répertoire", foreground="gray", font=("", 8))
        self.dir_status.pack(anchor=tk.W)

        # --- Cible ---
        target_frame = ttk.LabelFrame(parent, text="Cible variable", padding=6)
        target_frame.pack(fill=tk.X, pady=4)
        ttk.Label(target_frame, text="Nom (VSX / AAVSO) :").pack(anchor=tk.W)
        self.star_name_var = tk.StringVar()
        ttk.Entry(target_frame, textvariable=self.star_name_var).pack(fill=tk.X, pady=2)
        ttk.Label(target_frame, text="Filtre :").pack(anchor=tk.W)
        self.filter_var = tk.StringVar(value="V")
        ttk.Combobox(
            target_frame,
            textvariable=self.filter_var,
            values=FILTER_CHOICES,
            width=12,
            state="readonly",
        ).pack(anchor=tk.W, pady=2)
        ttk.Label(target_frame, text="Mag. de réf. (Gaia G) :").pack(anchor=tk.W)
        self.ref_mag_var = tk.StringVar()
        ttk.Entry(target_frame, textvariable=self.ref_mag_var, width=12).pack(anchor=tk.W, pady=2)

        # --- Catalogues ---
        cat_frame = ttk.LabelFrame(parent, text="Étoiles variables dans le champ", padding=6)
        cat_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        ttk.Button(
            cat_frame,
            text="🔍 Requête VSX",
            command=self._schedule_catalog_query,
        ).pack(fill=tk.X, pady=2)
        ttk.Label(
            cat_frame,
            text=f"Filtre affichage : magnitude G < {VSX_DISPLAY_MAG_MAX:.0f} lorsque VSX la fournit.",
            font=("", 8),
            foreground="gray",
            wraplength=250,
        ).pack(anchor=tk.W, pady=(0, 2))
        self.cat_status = ttk.Label(cat_frame, text="", foreground="gray", font=("", 8), wraplength=250)
        self.cat_status.pack(anchor=tk.W, pady=2)
        list_wrap = ttk.Frame(cat_frame)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_wrap)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.var_listbox = tk.Listbox(list_wrap, height=8, yscrollcommand=scroll.set, font=("Consolas", 9))
        self.var_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.var_listbox.yview)
        self.var_listbox.bind("<<ListboxSelect>>", self._on_variable_selected)
        ttk.Button(cat_frame, text="Détail", command=self._show_selected_variable_detail).pack(
            fill=tk.X, pady=2
        )

        # --- Photométrie ---
        phot_frame = ttk.LabelFrame(parent, text="Photométrie", padding=6)
        phot_frame.pack(fill=tk.X, pady=4)
        ttk.Label(
            phot_frame,
            text="Image de référence = image affichée (WCS requis).",
            font=("", 8),
            foreground="gray",
            wraplength=250,
        ).pack(anchor=tk.W)
        ttk.Button(phot_frame, text="1. Sélection T1 + comparateurs", command=self._launch_selector).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(phot_frame, text="2. Régler les ouvertures", command=self._open_aperture_dialog).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(phot_frame, text="3. Photométrie série", command=self._launch_batch).pack(fill=tk.X, pady=2)
        self.phot_status = ttk.Label(phot_frame, text="En attente", foreground="gray", font=("", 8))
        self.phot_status.pack(anchor=tk.W, pady=2)
        self.progress_var = tk.DoubleVar()
        ttk.Progressbar(phot_frame, variable=self.progress_var, maximum=100).pack(fill=tk.X, pady=2)

        # --- Export ---
        export_frame = ttk.LabelFrame(parent, text="Courbe & export AAVSO", padding=6)
        export_frame.pack(fill=tk.X, pady=4)
        ttk.Button(export_frame, text="💾 Exporter CSV AAVSO", command=self._export_aavso).pack(
            fill=tk.X, pady=2
        )

    def _build_right_viewer(self, parent: ttk.Frame) -> None:
        viewer_nb = ttk.Notebook(parent)
        viewer_nb.pack(fill=tk.BOTH, expand=True)

        img_tab = ttk.Frame(viewer_nb)
        lc_tab = ttk.Frame(viewer_nb)
        phase_tab = ttk.Frame(viewer_nb)
        viewer_nb.add(img_tab, text="Image")
        viewer_nb.add(lc_tab, text="Courbe de lumière")
        viewer_nb.add(phase_tab, text="Courbe en phase")

        # Image + toolbar zoom
        fig_frame = ttk.Frame(img_tab)
        fig_frame.pack(fill=tk.BOTH, expand=True)
        self.fig_img, self.ax_img = plt.subplots(figsize=(7, 6))
        self.canvas_img = FigureCanvasTkAgg(self.fig_img, master=fig_frame)
        self.canvas_img.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.toolbar_img = NavigationToolbar2Tk(self.canvas_img, fig_frame)
        self.toolbar_img.update()
        self.canvas_img.mpl_connect("button_press_event", self._on_image_click)

        nav = ttk.Frame(img_tab)
        nav.pack(fill=tk.X, pady=4)
        ttk.Button(nav, text="⏮", width=4, command=self._first_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav, text="◀", width=4, command=self._prev_image).pack(side=tk.LEFT, padx=2)
        self.img_info_label = ttk.Label(nav, text="—")
        self.img_info_label.pack(side=tk.LEFT, padx=8)
        ttk.Button(nav, text="▶", width=4, command=self._next_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav, text="⏭", width=4, command=self._last_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav, text="Image = référence", command=self._set_current_as_ref).pack(side=tk.RIGHT, padx=4)

        # Courbe de lumière
        lc_controls = ttk.Frame(lc_tab)
        lc_controls.pack(fill=tk.X, pady=(4, 2), padx=4)
        ttk.Label(lc_controls, text="Binning :").pack(side=tk.LEFT, padx=(0, 6))
        self.lc_bin_var = tk.IntVar(value=1)
        for n_bin, label in ((1, "Aucun"), (2, "×2"), (4, "×4")):
            ttk.Radiobutton(
                lc_controls,
                text=label,
                variable=self.lc_bin_var,
                value=n_bin,
                command=self._on_lc_display_changed,
            ).pack(side=tk.LEFT, padx=4)

        lc_plot_frame = ttk.Frame(lc_tab)
        lc_plot_frame.pack(fill=tk.BOTH, expand=True)
        self.fig_lc, self.ax_lc = plt.subplots(figsize=(7, 4))
        self.ax_lc.set_xlabel("BJD-TDB")
        self.ax_lc.set_ylabel("Magnitude")
        self.ax_lc.invert_yaxis()
        self.canvas_lc = FigureCanvasTkAgg(self.fig_lc, master=lc_plot_frame)
        self.canvas_lc.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas_lc, lc_plot_frame).update()

        # Courbe repliee en phase
        phase_controls = ttk.LabelFrame(phase_tab, text="Replissement en phase", padding=6)
        phase_controls.pack(fill=tk.X, padx=4, pady=4)
        prow1 = ttk.Frame(phase_controls)
        prow1.pack(fill=tk.X, pady=2)
        ttk.Label(prow1, text="Période P (j) :", width=14).pack(side=tk.LEFT)
        self.lc_period_var = tk.StringVar()
        ttk.Entry(prow1, textvariable=self.lc_period_var, width=14).pack(side=tk.LEFT, padx=4)
        ttk.Label(prow1, text="T₀ BJD-TDB :", width=12).pack(side=tk.LEFT, padx=(8, 0))
        self.lc_epoch_var = tk.StringVar()
        ttk.Entry(prow1, textvariable=self.lc_epoch_var, width=16).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            phase_controls,
            text="T₀ vide → minimum BJD-TDB de la série. Binning = réglage onglet « Courbe de lumière ».",
            font=("", 8),
            foreground="gray",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 4))
        prow2 = ttk.Frame(phase_controls)
        prow2.pack(fill=tk.X, pady=2)
        self.lc_phase_extend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            prow2,
            text="Étendre 0 → 2 (continuité autour de la phase 0/1)",
            variable=self.lc_phase_extend_var,
        ).pack(side=tk.LEFT)
        ttk.Button(prow2, text="Afficher courbe en phase", command=self._redraw_phase_curve).pack(
            side=tk.RIGHT, padx=4
        )

        phase_plot_frame = ttk.Frame(phase_tab)
        phase_plot_frame.pack(fill=tk.BOTH, expand=True)
        self.fig_phase, self.ax_phase = plt.subplots(figsize=(7, 4))
        self.ax_phase.set_xlabel("Phase")
        self.ax_phase.set_ylabel("Magnitude")
        self.ax_phase.invert_yaxis()
        self.canvas_phase = FigureCanvasTkAgg(self.fig_phase, master=phase_plot_frame)
        self.canvas_phase.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas_phase, phase_plot_frame).update()

    # ------------------------------------------------------------------
    # Répertoire & navigation
    # ------------------------------------------------------------------
    def _browse_directory(self) -> None:
        initial = str(self.image_dir or self.base_dir)
        chosen = filedialog.askdirectory(title="Répertoire des images FITS", initialdir=initial)
        if not chosen:
            return
        self.image_dir = Path(chosen)
        self.dir_var.set(str(self.image_dir))
        self._load_fits_list()

    def _load_fits_list(self) -> None:
        if not self.image_dir:
            return
        patterns = ("*.fits", "*.fit", "*.fts", "*.FITS")
        files: List[Path] = []
        for pat in patterns:
            files.extend(self.image_dir.glob(pat))
        self.fits_files = sorted(set(files))
        self.current_index = 0
        n = len(self.fits_files)
        self.dir_status.config(
            text=f"{n} fichier(s) FITS" if n else "Aucun FITS dans ce dossier",
            foreground="green" if n else "red",
        )
        self._catalog_overlays = []
        self._selected_vsx_index = None
        self.var_listbox.delete(0, tk.END)
        if n:
            self._load_image_at(0)
        else:
            self._refresh_image_display()

    def _load_image_at(self, index: int) -> None:
        if not self.fits_files:
            return
        index = max(0, min(index, len(self.fits_files) - 1))
        self.current_index = index
        fpath = self.fits_files[index]
        try:
            with fits.open(fpath) as hdul:
                data = np.asarray(hdul[0].data, dtype=float)
                if data.ndim > 2:
                    data = np.squeeze(data)
                if data.ndim != 2:
                    raise ValueError(f"Image non 2D : shape={data.shape}")
                self.current_data = data
                self.current_header = hdul[0].header.copy()
                self.current_wcs = wcs_from_image_hdu(self.current_header)
        except Exception as e:
            messagebox.showerror("Erreur FITS", f"Impossible de lire {fpath.name}:\n{e}")
            return
        self.img_info_label.config(text=f"{index + 1}/{len(self.fits_files)} — {fpath.name}")
        self._refresh_image_display()

    def _first_image(self) -> None:
        self._load_image_at(0)

    def _last_image(self) -> None:
        self._load_image_at(len(self.fits_files) - 1)

    def _prev_image(self) -> None:
        self._load_image_at(self.current_index - 1)

    def _next_image(self) -> None:
        self._load_image_at(self.current_index + 1)

    def _set_current_as_ref(self) -> None:
        if not self.fits_files:
            messagebox.showwarning("Référence", "Chargez d'abord un répertoire d'images.")
            return
        if self.current_wcs is None:
            messagebox.showwarning(
                "WCS",
                "L'image courante n'a pas de WCS. Utilisez une image astrométriquement résolue.",
            )
            return
        self.ref_image = str(self.fits_files[self.current_index])
        self.phot_status.config(text=f"Réf. : {Path(self.ref_image).name}", foreground="blue")

    def _refresh_image_display(self) -> None:
        self.ax_img.clear()
        if self.current_data is None:
            self.canvas_img.draw()
            return
        interval = ZScaleInterval()
        valid = self.current_data[np.isfinite(self.current_data)]
        if valid.size:
            vmin, vmax = interval.get_limits(valid)
        else:
            vmin, vmax = 0, 1
        self.ax_img.imshow(self.current_data, origin="lower", cmap="gray", vmin=vmin, vmax=vmax)
        sel_idx = self._selected_vsx_index
        for i, obj in enumerate(self._catalog_overlays):
            selected = sel_idx is not None and i == sel_idx
            color = "red" if selected else ("cyan" if obj.category == "variable" else "yellow")
            lw = 2.4 if selected else 1.2
            e = Ellipse(
                (obj.x_pix, obj.y_pix),
                width=2 * obj.semi_major_px,
                height=2 * obj.semi_minor_px,
                angle=obj.theta_mpl_deg,
                fill=False,
                edgecolor=color,
                linewidth=lw,
                alpha=0.95 if selected else 0.85,
                zorder=5 if selected else 3,
            )
            self.ax_img.add_patch(e)
            self.ax_img.text(
                obj.x_pix + 4,
                obj.y_pix + 4,
                obj.label[:24],
                color=color,
                fontsize=8 if selected else 7,
                fontweight="bold" if selected else "normal",
                clip_on=True,
                zorder=6 if selected else 4,
            )
        self.ax_img.set_title(self.img_info_label.cget("text"))
        self.fig_img.tight_layout()
        self.canvas_img.draw()

    def _on_image_click(self, event) -> None:
        if event.inaxes != self.ax_img or event.xdata is None:
            return
        x, y = float(event.xdata), float(event.ydata)
        for obj in reversed(self._catalog_overlays):
            if overlay_contains_pixel(obj, x, y):
                self._show_overlay_popup(obj)
                break

    def _show_overlay_popup(self, obj: FovOverlayObject) -> None:
        win = Toplevel(self)
        win.title(obj.label)
        win.geometry("420x300")
        st = ScrolledText(win, wrap=tk.WORD, font=("Consolas", 10))
        st.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        if obj.category == "variable":
            text = format_vsx_detail_text(obj)
        else:
            lines = [f"Libellé : {obj.label}", ""]
            for k, v in sorted(obj.details.items()):
                lines.append(f"{k}: {v}")
            text = "\n".join(lines)
        st.insert(tk.END, text)
        st.configure(state=tk.DISABLED)
        ttk.Button(win, text="Fermer", command=win.destroy).pack(pady=4)

    # ------------------------------------------------------------------
    # Requête VSX
    # ------------------------------------------------------------------
    def _schedule_catalog_query(self) -> None:
        if self.current_wcs is None or self.current_data is None:
            messagebox.showwarning(
                "WCS",
                "L'image affichée doit avoir un WCS valide pour interroger VSX.",
            )
            return
        if not (CDSCLIENT_AVAILABLE or ASTROQUERY_VIZIER):
            messagebox.showerror(
                "Catalogues",
                "Installez astroquery et/ou cdsclient pour les requêtes VizieR.",
            )
            return
        self._catalog_fetch_gen += 1
        gen = self._catalog_fetch_gen
        self.cat_status.config(text="Requête en cours…", foreground="blue")
        wcs = self.current_wcs
        shape = self.current_data.shape

        def worker():
            err = None
            overlays: List[FovOverlayObject] = []
            try:
                overlays = query_fov_overlays(
                    wcs,
                    shape,
                    include_exoplanets=False,
                    include_galaxies=False,
                    include_variables=True,
                    include_solar_system=False,
                    fov_query="box",
                    fov_margin=1.02,
                    chip_margin_frac=0.01,
                )
            except Exception as e:
                logger.exception("Requête VSX")
                err = str(e)

            def apply():
                if gen != self._catalog_fetch_gen:
                    return
                if err:
                    self.cat_status.config(text=f"Erreur : {err}", foreground="red")
                    return
                n_raw = len(overlays)
                filtered = _filter_vsx_overlays(overlays, VSX_DISPLAY_MAG_MAX)
                logger.info(
                    "VSX affichage : %d / %d après filtre G < %.0f",
                    len(filtered),
                    n_raw,
                    VSX_DISPLAY_MAG_MAX,
                )
                self._catalog_overlays = filtered
                self._selected_vsx_index = None
                self._fill_variable_listbox()
                self.cat_status.config(
                    text=(
                        f"VSX : {len(filtered)} retenue(s) sur {n_raw} "
                        f"(FOV image, G < {VSX_DISPLAY_MAG_MAX:.0f} si indiqué)"
                    ),
                    foreground="green",
                )
                self._refresh_image_display()

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _fill_variable_listbox(self) -> None:
        self.var_listbox.delete(0, tk.END)
        for obj in self._catalog_overlays:
            self.var_listbox.insert(tk.END, f"[VSX] {obj.label}")

    def _on_variable_selected(self, _event=None) -> None:
        sel = self.var_listbox.curselection()
        if not sel or sel[0] >= len(self._catalog_overlays):
            self._selected_vsx_index = None
            self._refresh_image_display()
            return
        self._selected_vsx_index = int(sel[0])
        obj = self._catalog_overlays[sel[0]]
        name = obj.label
        if obj.category == "variable" and "Name" in obj.details:
            name = obj.details.get("Name", name)
        self.star_name_var.set(name.split()[0] if name else "")
        vmag = _parse_vsx_magnitude(obj.details)
        if vmag is not None:
            self.ref_mag_var.set(f"{vmag:.3f}")
        elif "MagMax" in obj.details:
            try:
                self.ref_mag_var.set(f"{float(obj.details['MagMax']):.3f}")
            except (TypeError, ValueError):
                pass
        elif "max" in obj.details:
            try:
                self.ref_mag_var.set(f"{float(obj.details['max']):.3f}")
            except (TypeError, ValueError):
                pass
        for pkey in ("Period", "period", "Per"):
            if pkey in obj.details:
                try:
                    pval = float(obj.details[pkey])
                    if pval > 0:
                        self.lc_period_var.set(f"{pval:.8g}")
                except (TypeError, ValueError):
                    pass
                break
        for ekey in ("Epoch", "epoch", "T0", "Epo"):
            if ekey in obj.details:
                try:
                    eval_ = float(obj.details[ekey])
                    if np.isfinite(eval_) and eval_ > 2400000:
                        self.lc_epoch_var.set(f"{eval_:.8f}")
                except (TypeError, ValueError):
                    pass
                break
        self._refresh_image_display()

    def _show_selected_variable_detail(self) -> None:
        sel = self.var_listbox.curselection()
        if not sel:
            return
        self._show_overlay_popup(self._catalog_overlays[sel[0]])

    # ------------------------------------------------------------------
    # Photométrie
    # ------------------------------------------------------------------
    def _read_header_target_coord(self, fits_path: str) -> Optional[SkyCoord]:
        try:
            with fits.open(fits_path) as hdul:
                header = hdul[0].header
            ra_h = header.get("OBJCTRA") or header.get("RA")
            dec_h = header.get("OBJCTDEC") or header.get("DEC")
            if ra_h and dec_h:
                try:
                    ra_val = float(ra_h)
                    dec_val = float(dec_h)
                    if ra_val > 24.0:
                        return SkyCoord(ra_val, dec_val, unit=(u.deg, u.deg))
                except Exception:
                    pass
                return SkyCoord(ra_h, dec_h, unit=(u.hourangle, u.deg))
            if header.get("CRVAL1") is not None:
                return SkyCoord(
                    float(header["CRVAL1"]) * u.deg,
                    float(header["CRVAL2"]) * u.deg,
                )
        except Exception as e:
            logger.debug("Coordonnées header : %s", e)
        return None

    def _wcs_for_fits(self, fits_path: str) -> Optional[WCS]:
        """WCS de l'image FITS de référence (aligné sur le fichier ouvert dans le sélecteur)."""
        try:
            with fits.open(fits_path) as hdul:
                return wcs_from_image_hdu(hdul[0].header)
        except Exception as e:
            logger.debug("WCS depuis %s : %s", fits_path, e)
            return self.current_wcs

    def _launch_selector(self) -> None:
        if not self.ref_image:
            self._set_current_as_ref()
        if not self.ref_image:
            return

        def on_done(fits_path, target_data, comps_list):
            if isinstance(target_data, dict):
                t1 = target_data["coord"]
                if target_data.get("mag") is not None:
                    self.target_mag = float(target_data["mag"])
            else:
                t1 = target_data
            self.target_coord = t1
            self.comp_coords = comps_list
            self.current_selections = [{"label": "T1", "coord": t1, "r_ap": 8.0, "r_in": 12.0, "r_out": 18.0}]
            for i, c in enumerate(comps_list):
                coord = c["coord"] if isinstance(c, dict) else c
                self.current_selections.append(
                    {"label": f"C{i+1}", "coord": coord, "r_ap": 8.0, "r_in": 12.0, "r_out": 18.0}
                )
            self.phot_status.config(
                text=f"T1 + {len(comps_list)} comparateur(s)", foreground="orange"
            )
            if self.target_mag is not None:
                self.ref_mag_var.set(f"{self.target_mag:.3f}")
            self._open_aperture_dialog()

        header_coord = self._read_header_target_coord(self.ref_image)
        wcs_sel = self._wcs_for_fits(self.ref_image)
        launch_target_selection(
            self.ref_image,
            on_selection_done=on_done,
            header_target_coord=header_coord,
            max_comps=10,
            comp_mag_delta=2.5,
            comp_search_radius_arcmin=45.0,
            comps_full_fov=False,
            wcs=wcs_sel,
        )

    def _open_aperture_dialog(self) -> None:
        if not self.ref_image or not self.target_coord:
            messagebox.showwarning("Photométrie", "Effectuez d'abord la sélection T1 / comparateurs.")
            return
        try:
            self.pipeline.launch_photometry_aperture(
                fits_path=self.ref_image,
                target_coord=self.target_coord,
                comp_coords=self.comp_coords,
                on_finish=self._on_aperture_confirmed,
            )
        except Exception as e:
            messagebox.showerror("Ouvertures", str(e))

    def _on_aperture_confirmed(self, final_selections) -> None:
        if not final_selections:
            return
        self.current_selections = final_selections
        t1 = next((s for s in final_selections if s.get("label") == "T1"), None)
        if not t1:
            messagebox.showwarning("T1", "Réactivez la cible T1 dans la fenêtre d'ouvertures.")
            return
        self.target_coord = t1["coord"]
        self.comp_coords = [s["coord"] for s in final_selections if s.get("label", "").startswith("C")]
        self.phot_status.config(text="Ouvertures validées", foreground="green")

    def _launch_batch(self) -> None:
        if not self.current_selections or not self.image_dir:
            messagebox.showwarning("Batch", "Validez les ouvertures et choisissez un répertoire.")
            return
        if not self.ref_image:
            self._set_current_as_ref()
        self.phot_status.config(text="Photométrie en cours…", foreground="blue")
        self.progress_var.set(0)
        threading.Thread(target=self._run_batch, daemon=True).start()

    def _run_batch(self) -> None:
        try:
            self.pipeline.process_photometry_series(
                folder=str(self.image_dir),
                target_coord=self.target_coord,
                comps=self.comp_coords,
                ref_image=self.ref_image,
                selections=self.current_selections,
                progress_callback=lambda p: self.after(0, lambda: self.progress_var.set(p)),
            )
            res = self.image_dir / "photometrie" / "results.csv"
            self.results_csv = res if res.exists() else None

            def done():
                if self.results_csv:
                    self.phot_status.config(
                        text=f"Terminé — {self.results_csv.name}", foreground="green"
                    )
                    self._plot_lightcurve()
                    messagebox.showinfo("Photométrie", f"Résultats : {self.results_csv}")
                else:
                    self.phot_status.config(text="Aucun résultat", foreground="red")

            self.after(0, done)
        except Exception as e:
            logger.exception("Batch photométrie variables")
            self.after(0, lambda: messagebox.showerror("Erreur", str(e)))

    # ------------------------------------------------------------------
    # Courbe de lumière & export
    # ------------------------------------------------------------------
    def _get_ref_mag(self) -> float:
        try:
            return float(self.ref_mag_var.get().strip())
        except (TypeError, ValueError):
            if self.target_mag is not None:
                return float(self.target_mag)
            raise ValueError("Indiquez la magnitude de référence (Gaia G).")

    def _build_lc_dataframe(self) -> pd.DataFrame:
        if not self.results_csv or not self.results_csv.exists():
            raise FileNotFoundError("Lancez d'abord la photométrie série (results.csv).")
        if self.target_coord is None:
            raise ValueError("Coordonnées de la cible manquantes.")
        ref_mag = self._get_ref_mag()
        return build_lightcurve_table(
            self.results_csv,
            self.image_dir,
            self.target_coord,
            ref_mag,
            fits_files=self.fits_files,
        )

    def _plot_lightcurve(self) -> None:
        try:
            self.lc_df = self._build_lc_dataframe()
        except Exception as e:
            messagebox.showerror("Courbe", str(e))
            return
        self._redraw_lightcurve()
        if self.lc_period_var.get().strip():
            self._redraw_phase_curve()

    def _on_lc_display_changed(self) -> None:
        self._redraw_lightcurve()
        if self.lc_period_var.get().strip():
            self._redraw_phase_curve()

    def _lc_bin_size(self) -> int:
        try:
            return max(1, int(self.lc_bin_var.get()))
        except (tk.TclError, ValueError, TypeError):
            return 1

    def _get_binned_lc_arrays(self):
        """Retourne (t, mag, merr, tcol) après binning, ou (None, ...) si pas de données."""
        if self.lc_df is None:
            return None, None, None, "BJD-TDB"
        df = self.lc_df
        tcol = "BJD-TDB" if "BJD-TDB" in df.columns else "JD-UTC"
        valid = df[np.isfinite(df[tcol]) & np.isfinite(df["MAG"])].sort_values(tcol)
        if len(valid) == 0:
            return None, None, None, tcol
        t = valid[tcol].values
        m = valid["MAG"].values
        merr = valid["MERR"].values if "MERR" in valid.columns else None
        t, m, merr = bin_lightcurve_points(t, m, merr, n_bin=self._lc_bin_size())
        finite = np.isfinite(t) & np.isfinite(m)
        t, m = t[finite], m[finite]
        if merr is not None:
            merr = merr[finite]
        return t, m, merr, tcol

    def _plot_lc_on_axes(self, ax, x, y, yerr=None, *, xlabel: str, title: str) -> None:
        ax.clear()
        if x is not None and len(x):
            ax.plot(x, y, "-", color="steelblue", linewidth=1.2, alpha=0.85, zorder=1)
            ax.errorbar(
                x,
                y,
                yerr=yerr,
                fmt="o",
                ms=4,
                capsize=2,
                color="steelblue",
                zorder=2,
            )
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Magnitude")
        ax.set_title(title)
        ax.invert_yaxis()
        ax.grid(True, alpha=0.3)

    def _redraw_lightcurve(self) -> None:
        if self.lc_df is None:
            return
        t, m, merr, tcol = self._get_binned_lc_arrays()
        star = self.star_name_var.get().strip() or "Cible"
        n_bin = self._lc_bin_size()
        bin_label = {1: "", 2: " (bin ×2)", 4: " (bin ×4)"}.get(n_bin, f" (bin ×{n_bin})")
        self._plot_lc_on_axes(
            self.ax_lc,
            t,
            m,
            merr,
            xlabel="BJD-TDB" if tcol == "BJD-TDB" else "JD",
            title=f"Courbe de lumière — {star}{bin_label}",
        )
        self.fig_lc.tight_layout()
        self.canvas_lc.draw()

    def _parse_period_epoch(self, t: np.ndarray) -> tuple[float, float]:
        period_s = self.lc_period_var.get().strip().replace(",", ".")
        if not period_s:
            raise ValueError("Indiquez la période P en jours.")
        period = float(period_s)
        if period <= 0:
            raise ValueError("La période doit être > 0.")
        epoch_s = self.lc_epoch_var.get().strip().replace(",", ".")
        if epoch_s:
            epoch = float(epoch_s)
        else:
            epoch = float(np.nanmin(t))
            self.lc_epoch_var.set(f"{epoch:.8f}")
        return period, epoch

    def _redraw_phase_curve(self) -> None:
        if self.lc_df is None:
            messagebox.showinfo(
                "Phase",
                "Aucune courbe de lumière : lancez d'abord la photométrie série.",
            )
            return
        try:
            t, m, merr, tcol = self._get_binned_lc_arrays()
            if t is None or len(t) == 0:
                messagebox.showwarning("Phase", "Aucun point valide dans la courbe.")
                return
            period, epoch = self._parse_period_epoch(t)
            phase = compute_phases(t, period, epoch)
            if self.lc_phase_extend_var.get():
                phase_plot = np.concatenate([phase, phase + 1.0])
                m_plot = np.concatenate([m, m])
                merr_plot = np.concatenate([merr, merr]) if merr is not None else None
            else:
                phase_plot, m_plot, merr_plot = phase, m, merr
            order = np.argsort(phase_plot)
            phase_plot = phase_plot[order]
            m_plot = m_plot[order]
            if merr_plot is not None:
                merr_plot = merr_plot[order]
            star = self.star_name_var.get().strip() or "Cible"
            n_bin = self._lc_bin_size()
            bin_label = {1: "", 2: " (bin ×2)", 4: " (bin ×4)"}.get(n_bin, "")
            xlim = (0.0, 2.0) if self.lc_phase_extend_var.get() else (0.0, 1.0)
            self._plot_lc_on_axes(
                self.ax_phase,
                phase_plot,
                m_plot,
                merr_plot,
                xlabel="Phase",
                title=f"{star} — P={period:.6g} j, T₀={epoch:.5f}{bin_label}",
            )
            self.ax_phase.set_xlim(xlim)
            self.fig_phase.tight_layout()
            self.canvas_phase.draw()
        except ValueError as e:
            messagebox.showerror("Courbe en phase", str(e))
        except Exception as e:
            logger.exception("Courbe en phase")
            messagebox.showerror("Courbe en phase", str(e))

    def _export_star_name(self) -> str:
        """Nom AAVSO : champ utilisateur, sinon nom du fichier de référence."""
        name = self.star_name_var.get().strip()
        if name:
            return name
        if self.ref_image:
            return Path(self.ref_image).stem
        if self.fits_files:
            return self.fits_files[0].stem
        return "TARGET"

    def _export_aavso(self) -> None:
        try:
            if self.lc_df is None:
                self.lc_df = self._build_lc_dataframe()
        except Exception as e:
            messagebox.showerror("Export", str(e))
            return
        star = self._export_star_name()
        initial = str(self.image_dir or self.base_dir)
        path = filedialog.asksaveasfilename(
            title="Exporter au format AAVSO Extended",
            initialdir=initial,
            initialfile=f"{star.replace(' ', '_')}_aavso.csv",
            defaultextension=".csv",
            filetypes=[("CSV / texte AAVSO", "*.csv *.txt"), ("Tous", "*.*")],
        )
        if not path:
            return
        equip = getattr(config, "EQUIPMENT_OBSERVATION", {})
        delim = equip.get("delim", ",")
        if delim == "tab":
            delim_tag = "tab"
        else:
            delim_tag = delim if delim in (",", ";", "|") else ","
        try:
            export_aavso_extended_format(
                self.lc_df,
                Path(path),
                star_name=star,
                filt=self.filter_var.get().strip() or "V",
                delim=delim_tag,
            )
            messagebox.showinfo("Export AAVSO", f"Fichier enregistré :\n{path}")
        except Exception as e:
            messagebox.showerror("Export", str(e))
