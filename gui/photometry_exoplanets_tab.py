# gui/photometry_exoplanets_tab.py
import json
import os
import sys
import shutil
import zipfile
import subprocess
import importlib.util
import inspect
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from threading import Thread
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import csv
import pandas as pd
import numpy as np
from astropy.io import fits
from astropy.coordinates import EarthLocation, SkyCoord
import astropy.units as u
from io import StringIO


def _read_text_file_robust(file_path):
    """
    Lit un fichier texte en essayant plusieurs encodages (utf-8, utf-16, utf-8-sig, cp1252).
    Évite l'erreur 'utf-8' codec can't decode byte 0xff in position 0 lorsque le fichier
    a un BOM ou un autre encodage (ex. final-report.txt généré ailleurs).
    """
    encodings = ('utf-8', 'utf-16', 'utf-16-le', 'utf-16-be', 'utf-8-sig', 'cp1252', 'latin-1')
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Dernier recours : lire en binaire et décoder en ignorant les erreurs
    with open(file_path, 'rb') as f:
        return f.read().decode('utf-8', errors='replace')


def _to_utf8_no_bom(s):
    """Retourne les octets UTF-8 sans BOM pour upload ExoClock (évite erreur 0xff / UTF-16)."""
    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='replace')
    if s.startswith('\ufeff'):
        s = s[1:]
    return s.encode('utf-8', errors='replace')


def _pip_stderr_suggests_site_packages_denied(blob: str) -> bool:
    """WinError 5 / accès refusé au dossier env conda (souvent ProgramData\\Miniconda3)."""
    b = (blob or "").lower()
    return (
        "winerror 5" in b
        or "accès refusé" in b
        or "access is denied" in b
        or ("permission denied" in b and "site-packages" in b)
        or ("errno 13" in b and "permission" in b)
    )


def _read_csv_robust(file_path):
    """
    Lit un CSV avec plusieurs encodages (évite 'utf-8' codec can't decode byte 0xff).
    Force les colonnes de temps (JD-UTC, JD_UTC, BJD-TDB) en float pour une échelle correcte.
    Retourne un DataFrame pandas.
    """
    content = _read_text_file_robust(file_path)
    df = pd.read_csv(StringIO(content))
    for col in ('JD-UTC', 'JD_UTC', 'BJD-TDB'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


# --- Pipeline photométrie (batch legacy, conservé pour compatibilité interne) ---
from core.photometry_pipeline import PhotometryPipeline
from gui.manual_help import (
    add_manual_help_header,
    open_exoplanetpie_quickstart,
    open_user_manual_chapter,
)
import config

# --- NOUVEAU : On utilise UNIQUEMENT le visualiseur complet ---
from gui.lightcurve_fitting import LightcurveFitting

# --- Workflow ExoPlanetPie (panneau droit à côté de HOPS ; backend core/exoplanetpie_pipeline.py) ---
import matplotlib

matplotlib.use("Agg", force=False)
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from core.exoplanetpie_pipeline import (
    SUPPORTED_FILTERS,
    PlanetParams,
    TransitFitResult,
    detrend_and_normalize,
    diagnostics,
    download_satellite_lightcurve,
    fetch_planet_from_exoclock,
    fetch_planet_from_nasa_archive,
    fit_transit_batman_ultranest,
    fit_ttv,
    list_satellite_lightcurves,
    load_midtimes,
    load_ttv_result,
    merge_midtimes,
    save_midtimes,
    save_ttv_result,
    save_transit_segment,
    slice_transits,
)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Dossiers de travail (équivalent ExoPlanetPie.ini)
# ────────────────────────────────────────────────────────────────────────────
def default_work_root() -> Path:
    base = Path(config.OUTPUT_DIR) / "exoplanetpie"
    base.mkdir(parents=True, exist_ok=True)
    return base


def work_subdir(name: str) -> Path:
    p = default_work_root() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ────────────────────────────────────────────────────────────────────────────
# Utilitaire : lecture robuste d'un CSV `time, flux, flux_err`
# ────────────────────────────────────────────────────────────────────────────
def _read_lightcurve_csv(path: Path) -> Dict[str, np.ndarray]:
    """Accepte virgule, tab ou espace ; ignore les lignes commentaires (#)."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: List[List[float]] = []
    for ln in raw:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        # détection séparateur
        if "," in s:
            parts = [p.strip() for p in s.split(",")]
        elif "\t" in s:
            parts = [p.strip() for p in s.split("\t")]
        else:
            parts = s.split()
        try:
            vals = [float(p) for p in parts[:3] if p]
        except ValueError:
            # ligne d'en-tête
            continue
        if len(vals) >= 2:
            if len(vals) == 2:
                vals.append(float("nan"))
            rows.append(vals[:3])
    if not rows:
        raise ValueError(f"Aucune donnée numérique trouvée dans {path}.")
    arr = np.asarray(rows, dtype=float)
    return {"time": arr[:, 0], "flux": arr[:, 1], "flux_err": arr[:, 2]}


# ────────────────────────────────────────────────────────────────────────────
# Onglet principal
# ────────────────────────────────────────────────────────────────────────────
class ExoplanetPieWorkflowTab(ttk.Frame):
    """Panneau droit de « Photométrie Exoplanètes » : workflow ExoPlanetPie natif (à côté de HOPS)."""

    def __init__(self, parent, *, show_manual_help: bool = False):
        super().__init__(parent, padding=0)
        self.pack(fill=tk.BOTH, expand=True)
        if show_manual_help:
            add_manual_help_header(self, "4-photométrie-exoplanètes")

        # Barre d'aide propre au workflow ExoPlanetPie : raccourci vers le mode
        # d'emploi rapide (docs/EXOPLANETPIE_MODE_EMPLOI.md) et vers la section
        # détaillée §4.8 du manuel utilisateur.
        help_bar = ttk.Frame(self)
        help_bar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(2, 4))
        ttk.Label(
            help_bar,
            text="Workflow ExoPlanetPie natif — batman + ultranest + ExoTETHyS",
            font=("Arial", 9, "italic"),
            foreground="gray30",
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            help_bar,
            text="📖 Mode d'emploi rapide",
            command=lambda: open_exoplanetpie_quickstart(self.winfo_toplevel()),
        ).pack(side=tk.RIGHT, padx=(4, 2))
        ttk.Button(
            help_bar,
            text="Manuel §4.8…",
            command=lambda: open_user_manual_chapter(
                "48-workflow-exoplanetpie-natif", self.winfo_toplevel()
            ),
        ).pack(side=tk.RIGHT, padx=2)

        # État partagé entre sous-onglets
        self.planet: PlanetParams = PlanetParams()
        self.raw_lc: Optional[Dict[str, np.ndarray]] = None
        self.raw_lc_path: Optional[Path] = None
        self.segments: List[Dict[str, Any]] = []
        self.segment_paths: List[Path] = []
        self.fit_results: List[TransitFitResult] = []
        self.merger_rows: List[Dict[str, Any]] = []
        self.last_ttv_result = None

        # Diagnostics (batman/ultranest/lightkurve/exotethys)
        diag = diagnostics()
        if not all(diag.values()):
            missing = [k for k, ok in diag.items() if not ok]
            logger.warning("ExoPlanetPie workflow : dépendances manquantes -> %s", missing)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.tab_a = ttk.Frame(self.notebook)
        self.tab_b = ttk.Frame(self.notebook)
        self.tab_c = ttk.Frame(self.notebook)
        self.tab_d = ttk.Frame(self.notebook)
        self.tab_e = ttk.Frame(self.notebook)
        self.tab_f = ttk.Frame(self.notebook)
        self.tab_g = ttk.Frame(self.notebook)
        self.tab_h = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_a, text="A. Satellite Data")
        self.notebook.add(self.tab_b, text="B. NASA / AAVSO")
        self.notebook.add(self.tab_c, text="C. Get Planet")
        self.notebook.add(self.tab_d, text="D. Prepare Data")
        self.notebook.add(self.tab_e, text="E. Transit Fitter")
        self.notebook.add(self.tab_f, text="F. Transit Merger")
        self.notebook.add(self.tab_g, text="G. TTV")
        self.notebook.add(self.tab_h, text="H. Visualizer")

        self._build_tab_a()
        self._build_tab_b()
        self._build_tab_c()
        self._build_tab_d()
        self._build_tab_e()
        self._build_tab_f()
        self._build_tab_g()
        self._build_tab_h()

        # Barre de statut globale
        self.status_var = tk.StringVar(value=self._status_text(diag))
        ttk.Label(self, textvariable=self.status_var, foreground="gray", anchor="w").pack(
            fill="x", padx=4, pady=(0, 4)
        )

    # ──────────────────────────────────────────────────────────────────────
    # Statut / aide
    # ──────────────────────────────────────────────────────────────────────
    def _status_text(self, diag: Dict[str, bool]) -> str:
        parts = [f"{name}: {'✓' if ok else '✗'}" for name, ok in diag.items()]
        return "Dépendances — " + "   ".join(parts) + f"   |  Workdir : {default_work_root()}"

    def _set_busy(self, text: str) -> None:
        self.status_var.set(text)
        self.update_idletasks()

    def _post_threadsafe(self, fn, *args):
        self.after(0, lambda: fn(*args))

    # ──────────────────────────────────────────────────────────────────────
    # A. Satellite Data
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_a(self) -> None:
        frm = self.tab_a
        head = ttk.LabelFrame(frm, text="1. Rechercher des fichiers TESS / Kepler / K2 (lightkurve → MAST)", padding=8)
        head.pack(fill="x", padx=6, pady=6)

        row = ttk.Frame(head)
        row.pack(fill="x")
        ttk.Label(row, text="Cible :").pack(side="left")
        self.a_target_var = tk.StringVar(value="Toi-216")
        ttk.Entry(row, textvariable=self.a_target_var, width=22).pack(side="left", padx=4)
        ttk.Label(row, text="Mission :").pack(side="left", padx=(8, 0))
        self.a_mission_var = tk.StringVar(value="")
        ttk.Combobox(
            row, values=["", "TESS", "Kepler", "K2"], textvariable=self.a_mission_var, width=7, state="readonly"
        ).pack(side="left", padx=4)
        ttk.Button(row, text="Get List Satellite Files", command=self._a_search).pack(side="left", padx=8)

        list_frm = ttk.LabelFrame(frm, text="2. Sélectionner et télécharger", padding=8)
        list_frm.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("ok", "mission", "author", "year", "exptime", "target_name")
        self.a_tree = ttk.Treeview(list_frm, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (40, 80, 100, 60, 80, 160)):
            self.a_tree.heading(c, text=c)
            self.a_tree.column(c, width=w, anchor="w")
        self.a_tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(list_frm, orient="vertical", command=self.a_tree.yview)
        sb.pack(side="right", fill="y")
        self.a_tree.configure(yscrollcommand=sb.set)
        self.a_tree.bind("<Double-1>", self._a_toggle_ok)

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_frm, text="Tout cocher", command=lambda: self._a_set_all(True)).pack(side="left")
        ttk.Button(btn_frm, text="Tout décocher", command=lambda: self._a_set_all(False)).pack(side="left", padx=4)
        ttk.Button(btn_frm, text="Télécharger sélection", command=self._a_download).pack(side="left", padx=8)

    def _a_search(self) -> None:
        target = self.a_target_var.get().strip()
        mission = self.a_mission_var.get().strip() or None
        if not target:
            messagebox.showwarning("Cible manquante", "Renseignez un nom de cible.")
            return

        self._set_busy(f"Recherche MAST pour « {target} »…")
        self.a_tree.delete(*self.a_tree.get_children())

        def worker():
            try:
                rows = list_satellite_lightcurves(target, mission=mission)
                self._post_threadsafe(self._a_fill_results, rows)
            except Exception as exc:
                logger.exception("Recherche MAST échouée")
                self._post_threadsafe(messagebox.showerror, "Recherche MAST", str(exc))
                self._post_threadsafe(self._set_busy, "Erreur recherche MAST.")

        Thread(target=worker, daemon=True).start()

    def _a_fill_results(self, rows: List[Dict[str, Any]]) -> None:
        for r in rows:
            self.a_tree.insert(
                "",
                "end",
                iid=str(r["index"]),
                values=("✓" if r["ok"] else "", r["mission"], r["author"], r["year"], r["exptime"], r["target_name"]),
            )
        self._set_busy(f"{len(rows)} fichier(s) trouvé(s) sur MAST.")

    def _a_toggle_ok(self, _event) -> None:
        sel = self.a_tree.focus()
        if not sel:
            return
        vals = list(self.a_tree.item(sel, "values"))
        vals[0] = "" if vals[0] else "✓"
        self.a_tree.item(sel, values=vals)

    def _a_set_all(self, ok: bool) -> None:
        for iid in self.a_tree.get_children():
            vals = list(self.a_tree.item(iid, "values"))
            vals[0] = "✓" if ok else ""
            self.a_tree.item(iid, values=vals)

    def _a_download(self) -> None:
        selected = [
            int(iid) for iid in self.a_tree.get_children() if self.a_tree.item(iid, "values")[0]
        ]
        if not selected:
            messagebox.showinfo("Aucune sélection", "Cochez au moins une ligne (double-clic) puis Télécharger.")
            return
        out_dir = work_subdir("1_RawFiles") / self.a_target_var.get().strip().replace(" ", "_")

        def worker():
            saved: List[Path] = []
            for idx in selected:
                try:
                    self._post_threadsafe(self._set_busy, f"Téléchargement index {idx}…")
                    p = download_satellite_lightcurve(idx, out_dir)
                    saved.append(p)
                except Exception as exc:
                    logger.exception("Téléchargement %s échoué", idx)
                    self._post_threadsafe(messagebox.showerror, "Téléchargement", f"Index {idx} : {exc}")
            if saved:
                self._post_threadsafe(messagebox.showinfo, "Téléchargement", f"{len(saved)} LC enregistrées :\n{out_dir}")
                self._post_threadsafe(self._set_busy, f"Téléchargements terminés ({len(saved)}).")

        Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────
    # B. NASA / AAVSO
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_b(self) -> None:
        frm = self.tab_b
        ttk.Label(
            frm,
            text=(
                "Télécharger des observations AAVSO via NASA Exoplanet Watch.\n"
                "Pour le moment, on s'appuie sur les fichiers HOPS-compatibles (time, flux, flux_err).\n"
                "Téléversez vos propres fichiers ou un export AAVSO/HOPS pour les inclure dans le pipeline."
            ),
            justify="left",
            wraplength=560,
        ).pack(anchor="w", padx=10, pady=10)

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=10)
        ttk.Button(row, text="Importer fichiers HOPS / AAVSO…", command=self._b_import_files).pack(side="left")
        ttk.Button(row, text="Ouvrir le dossier 1_RawFiles…", command=lambda: os.startfile(work_subdir("1_RawFiles"))).pack(
            side="left", padx=8
        )

        self.b_imported_var = tk.StringVar(value="Aucun fichier importé.")
        ttk.Label(frm, textvariable=self.b_imported_var, foreground="gray").pack(anchor="w", padx=10, pady=(8, 0))

    def _b_import_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Fichiers AAVSO / HOPS (time flux flux_err)",
            filetypes=[("HOPS/AAVSO", "*.txt *.csv *.dat"), ("Tous", "*.*")],
        )
        if not paths:
            return
        dest = work_subdir("1_RawFiles") / "imports"
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for p in paths:
            try:
                lc = _read_lightcurve_csv(Path(p))
                out = dest / (Path(p).stem + ".csv")
                arr = np.column_stack([lc["time"], lc["flux"], lc["flux_err"]])
                np.savetxt(out, arr, delimiter=",", header="time_bjd_tdb,flux,flux_err", comments="")
                n += 1
            except Exception as exc:
                logger.exception("Import %s impossible : %s", p, exc)
        self.b_imported_var.set(f"{n} fichier(s) importé(s) dans {dest}")

    # ──────────────────────────────────────────────────────────────────────
    # C. Get Planet (ExoClock + NASA Archive)
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_c(self) -> None:
        frm = self.tab_c
        top = ttk.LabelFrame(frm, text="1. Récupérer les éphémérides", padding=8)
        top.pack(fill="x", padx=6, pady=6)

        row = ttk.Frame(top)
        row.pack(fill="x")
        ttk.Label(row, text="Nom planète :").pack(side="left")
        self.c_name_var = tk.StringVar(value="WASP-12 b")
        ttk.Entry(row, textvariable=self.c_name_var, width=20).pack(side="left", padx=4)
        ttk.Button(row, text="from ExoClock", command=lambda: self._c_fetch("exoclock")).pack(side="left", padx=4)
        ttk.Button(row, text="from NASA Archive", command=lambda: self._c_fetch("nasa")).pack(side="left", padx=4)
        ttk.Button(row, text="Charger fichier…", command=self._c_load_file).pack(side="left", padx=4)
        ttk.Button(row, text="Enregistrer…", command=self._c_save_file).pack(side="left", padx=4)

        body = ttk.LabelFrame(frm, text="2. Paramètres système (modifiables)", padding=8)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        self.c_entries: Dict[str, tk.StringVar] = {}
        fields = [
            ("name", "Nom"),
            ("ra_deg", "RA [deg]"),
            ("dec_deg", "DEC [deg]"),
            ("teff", "Teff [K]"),
            ("logg", "log g [cgs]"),
            ("feh", "[Fe/H]"),
            ("rstar_rsun", "R*  [Rsun]"),
            ("mstar_msun", "M*  [Msun]"),
            ("period_d", "P [j]"),
            ("t0_bjd", "T0 [BJD_TDB]"),
            ("rp_over_rs", "Rp/Rs"),
            ("sma_over_rs", "a/Rs"),
            ("inclination_deg", "inc [deg]"),
            ("eccentricity", "ecc"),
            ("arg_periastron_deg", "ω [deg]"),
            ("duration_d", "Durée transit [j]"),
            ("source", "Source"),
        ]
        for i, (key, label) in enumerate(fields):
            r, c = divmod(i, 2)
            ttk.Label(body, text=label + " :", anchor="e").grid(row=r, column=c * 2, sticky="e", padx=4, pady=2)
            var = tk.StringVar(value=str(getattr(self.planet, key)))
            self.c_entries[key] = var
            ttk.Entry(body, textvariable=var, width=22).grid(row=r, column=c * 2 + 1, sticky="ew", padx=4, pady=2)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(3, weight=1)

        ttk.Button(frm, text="Appliquer ces paramètres", command=self._c_apply).pack(pady=4)

    def _c_fetch(self, source: str) -> None:
        name = self.c_name_var.get().strip()
        if not name:
            return
        self._set_busy(f"Interrogation {source} pour « {name} »…")

        def worker():
            try:
                pl = (
                    fetch_planet_from_exoclock(name)
                    if source == "exoclock"
                    else fetch_planet_from_nasa_archive(name)
                )
                self._post_threadsafe(self._c_populate, pl)
            except Exception as exc:
                logger.exception("Recherche planète échouée")
                self._post_threadsafe(messagebox.showerror, "Get Planet", str(exc))
                self._post_threadsafe(self._set_busy, "Recherche planète : échec.")

        Thread(target=worker, daemon=True).start()

    def _c_populate(self, pl: PlanetParams) -> None:
        for key, var in self.c_entries.items():
            var.set(str(getattr(pl, key)))
        self.planet = pl
        self._set_busy(f"Planète « {pl.name} » chargée ({pl.source}).")

    def _c_apply(self) -> None:
        try:
            d = {}
            for key, var in self.c_entries.items():
                if key in ("name", "source"):
                    d[key] = var.get()
                else:
                    d[key] = float(var.get())
            self.planet = PlanetParams.from_dict(d)
            self._set_busy(f"Paramètres système appliqués : {self.planet.name}.")
        except ValueError as exc:
            messagebox.showerror("Erreur valeur", str(exc))

    def _c_save_file(self) -> None:
        self._c_apply()
        path = filedialog.asksaveasfilename(
            title="Enregistrer paramètres planète",
            defaultextension=".json",
            initialdir=work_subdir("planets"),
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self.planet.to_dict(), indent=2), encoding="utf-8")

    def _c_load_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Charger paramètres planète",
            initialdir=work_subdir("planets"),
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
        )
        if not path:
            return
        try:
            pl = PlanetParams.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
            self._c_populate(pl)
        except Exception as exc:
            messagebox.showerror("Chargement", str(exc))

    # ──────────────────────────────────────────────────────────────────────
    # D. Prepare Data
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_d(self) -> None:
        frm = self.tab_d
        top = ttk.LabelFrame(frm, text="1. Charger une light-curve", padding=8)
        top.pack(fill="x", padx=6, pady=6)
        row = ttk.Frame(top)
        row.pack(fill="x")
        ttk.Button(row, text="Charger fichier .csv / .txt", command=self._d_load_lc).pack(side="left")
        self.d_lc_label = ttk.Label(row, text="Aucun fichier", foreground="gray")
        self.d_lc_label.pack(side="left", padx=8)

        opts = ttk.LabelFrame(frm, text="2. Découpage par cycle (transits attendus)", padding=8)
        opts.pack(fill="x", padx=6, pady=6)
        ttk.Label(opts, text="Demi-fenêtre (heures) :").grid(row=0, column=0, sticky="e")
        self.d_window_var = tk.StringVar(value="6.0")
        ttk.Entry(opts, textvariable=self.d_window_var, width=8).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(opts, text="Ordre polynôme baseline (Detrend) :").grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.d_detrend_var = tk.StringVar(value="2")
        ttk.Spinbox(opts, from_=0, to=4, textvariable=self.d_detrend_var, width=4).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(opts, text="Découper en cycles", command=self._d_slice).grid(row=0, column=4, padx=8)

        # Liste des segments
        list_frm = ttk.LabelFrame(frm, text="3. Cycles trouvés", padding=4)
        list_frm.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("cycle", "t_expected", "n_points", "file")
        self.d_tree = ttk.Treeview(list_frm, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (60, 160, 80, 360)):
            self.d_tree.heading(c, text=c)
            self.d_tree.column(c, width=w, anchor="w")
        self.d_tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(list_frm, orient="vertical", command=self.d_tree.yview)
        sb.pack(side="right", fill="y")
        self.d_tree.configure(yscrollcommand=sb.set)

        ttk.Button(frm, text="Ouvrir 2_MidtimesFiles…", command=lambda: os.startfile(work_subdir("2_MidtimesFiles"))).pack(
            anchor="w", padx=6
        )

    def _d_load_lc(self) -> None:
        path = filedialog.askopenfilename(
            title="Light-curve (time, flux, flux_err)",
            initialdir=work_subdir("1_RawFiles"),
            filetypes=[("CSV/TXT", "*.csv *.txt *.dat"), ("Tous", "*.*")],
        )
        if not path:
            return
        try:
            lc = _read_lightcurve_csv(Path(path))
            self.raw_lc = lc
            self.raw_lc_path = Path(path)
            self.d_lc_label.config(text=Path(path).name, foreground="green")
            self._set_busy(f"LC chargée : {len(lc['time'])} points.")
        except Exception as exc:
            messagebox.showerror("Lecture LC", str(exc))

    def _d_slice(self) -> None:
        if self.raw_lc is None or self.raw_lc_path is None:
            messagebox.showwarning("LC manquante", "Chargez d'abord une light-curve.")
            return
        self._c_apply()
        try:
            window_h = float(self.d_window_var.get())
            detrend = int(self.d_detrend_var.get())
        except ValueError:
            messagebox.showerror("Paramètres", "Valeurs invalides pour fenêtre/ordre.")
            return

        f, fe = detrend_and_normalize(
            self.raw_lc["time"], self.raw_lc["flux"], self.raw_lc["flux_err"], None, poly_order=detrend
        )
        segments = slice_transits(
            self.raw_lc["time"],
            f,
            fe,
            t0_bjd=self.planet.t0_bjd,
            period_d=self.planet.period_d,
            selection_hours=window_h,
            duration_d=self.planet.duration_d,
        )
        if not segments:
            messagebox.showinfo("Aucun transit", "Aucun transit attendu n'a assez de points dans la fenêtre.")
            return

        out_dir = work_subdir("2_MidtimesFiles") / Path(self.raw_lc_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)

        self.segments = segments
        self.segment_paths = []
        self.d_tree.delete(*self.d_tree.get_children())
        for seg in segments:
            p = save_transit_segment(seg, out_dir)
            self.segment_paths.append(p)
            self.d_tree.insert(
                "", "end",
                values=(seg["cycle"], f"{seg['t_expected']:.5f}", len(seg["time"]), str(p))
            )
        self._set_busy(f"{len(segments)} cycle(s) sauvegardé(s) dans {out_dir}")

    # ──────────────────────────────────────────────────────────────────────
    # E. Transit Fitter (batman + ultranest + ExoTETHyS)
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_e(self) -> None:
        frm = self.tab_e
        cfg = ttk.LabelFrame(frm, text="1. Réglages du fit", padding=8)
        cfg.pack(fill="x", padx=6, pady=6)

        ttk.Label(cfg, text="Filtre :").grid(row=0, column=0, sticky="e")
        self.e_filter_var = tk.StringVar(value="TESS")
        ttk.Combobox(cfg, values=list(SUPPORTED_FILTERS), textvariable=self.e_filter_var, width=10, state="readonly").grid(
            row=0, column=1, sticky="w", padx=4
        )
        ttk.Label(cfg, text="Exposition (s) :").grid(row=0, column=2, sticky="e")
        self.e_exp_var = tk.StringVar(value="0.0")
        ttk.Entry(cfg, textvariable=self.e_exp_var, width=8).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(cfg, text="Detrend ordre :").grid(row=0, column=4, sticky="e")
        self.e_detrend_var = tk.StringVar(value="1")
        ttk.Spinbox(cfg, from_=0, to=4, textvariable=self.e_detrend_var, width=4).grid(row=0, column=5, sticky="w", padx=4)

        self.e_fit_rp_var = tk.BooleanVar(value=True)
        self.e_fit_a_var = tk.BooleanVar(value=False)
        self.e_fit_inc_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="fit Rp/Rs", variable=self.e_fit_rp_var).grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Checkbutton(cfg, text="fit a/Rs", variable=self.e_fit_a_var).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Checkbutton(cfg, text="fit inc.", variable=self.e_fit_inc_var).grid(row=1, column=2, sticky="w", padx=4)

        ttk.Label(cfg, text="live points :").grid(row=1, column=3, sticky="e")
        self.e_live_var = tk.StringVar(value="200")
        ttk.Entry(cfg, textvariable=self.e_live_var, width=8).grid(row=1, column=4, sticky="w", padx=4)
        ttk.Label(cfg, text="dlogz :").grid(row=1, column=5, sticky="e")
        self.e_dlogz_var = tk.StringVar(value="0.5")
        ttk.Entry(cfg, textvariable=self.e_dlogz_var, width=8).grid(row=1, column=6, sticky="w", padx=4)

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row, text="Charger dossier de cycles…", command=self._e_load_folder).pack(side="left")
        ttk.Button(row, text="Lancer fits (batman+ultranest)", command=self._e_run_fits).pack(side="left", padx=8)
        ttk.Button(row, text="Enregistrer mid-times…", command=self._e_save_midtimes).pack(side="left")

        list_frm = ttk.LabelFrame(frm, text="2. Résultats", padding=4)
        list_frm.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("cycle", "t0_bjd", "err_minus", "err_plus", "rp_over_rs", "chi2_red", "n_points")
        self.e_tree = ttk.Treeview(list_frm, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (60, 150, 90, 90, 100, 90, 80)):
            self.e_tree.heading(c, text=c)
            self.e_tree.column(c, width=w, anchor="w")
        self.e_tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(list_frm, orient="vertical", command=self.e_tree.yview)
        sb.pack(side="right", fill="y")
        self.e_tree.configure(yscrollcommand=sb.set)

    def _e_load_folder(self) -> None:
        d = filedialog.askdirectory(title="Dossier des cycles (étape D)", initialdir=work_subdir("2_MidtimesFiles"))
        if not d:
            return
        files = sorted(Path(d).glob("cycle_*.csv"))
        if not files:
            messagebox.showinfo("Aucun cycle", f"Aucun cycle_*.csv dans {d}")
            return
        self.segment_paths = files
        self.segments = []
        for fp in files:
            try:
                lc = _read_lightcurve_csv(fp)
                # cycle = ce qui suit "cycle_" dans le nom
                stem = fp.stem
                try:
                    cycle = int(stem.split("_")[-1])
                except Exception:
                    cycle = 0
                self.segments.append(
                    {"cycle": cycle, "t_expected": float(np.median(lc["time"])), "time": lc["time"], "flux": lc["flux"], "flux_err": lc["flux_err"]}
                )
            except Exception as exc:
                logger.exception("Lecture %s impossible : %s", fp, exc)
        self._set_busy(f"{len(self.segments)} cycle(s) chargé(s) depuis {d}")

    def _e_run_fits(self) -> None:
        if not self.segments:
            messagebox.showwarning("Aucun cycle", "Chargez ou découpez des cycles d'abord.")
            return
        self._c_apply()

        try:
            filt = self.e_filter_var.get()
            exp_s = float(self.e_exp_var.get())
            detrend = int(self.e_detrend_var.get())
            live = int(self.e_live_var.get())
            dlogz = float(self.e_dlogz_var.get())
        except ValueError:
            messagebox.showerror("Paramètres", "Valeur de fit invalide.")
            return

        fit_rp = self.e_fit_rp_var.get()
        fit_a = self.e_fit_a_var.get()
        fit_inc = self.e_fit_inc_var.get()
        planet = self.planet
        segments = list(self.segments)

        self.fit_results = []
        self.e_tree.delete(*self.e_tree.get_children())

        def worker():
            for seg in segments:
                try:
                    self._post_threadsafe(self._set_busy, f"Fit cycle {seg['cycle']:+d}…")
                    res = fit_transit_batman_ultranest(
                        time=seg["time"],
                        flux=seg["flux"],
                        flux_err=seg["flux_err"],
                        planet=planet,
                        cycle=int(seg["cycle"]),
                        filter_ui=filt,
                        fit_rp=fit_rp,
                        fit_a_rs=fit_a,
                        fit_inc=fit_inc,
                        detrend_order=detrend,
                        exp_time_s=exp_s,
                        min_num_live_points=live,
                        dlogz=dlogz,
                        progress_callback=lambda m: self._post_threadsafe(self._set_busy, m),
                    )
                    self.fit_results.append(res)
                    self._post_threadsafe(self._e_add_row, res)
                except Exception as exc:
                    logger.exception("Fit cycle %s échoué", seg.get("cycle"))
                    self._post_threadsafe(messagebox.showerror, "Fit", f"Cycle {seg.get('cycle')} : {exc}")
            self._post_threadsafe(self._set_busy, f"Fits terminés : {len(self.fit_results)} résultat(s).")

        Thread(target=worker, daemon=True).start()

    def _e_add_row(self, res: TransitFitResult) -> None:
        self.e_tree.insert(
            "",
            "end",
            values=(
                res.cycle,
                f"{res.t0_bjd:.6f}",
                f"{res.t0_err_minus * 24 * 60:.2f}m",
                f"{res.t0_err_plus * 24 * 60:.2f}m",
                f"{res.rp_over_rs:.5f}",
                f"{res.chi2_red:.2f}",
                res.n_points,
            ),
        )

    def _e_save_midtimes(self) -> None:
        if not self.fit_results:
            return
        out = filedialog.asksaveasfilename(
            title="Enregistrer mid-times",
            initialdir=work_subdir("3_MidTimes"),
            defaultextension=".csv",
            initialfile=f"midtimes_{self.planet.name.replace(' ', '_') or 'planet'}.csv",
        )
        if not out:
            return
        save_midtimes(self.fit_results, Path(out))
        self._set_busy(f"{len(self.fit_results)} mid-time(s) enregistrés : {out}")

    # ──────────────────────────────────────────────────────────────────────
    # F. Transit Merger
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_f(self) -> None:
        frm = self.tab_f
        row = ttk.Frame(frm)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Button(row, text="Charger fichier mid-times A…", command=lambda: self._f_load("a")).pack(side="left")
        ttk.Button(row, text="Charger fichier mid-times B…", command=lambda: self._f_load("b")).pack(side="left", padx=4)
        ttk.Button(row, text="Fusionner A + B", command=self._f_merge).pack(side="left", padx=8)
        ttk.Button(row, text="Enregistrer fusion…", command=self._f_save).pack(side="left")

        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True, padx=6, pady=6)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.f_tree_a = self._make_merger_tree(body, 0, 0, "A")
        self.f_tree_b = self._make_merger_tree(body, 0, 1, "B")
        self.f_tree_m = self._make_merger_tree(frm, None, None, "Fusion")
        self.f_tree_m.master.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._merger_data = {"a": [], "b": [], "m": []}

    def _make_merger_tree(self, parent, r: Optional[int], c: Optional[int], title: str):
        frm = ttk.LabelFrame(parent, text=title, padding=4)
        if r is not None and c is not None:
            frm.grid(row=r, column=c, sticky="nsew", padx=4)
        cols = ("ok", "cycle", "midtime", "err_minus", "err_plus")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=8)
        for k, w in zip(cols, (40, 60, 160, 90, 90)):
            tree.heading(k, text=k)
            tree.column(k, width=w, anchor="w")
        tree.pack(fill="both", expand=True)
        return tree

    def _f_load(self, which: str) -> None:
        p = filedialog.askopenfilename(
            title=f"Mid-times {which.upper()}",
            initialdir=work_subdir("3_MidTimes"),
            filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
        )
        if not p:
            return
        try:
            rows = load_midtimes(Path(p))
        except Exception as exc:
            messagebox.showerror("Lecture", str(exc))
            return
        self._merger_data[which] = rows
        tree = self.f_tree_a if which == "a" else self.f_tree_b
        tree.delete(*tree.get_children())
        for r in rows:
            tree.insert(
                "",
                "end",
                values=(
                    "✓" if r.get("ok", 1) else "",
                    r.get("cycle", 0),
                    f"{r.get('transit_midtime', 0.0):.6f}",
                    f"{r.get('transit_midtime_min', 0.0):.6f}",
                    f"{r.get('transit_midtime_plus', 0.0):.6f}",
                ),
            )
        self._set_busy(f"{len(rows)} ligne(s) chargée(s) dans {which.upper()}.")

    def _f_merge(self) -> None:
        self._c_apply()
        merged = merge_midtimes(
            self._merger_data["a"],
            self._merger_data["b"],
            period_d=self.planet.period_d,
        )
        self._merger_data["m"] = merged
        self.f_tree_m.delete(*self.f_tree_m.get_children())
        for r in merged:
            self.f_tree_m.insert(
                "",
                "end",
                values=(
                    "✓" if r.get("ok", 1) else "",
                    r.get("cycle", 0),
                    f"{r.get('transit_midtime', 0.0):.6f}",
                    f"{r.get('transit_midtime_min', 0.0):.6f}",
                    f"{r.get('transit_midtime_plus', 0.0):.6f}",
                ),
            )
        self.merger_rows = merged
        self._set_busy(f"Fusion : {len(merged)} ligne(s).")

    def _f_save(self) -> None:
        if not self.merger_rows:
            return
        p = filedialog.asksaveasfilename(
            title="Enregistrer fusion",
            defaultextension=".csv",
            initialdir=work_subdir("3_MidTimes"),
            initialfile="midtimes_merged.csv",
        )
        if not p:
            return
        cols = ["ok", "cycle", "transit_midtime", "transit_midtime_min", "transit_midtime_plus"]
        with Path(p).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in self.merger_rows:
                w.writerow({k: r.get(k, "") for k in cols})

    # ──────────────────────────────────────────────────────────────────────
    # G. TTV (O-C)
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_g(self) -> None:
        frm = self.tab_g
        row = ttk.Frame(frm)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Button(row, text="Charger mid-times…", command=self._g_load).pack(side="left")
        ttk.Label(row, text="Modèle :").pack(side="left", padx=(8, 0))
        self.g_model_var = tk.StringVar(value="linear")
        ttk.Combobox(row, values=["linear", "quadratic", "sin"], textvariable=self.g_model_var,
                     width=10, state="readonly").pack(side="left", padx=4)
        ttk.Button(row, text="Fit O-C", command=self._g_fit).pack(side="left", padx=8)
        ttk.Button(row, text="Enregistrer résultat…", command=self._g_save).pack(side="left")
        ttk.Button(
            row,
            text="Aide (manuel)…",
            command=lambda: open_user_manual_chapter(
                "48-workflow-exoplanetpie-natif", self.winfo_toplevel()
            ),
        ).pack(side="right", padx=4)

        # Figure O-C
        self.g_fig = Figure(figsize=(7, 4), dpi=100)
        self.g_ax = self.g_fig.add_subplot(111)
        self.g_ax.set_xlabel("Cycle")
        self.g_ax.set_ylabel("O - C (minutes)")
        self.g_canvas = FigureCanvasTkAgg(self.g_fig, master=frm)
        self.g_canvas.draw()
        self.g_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)
        toolbar = NavigationToolbar2Tk(self.g_canvas, frm, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")

        self.g_summary_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.g_summary_var, anchor="w", justify="left").pack(fill="x", padx=6)

        self._g_rows: List[Dict[str, Any]] = []

    def _g_load(self) -> None:
        p = filedialog.askopenfilename(
            title="Mid-times à analyser",
            initialdir=work_subdir("3_MidTimes"),
            filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
        )
        if not p:
            return
        try:
            self._g_rows = load_midtimes(Path(p))
        except Exception as exc:
            messagebox.showerror("Lecture", str(exc))
            return
        self._set_busy(f"TTV : {len(self._g_rows)} mid-times chargés.")

    def _g_fit(self) -> None:
        if not self._g_rows:
            messagebox.showwarning("Aucun mid-time", "Chargez d'abord un fichier mid-times.")
            return
        try:
            result = fit_ttv(self._g_rows, model=self.g_model_var.get())
        except Exception as exc:
            messagebox.showerror("Fit O-C", str(exc))
            return

        self.last_ttv_result = result
        self.g_ax.clear()
        self.g_ax.errorbar(
            result.cycles,
            result.o_minus_c_d * 24 * 60,
            yerr=[
                [r.get("transit_midtime_min", 0.001) * 24 * 60 for r in self._g_rows[: len(result.cycles)]],
                [r.get("transit_midtime_plus", 0.001) * 24 * 60 for r in self._g_rows[: len(result.cycles)]],
            ],
            fmt="o",
            ms=4,
        )
        self.g_ax.axhline(0, color="gray", lw=0.5)
        self.g_ax.set_xlabel("Cycle")
        self.g_ax.set_ylabel("O - C (minutes)")
        self.g_ax.set_title(
            f"{self.planet.name or 'TTV'} — modèle {result.model}, χ²_r = {result.chi2_red:.2f}, RMS = {result.rms_minutes:.2f} min"
        )
        self.g_canvas.draw()

        extra = ", ".join(f"{k} = {v:.6g}" for k, v in result.extra.items())
        self.g_summary_var.set(
            f"P = {result.period_d:.8f} j ; T0 = {result.t0_bjd:.6f} BJD ; "
            f"{extra if extra else 'aucun paramètre supplémentaire'}"
        )
        self._set_busy(f"Fit TTV ({result.model}) terminé.")

    def _g_save(self) -> None:
        if self.last_ttv_result is None:
            return
        p = filedialog.asksaveasfilename(
            title="Enregistrer résultat TTV",
            defaultextension=".json",
            initialdir=work_subdir("4_TTVFitter"),
            initialfile=f"ttv_{self.planet.name.replace(' ', '_') or 'planet'}_{self.last_ttv_result.model}.json",
        )
        if not p:
            return
        save_ttv_result(self.last_ttv_result, Path(p))
        self._set_busy(f"Résultat TTV sauvegardé : {p}")

    # ──────────────────────────────────────────────────────────────────────
    # H. Visualizer
    # ──────────────────────────────────────────────────────────────────────
    def _build_tab_h(self) -> None:
        frm = self.tab_h
        row = ttk.Frame(frm)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Button(row, text="Get TTV Analysis Result…", command=self._h_load).pack(side="left")
        self.h_summary = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.h_summary, justify="left", anchor="w").pack(fill="x", padx=6, pady=4)

        self.h_fig = Figure(figsize=(7, 4), dpi=100)
        self.h_ax = self.h_fig.add_subplot(111)
        self.h_canvas = FigureCanvasTkAgg(self.h_fig, master=frm)
        self.h_canvas.draw()
        self.h_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)

    def _h_load(self) -> None:
        p = filedialog.askopenfilename(
            title="Résultat TTV (.json)",
            initialdir=work_subdir("4_TTVFitter"),
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
        )
        if not p:
            return
        try:
            result = load_ttv_result(Path(p))
        except Exception as exc:
            messagebox.showerror("Visualiser TTV", str(exc))
            return

        self.h_ax.clear()
        self.h_ax.plot(result.cycles, result.o_minus_c_d * 24 * 60, "o", ms=4)
        self.h_ax.axhline(0, color="gray", lw=0.5)
        self.h_ax.set_xlabel("Cycle")
        self.h_ax.set_ylabel("O - C (minutes)")
        self.h_ax.set_title(
            f"{Path(p).stem} — modèle {result.model}, χ²_r = {result.chi2_red:.2f}, RMS = {result.rms_minutes:.2f} min"
        )
        self.h_canvas.draw()

        extra = ", ".join(f"{k} = {v:.6g}" for k, v in result.extra.items())
        self.h_summary.set(
            f"Fichier : {p}\nP = {result.period_d:.8f} j ; T0 = {result.t0_bjd:.6f} BJD ; "
            f"{extra if extra else '∅'}"
        )
        self._set_busy(f"TTV affiché : {Path(p).name}")


class PhotometryExoplanetsTab(ttk.Frame):
    """
    Onglet photométrie exoplanètes : HOPS modifié (gauche) et workflow ExoPlanetPie natif (droite).
    """

    def __init__(self, parent, base_dir=None):
        super().__init__(parent, padding=0)
        self.base_dir = str(base_dir) if base_dir is not None else None
        self.data_analysis_tab = None
        
        # Instanciation du pipeline
        self.pipeline = PhotometryPipeline()

        self.ref_image = None
        self.target_coord = None
        self.comp_coords = []
        self.current_selections = None

        self.create_widgets()

    def create_widgets(self):
        main_paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_paned, padding=0)
        right_frame = ttk.Frame(main_paned, padding=0)
        main_paned.add(left_frame, weight=1)
        main_paned.add(right_frame, weight=1)
        add_manual_help_header(left_frame, "4-photométrie-exoplanètes")
        try:
            main_paned.pane(left_frame, minsize=260)
            main_paned.pane(right_frame, minsize=380)
        except tk.TclError:
            pass
        self.after_idle(lambda: self._set_photometry_paned_sash(main_paned))

        hops_frame = ttk.LabelFrame(left_frame, text="HOPS modifié", padding=8)
        hops_frame.pack(fill="both", expand=True, pady=4, padx=(4, 2))

        hops_btn_row = ttk.Frame(hops_frame)
        hops_btn_row.pack(fill="x")
        ttk.Button(
            hops_btn_row,
            text="Installer / Réinstaller HOPS (ZIP)",
            command=self.install_hops_from_zip,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            hops_btn_row,
            text="Lancer HOPS",
            command=self.launch_hops,
        ).pack(side="left")
        ttk.Button(
            hops_btn_row,
            text="Réinitialiser HOPS",
            command=self.reset_hops,
        ).pack(side="left", padx=(6, 0))

        self.hops_embed_host = ttk.Frame(hops_frame)
        self.hops_embed_host.pack(fill="both", expand=True, pady=(8, 0))
        # Zone à défilement : HOPS (grille + figures) peut dépasser la hauteur du panneau.
        self.hops_canvas = None
        self.hops_scrollbar = None
        self.hops_canvas_window_id = None
        self.hops_isolated_container = None
        self.hops_app = None
        self._build_hops_scrollable_embed()

        # Conservé pour compatibilité interne, mais non affiché.
        self.hops_status_var = tk.StringVar(value=self._hops_status_text())
        ttk.Label(
            hops_frame,
            text="MIT License\nCopyright (c) 2017 Angelos Tsiaras and Konstantinos Karpouzas\nHOPS-modified integration: J.P Vignes <jeanpascal.vignes@gmail.com>",
            justify="left",
        ).pack(anchor="w", pady=(6, 0))
        
        # Variables conservées pour compatibilité avec les fonctions batch appelées ailleurs.
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(hops_frame, variable=self.progress_var, maximum=100)
        self.lbl_progress = ttk.Label(hops_frame, text="En attente...", font=("Arial", 8))

        # Panneau droit : même onglet que HOPS — workflow ExoPlanetPie natif (A … H), dans un cadre dédié.
        workflow_outer = ttk.LabelFrame(
            right_frame,
            text="Workflow ExoPlanetPie natif (batman · ultranest · ExoTETHyS)",
            padding=4,
        )
        workflow_outer.pack(fill=tk.BOTH, expand=True, padx=(2, 4), pady=4)
        analysis_host = ttk.Frame(workflow_outer)
        analysis_host.pack(fill=tk.BOTH, expand=True)
        try:
            self.data_analysis_tab = ExoplanetPieWorkflowTab(analysis_host, show_manual_help=False)
        except Exception as e:
            logging.error(
                "Intégration ExoPlanetPie workflow dans Photométrie Exoplanètes impossible: %s",
                e,
                exc_info=True,
            )
            self.data_analysis_tab = None
            ttk.Label(
                analysis_host,
                text=f"ExoPlanetPie workflow indisponible :\n{e}",
                foreground="red",
                wraplength=420,
                justify="left",
            ).pack(anchor="w", padx=8, pady=8)

    def _set_photometry_paned_sash(self, paned: ttk.Panedwindow) -> None:
        """Place la séparation ~45 % / 55 % (HOPS / analyse) après géométrie connue."""
        try:
            paned.update_idletasks()
            w = int(paned.winfo_width())
            if w > 80:
                paned.sashpos(0, max(200, int(w * 0.45)))
        except tk.TclError:
            pass

    def _build_hops_scrollable_embed(self) -> None:
        scroll_wrap = ttk.Frame(self.hops_embed_host)
        scroll_wrap.pack(fill="both", expand=True)
        try:
            bg = scroll_wrap.cget("background")
        except tk.TclError:
            bg = None
        if not bg:
            bg = "#f5f5f5" if sys.platform == "win32" else "#ececec"
        self.hops_canvas = tk.Canvas(scroll_wrap, highlightthickness=0, borderwidth=0, bg=bg)
        self.hops_scrollbar = ttk.Scrollbar(scroll_wrap, orient="vertical", command=self.hops_canvas.yview)
        self.hops_canvas.configure(yscrollcommand=self.hops_scrollbar.set)
        self.hops_scrollbar.pack(side="right", fill="y")
        self.hops_canvas.pack(side="left", fill="both", expand=True)

        self.hops_isolated_container = ttk.Frame(self.hops_canvas)
        self.hops_canvas_window_id = self.hops_canvas.create_window(
            (0, 0), window=self.hops_isolated_container, anchor="nw"
        )
        self.hops_isolated_container.bind("<Configure>", self._on_hops_embed_inner_configure)
        self.hops_canvas.bind("<Configure>", self._on_hops_embed_canvas_configure)
        self._bind_hops_embed_mousewheel(self.hops_canvas)
        self._bind_hops_embed_mousewheel(self.hops_isolated_container)

    def _on_hops_embed_inner_configure(self, event) -> None:
        if self.hops_canvas is None:
            return
        try:
            self.hops_canvas.configure(scrollregion=self.hops_canvas.bbox("all"))
        except tk.TclError:
            pass

    def _on_hops_embed_canvas_configure(self, event) -> None:
        if self.hops_canvas is None or self.hops_canvas_window_id is None:
            return
        try:
            self.hops_canvas.itemconfigure(self.hops_canvas_window_id, width=event.width)
        except tk.TclError:
            pass

    def _on_hops_embed_mousewheel(self, event) -> None:
        if self.hops_canvas is None:
            return
        if getattr(event, "delta", 0):
            self.hops_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4:
            self.hops_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.hops_canvas.yview_scroll(1, "units")

    def _bind_hops_embed_mousewheel(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_hops_embed_mousewheel)
        widget.bind("<Button-4>", self._on_hops_embed_mousewheel)
        widget.bind("<Button-5>", self._on_hops_embed_mousewheel)

    def _recreate_hops_isolated_container(self) -> None:
        """Recrée la surface Tk accueillie dans le canvas (après fermeture HOPS ou réinitialisation)."""
        if self.hops_canvas is None:
            self._build_hops_scrollable_embed()
            return
        if self.hops_app is not None:
            try:
                self.hops_app.close()
            except Exception:
                pass
            self.hops_app = None
        if self.hops_canvas_window_id is not None:
            try:
                self.hops_canvas.delete(self.hops_canvas_window_id)
            except tk.TclError:
                pass
            self.hops_canvas_window_id = None
        self.hops_isolated_container = ttk.Frame(self.hops_canvas)
        self.hops_canvas_window_id = self.hops_canvas.create_window(
            (0, 0), window=self.hops_isolated_container, anchor="nw"
        )
        self.hops_isolated_container.bind("<Configure>", self._on_hops_embed_inner_configure)
        self._bind_hops_embed_mousewheel(self.hops_isolated_container)

    def browse_ref(self):
        """Legacy NPOAP (sélection FITS + target_selector) — remplacé par HOPS."""
        messagebox.showinfo(
            "Photométrie FITS",
            "La photométrie sur images FITS dans cet onglet passe par HOPS (panneau gauche).\n"
            "Utilisez « Lancer HOPS » pour T1, comparateurs et ouvertures.",
        )

    def launch_selector(self):
        """Legacy — voir browse_ref ; ne plus appeler target_selector depuis cet onglet."""
        self.browse_ref()

    def open_aperture_dialog(self):
        if not self.ref_image or not self.target_coord: return
        try:
            self.pipeline.launch_photometry_aperture(
                fits_path=self.ref_image,
                target_coord=self.target_coord,
                comp_coords=self.comp_coords,
                on_finish=self.on_aperture_confirmed
            )
        except Exception as e:
            logging.error(f"Erreur ouverture interface aperture: {e}")
            messagebox.showerror("Erreur", f"Interface aperture: {e}")

    def on_aperture_confirmed(self, final_selections):
        if not final_selections:
            return
        self.current_selections = final_selections
        logging.info(f"Ouvertures validées pour {len(final_selections)} étoiles")
        
        t1 = next((s for s in final_selections if s['label'] == 'T1'), None)
        if not t1:
            messagebox.showwarning("Attention", "T1 est désactivée ! Réactivez-la.")
            self.lbl_aperture_status.config(text="T1 manquante", foreground="red")
            self.btn_batch.config(state="disabled")
            return
            
        self.target_coord = t1['coord']
        self.comp_coords = [s['coord'] for s in final_selections if s['label'] != 'T1']
        self.lbl_aperture_status.config(text="Validé", foreground="green")
        self.btn_batch.config(state="normal")

    def launch_batch(self):
        if not self.current_selections:
            messagebox.showwarning("Erreur", "Validez d'abord les ouvertures (Étape 3)")
            return

        initial = self.base_dir or getattr(config, "CALIBRATED_DIR", os.getcwd())
        science_dir = filedialog.askdirectory(title="Dossier images science", initialdir=initial)
        if not science_dir: return

        logging.info(f"Batch démarré sur {science_dir}")
        self.progress_var.set(0)
        self.lbl_progress.config(text="Traitement en cours...")

        Thread(target=self.run_batch, args=(science_dir,), daemon=True).start()

    def run_batch(self, science_dir):
        try:
            self.pipeline.process_photometry_series(
                folder=science_dir,
                target_coord=self.target_coord,
                comps=self.comp_coords,
                ref_image=self.ref_image,
                selections=self.current_selections,
                progress_callback=self.update_progress_ui
            )
            res_csv = Path(science_dir) / "photometrie" / "results.csv"
            self.after(0, lambda: self.on_batch_success(res_csv))
        except Exception as e:
            logging.error(f"Batch échoué: {e}")
            self.after(0, lambda: messagebox.showerror("Erreur Batch", str(e)))

    def update_progress_ui(self, percent):
        self.after(0, lambda: self.progress_var.set(percent))
        self.after(0, lambda: self.lbl_progress.config(text=f"{percent:.1f}%"))

    def on_batch_success(self, csv_path):
        self.lbl_progress.config(text="Terminé !")
        if messagebox.askyesno("Succès", "Photométrie terminée !\nOuvrir l'analyseur avancé ?"):
            self.open_advanced_analysis(csv_path)

    def open_advanced_analysis(self, csv_path=None):
        """
        Ouvre le visualiseur complet (detrending + modélisation)
        Si csv_path=None → demande à l'utilisateur
        """
        if csv_path is None:
            initial = self.base_dir or os.getcwd()
            csv_path = filedialog.askopenfilename(
                title="Ouvrir results.csv",
                initialdir=initial,
                filetypes=[("CSV", "*.csv")]
            )
        if not csv_path or not Path(csv_path).exists():
            return

        try:
            window = LightcurveFitting(self)
            window.load_from_path(csv_path)
            logging.info(f"Analyse avancée ouverte : {csv_path}")
        except Exception as e:
            logging.error(f"Erreur ouverture analyse : {e}")
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{e}")

    def save_equipment_config(self):
        """Sauvegarde les spécifications matériel dans config.py"""
        try:
            import config
            
            # Préparer le dictionnaire
            equipment_data = {
                "obs_code": self.equip_obs_code.get().strip(),
                "camera": self.equip_camera.get().strip(),
                "binning": self.equip_binning.get().strip(),
                "delim": self.equip_delim.get().strip()
            }
            
            # Lire le fichier config.py
            config_path = Path(__file__).parent.parent / "config.py"
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Trouver et remplacer la section EQUIPMENT_OBSERVATION
            import re
            pattern = r'(EQUIPMENT_OBSERVATION\s*=\s*\{)(.*?)(\})'
            
            new_section = (
                "EQUIPMENT_OBSERVATION = {\n"
                f'    "obs_code": {json.dumps(equipment_data["obs_code"])},           # Code observateur AAVSO (5 caractères max)\n'
                f'    "camera": {json.dumps(equipment_data["camera"])},             # Nom de la caméra\n'
                f'    "binning": {json.dumps(equipment_data["binning"])},         # Binning (1x1, 2x2, 3x3, 4x4)\n'
                f'    "delim": {json.dumps(equipment_data["delim"])},             # Délimiteur pour rapports (, ; | : ! / ? ou tab)\n'
                "}"
            )
            
            if re.search(pattern, content, re.DOTALL):
                content = re.sub(pattern, new_section, content, flags=re.DOTALL)
            else:
                # Ajouter avant la dernière ligne si pas trouvé
                content += "\n\n" + new_section + "\n"
            
            # Écrire le fichier
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Mettre à jour le module config
            config.EQUIPMENT_OBSERVATION = equipment_data
            
            messagebox.showinfo("Succès", "Spécifications matériel sauvegardées dans config.py")
            logging.info("Spécifications matériel sauvegardées")
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lors de la sauvegarde:\n{e}")
            logging.error(f"Erreur sauvegarde équipement: {e}")

    def _npoap_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _hops_base_dir(self) -> Path:
        return self._npoap_root() / "external_apps" / "hops"

    def _hops_source_dir(self) -> Path:
        return self._hops_base_dir() / "hops-master"

    def _hops_entry_file(self) -> Path:
        return self._hops_source_dir() / "hops" / "__main__.py"

    def _hops_status_text(self) -> str:
        if self._hops_entry_file().is_file():
            return f"HOPS prêt : {self._hops_source_dir()}"
        return "HOPS non installé (utilisez le bouton d'installation depuis ZIP)."

    def _default_hops_zip(self) -> Path:
        # Priorité à l'archive fournie dans la distribution NPOAP.
        bundled = self._hops_base_dir() / "HOPS-modified.zip"
        if bundled.is_file():
            return bundled
        return Path.home() / "Downloads" / "hops-master.zip"

    def _ensure_hops_dependencies(self) -> None:
        """Installe les dépendances HOPS manquantes dans l'environnement Python courant."""
        # Le premier import qui casse est généralement `exoclock`.
        if importlib.util.find_spec("exoclock") is not None:
            return

        req = self._hops_source_dir() / "requirements.txt"
        if not req.is_file():
            raise FileNotFoundError(f"requirements.txt introuvable: {req}")

        self.hops_status_var.set("Installation dépendances HOPS (exoclock, etc.)...")
        self.update_idletasks()

        progress_dialog = tk.Toplevel(self)
        progress_dialog.title("HOPS - Installation dépendances")
        progress_dialog.geometry("460x150")
        progress_dialog.transient(self.winfo_toplevel())
        progress_dialog.grab_set()
        progress_dialog.resizable(False, False)

        progress_label = ttk.Label(
            progress_dialog,
            text="Installation des dépendances HOPS en cours...\nMerci de patienter.",
            justify="center",
        )
        progress_label.pack(pady=(18, 10), padx=12)

        progress_bar = ttk.Progressbar(progress_dialog, mode="indeterminate", length=360)
        progress_bar.pack(pady=(0, 10))
        progress_bar.start(10)

        ttk.Label(
            progress_dialog,
            text="(L'installation peut durer plusieurs minutes.)",
            foreground="gray",
        ).pack()

        progress_dialog.update_idletasks()
        logging.info(f"HOPS: installation dépendances depuis {req}")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            if proc.returncode != 0:
                logging.error("HOPS pip install échec (code %s):\n%s", proc.returncode, out or "(pas de sortie)")
                py = sys.executable
                req_s = str(req)
                if _pip_stderr_suggests_site_packages_denied(out):
                    raise RuntimeError(
                        "Installation des paquets HOPS refusée (accès en écriture à site-packages).\n\n"
                        "Avec Miniconda installé pour tous les utilisateurs (dossier ProgramData), "
                        "il faut souvent lancer pip une fois avec des droits administrateur, "
                        "ou donner à votre compte le contrôle du dossier "
                        r"…\envs\astroenv\Lib\site-packages"
                        ".\n\n"
                        "Ouvrez une invite de commandes ou PowerShell « Exécuter en tant qu’administrateur », puis :\n\n"
                        f'    "{py}" -m pip install -r "{req_s}"\n\n'
                        "Ensuite relancez « Lancer HOPS » depuis NPOAP."
                    )
                raise RuntimeError(
                    "L’installation pip des dépendances HOPS a échoué.\n"
                    "Consultez le journal NPOAP pour la sortie complète de pip."
                )
        finally:
            progress_bar.stop()
            try:
                progress_dialog.grab_release()
            except Exception:
                pass
            progress_dialog.destroy()

    def _register_gaia_filters_from_resources(self) -> None:
        """
        Enregistre automatiquement les passbands Gaia de resources/filters
        dans hops.pylightcurve41 au lancement de HOPS.
        """
        filters_dir = self._npoap_root() / "resources" / "filters"
        mapping = {
            "GAIA_G": filters_dir / "GAIA_G.txt",
            "GAIA_BP": filters_dir / "GAIA_BP.txt",
            "GAIA_RP": filters_dir / "GAIA_RP.txt",
        }
        try:
            import hops.pylightcurve41 as plc
        except Exception as e:
            logging.warning(f"Impossible d'importer hops.pylightcurve41 pour enregistrer les filtres Gaia: {e}")
            return

        try:
            existing = set(plc.all_filters())
        except Exception as e:
            logging.warning(f"Impossible de lister les filtres pylightcurve (all_filters): {e}")
            existing = set()

        for filter_name, filter_path in mapping.items():
            if not filter_path.is_file():
                logging.warning(f"Passband Gaia manquant: {filter_path}")
                continue
            if filter_name in existing:
                logging.info(f"Passband Gaia deja disponible: {filter_name}")
                continue
            try:
                plc.add_filter(filter_name, str(filter_path))
                logging.info(f"Passband Gaia enregistre: {filter_name} <- {filter_path}")
            except Exception as e:
                logging.warning(f"Echec enregistrement passband Gaia {filter_name}: {e}")

    def _enable_hops_embedded_mode_source(self) -> None:
        """Patche la copie locale de HOPS pour supporter un mode embarqué."""
        app_windows = self._hops_source_dir() / "hops" / "application_windows.py"
        app_file = self._hops_source_dir() / "hops" / "application.py"
        if not app_windows.is_file() or not app_file.is_file():
            raise FileNotFoundError("Fichiers HOPS introuvables pour le patch embarqué.")

        txt = app_windows.read_text(encoding="utf-8", errors="replace")
        if "embedded=False" not in txt:
            txt = txt.replace(
                "def __init__(self, log=HOPSLog, name='HOPS - window', sizex=None, sizey=None, position=5):",
                "def __init__(self, log=HOPSLog, name='HOPS - window', sizex=None, sizey=None, position=5, embedded=False, host_root=None, host_frame=None):",
            )
            txt = txt.replace(
                "        self.root = Tk()\n        self.hide()\n        self.main_frame = self.root\n        self.root.protocol('WM_DELETE_WINDOW', self.close)",
                "        self.embedded = bool(embedded)\n\n        if self.embedded:\n            if host_root is None or host_frame is None:\n                raise ValueError(\"Embedded mode requires host_root and host_frame\")\n            self.root = host_root\n            self.main_frame = host_frame\n        else:\n            self.root = Tk()\n            self.main_frame = self.root\n            self.root.protocol('WM_DELETE_WINDOW', self.close)\n            self.hide()",
            )
            txt = txt.replace(
                "        self.root.wm_title(name)\n        if sizex and sizey:\n            self.root.geometry('{0}x{1}'.format(int(self.root.winfo_screenwidth() / sizex),\n                                                int(self.root.winfo_screenheight() / sizey)))",
                "        if not self.embedded:\n            self.root.wm_title(name)\n            if sizex and sizey:\n                self.root.geometry('{0}x{1}'.format(int(self.root.winfo_screenwidth() / sizex),\n                                                    int(self.root.winfo_screenheight() / sizey)))",
            )
            txt = txt.replace(
                "class MainWindow(HOPSWindow):\n\n    def __init__(self, log, name, sizex=None, sizey=None, position=5):\n\n        HOPSWindow.__init__(self, log, name, sizex, sizey, position)",
                "class MainWindow(HOPSWindow):\n\n    def __init__(self, log, name, sizex=None, sizey=None, position=5, embedded=False, host_root=None, host_frame=None):\n\n        HOPSWindow.__init__(self, log, name, sizex, sizey, position, embedded=embedded, host_root=host_root, host_frame=host_frame)",
            )
            app_windows.write_text(txt, encoding="utf-8")
        # Correctif géométrie Tk: tous les widgets doivent cibler main_frame en mode embarqué.
        txt = app_windows.read_text(encoding="utf-8", errors="replace")
        txt = txt.replace("widget = Label(window.root, textvar=self.variable)", "widget = Label(window.main_frame, textvar=self.variable)")
        txt = txt.replace("widget = Frame(window.root)", "widget = Frame(window.main_frame)")
        app_windows.write_text(txt, encoding="utf-8")

        txt2 = app_file.read_text(encoding="utf-8", errors="replace")
        if "def __init__(self, embedded=False, host_root=None, host_frame=None):" not in txt2:
            txt2 = txt2.replace(
                "    def __init__(self):",
                "    def __init__(self, embedded=False, host_root=None, host_frame=None):",
            )
            txt2 = txt2.replace(
                "        MainWindow.__init__(self, HOPSLog(), name='HOPS-modified (A. Tsiaras, K. Karpouzas) - J.P Vignes <jeanpascal.vignes@gmail.com>', position=1)",
                "        MainWindow.__init__(self, HOPSLog(), name='HOPS-modified (A. Tsiaras, K. Karpouzas) - J.P Vignes <jeanpascal.vignes@gmail.com>', position=1, embedded=embedded, host_root=host_root, host_frame=host_frame)",
            )
            app_file.write_text(txt2, encoding="utf-8")

        txt2 = app_file.read_text(encoding="utf-8", errors="replace")
        if "NPOAP: embedded close callback" not in txt2:
            old_sig = (
                "    def __init__(self, embedded=False, host_root=None, host_frame=None):\n\n"
                "        MainWindow.__init__(self, HOPSLog(), name='HOPS-modified (A. Tsiaras, K. Karpouzas) - J.P Vignes <jeanpascal.vignes@gmail.com>', position=1, "
                "embedded=embedded, host_root=host_root, host_frame=host_frame)"
            )
            new_sig = (
                "    def __init__(self, embedded=False, host_root=None, host_frame=None, on_embedded_close=None):  "
                "# NPOAP: embedded close callback\n\n"
                "        self._on_embedded_close = on_embedded_close if embedded else None\n"
                "        MainWindow.__init__(self, HOPSLog(), name='HOPS-modified (A. Tsiaras, K. Karpouzas) - J.P Vignes <jeanpascal.vignes@gmail.com>', position=1, "
                "embedded=embedded, host_root=host_root, host_frame=host_frame)"
            )
            if old_sig in txt2:
                txt2 = txt2.replace(old_sig, new_sig, 1)
            old_block = "        self.update_window()\n\n    def open_updates(self):"
            new_block = (
                "        self.update_window()\n\n"
                "    def close(self):\n"
                "        MainWindow.close(self)\n"
                "        if self.embedded and getattr(self, '_on_embedded_close', None):\n"
                "            cb = self._on_embedded_close\n"
                "            self._on_embedded_close = None\n"
                "            try:\n"
                "                cb()\n"
                "            except Exception:\n"
                "                traceback.print_exc()\n\n"
                "    def open_updates(self):"
            )
            if old_block in txt2:
                txt2 = txt2.replace(old_block, new_block, 1)
            app_file.write_text(txt2, encoding="utf-8")

        self._patch_hops_on_embedded_close_fallback(app_file)

        self._patch_hops_embedded_frame_safe(app_windows)

    def _patch_hops_on_embedded_close_fallback(self, app_file: Path) -> None:
        """
        Si le ZIP HOPS a une signature embarquée sans on_embedded_close (échec du patch
        par chaîne exacte), complète le fichier pour éviter TypeError au lancement.
        """
        txt = app_file.read_text(encoding="utf-8", errors="replace")
        if "on_embedded_close" in txt:
            return
        old = (
            "    def __init__(self, embedded=False, host_root=None, host_frame=None):\n\n"
            "        MainWindow.__init__(self, HOPSLog()"
        )
        new = (
            "    def __init__(self, embedded=False, host_root=None, host_frame=None, "
            "on_embedded_close=None):  # NPOAP: embedded close callback\n\n"
            "        self._on_embedded_close = on_embedded_close if embedded else None\n\n"
            "        MainWindow.__init__(self, HOPSLog()"
        )
        if old not in txt:
            return
        txt = txt.replace(old, new, 1)
        if "    def close(self):\n        MainWindow.close(self)" not in txt:
            anchor = "    def open_updates(self):"
            insert = (
                "    def close(self):\n"
                "        MainWindow.close(self)\n"
                "        if self.embedded and getattr(self, '_on_embedded_close', None):\n"
                "            cb = self._on_embedded_close\n"
                "            self._on_embedded_close = None\n"
                "            try:\n"
                "                cb()\n"
                "            except Exception:\n"
                "                traceback.print_exc()\n\n"
                f"{anchor}"
            )
            if anchor in txt:
                txt = txt.replace(anchor, insert, 1)
        app_file.write_text(txt, encoding="utf-8")

    @staticmethod
    def _invalidate_hops_import_cache() -> None:
        """Force le rechargement des modules hops depuis le disque après patch."""
        for name in list(sys.modules):
            if name == "hops" or name.startswith("hops."):
                del sys.modules[name]

    def _patch_hops_embedded_frame_safe(self, app_windows: Path) -> None:
        """Complète le patch embarqué : Frame n'a pas geometry/protocol/mainloop."""
        txt = app_windows.read_text(encoding="utf-8", errors="replace")
        if "NPOAP: embedded frame-safe" in txt:
            return
        if "host_frame" not in txt or "self.embedded" not in txt:
            return

        old = """    def reposition(self):

        self.root.update_idletasks()

        if self.position == 1:"""
        new = """    def reposition(self):

        self.root.update_idletasks()

        # NPOAP: embedded frame-safe (Frame host has no geometry/protocol)
        if self.embedded:
            try:
                self.main_frame.update_idletasks()
            except TclError:
                pass
            return

        if self.position == 1:"""
        if old not in txt:
            return
        txt = txt.replace(old, new, 1)

        old = """    def show(self):

        self.reposition()

        self.root.wm_attributes("-topmost", 1)"""
        new = """    def show(self):

        self.reposition()

        if self.embedded:
            self.update_idletasks()
            return

        # Garder les fenêtres HOPS auxiliaires visibles au-dessus de NPOAP.
        self.root.wm_attributes("-topmost", 1)
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except TclError:
            pass
        self.update_idletasks()
        return"""
        txt = txt.replace(old, new, 1)

        old = """    def hide(self):

        self.root.withdraw()"""
        new = """    def hide(self):

        if self.embedded:
            return

        self.root.withdraw()"""
        txt = txt.replace(old, new, 1)

        old = """        self.after(f_after)

        self.root.mainloop()"""
        new = """        self.after(f_after)

        if self.embedded:
            return

        self.root.mainloop()"""
        txt = txt.replace(old, new, 1)

        old = """    def def_close(self):

        if self.mainloop_on:
            self.root.quit()

        for job in self.jobs:
            self.root.after_cancel(job)

        self.root.destroy()"""
        new = """    def def_close(self):

        if not self.embedded:
            if self.mainloop_on:
                self.root.quit()

        for job in self.jobs:
            try:
                self.root.after_cancel(job)
            except TclError:
                pass
        self.jobs.clear()

        if self.embedded:
            self.mainloop_on = False
            try:
                for w in list(self.main_frame.winfo_children()):
                    w.destroy()
            except TclError:
                pass
            return

        self.root.destroy()"""
        txt = txt.replace(old, new, 1)

        old = """    def disable(self):

        self.root.protocol('WM_DELETE_WINDOW', self.no_action)"""
        new = """    def disable(self):

        if not self.embedded:
            self.root.protocol('WM_DELETE_WINDOW', self.no_action)"""
        txt = txt.replace(old, new, 1)

        old = """    def activate(self):

        self.root.protocol('WM_DELETE_WINDOW', self.close)"""
        new = """    def activate(self):

        if not self.embedded:
            self.root.protocol('WM_DELETE_WINDOW', self.close)"""
        txt = txt.replace(old, new, 1)

        old = """    def set_close_button_function(self, function):
        self.root.protocol('WM_DELETE_WINDOW', function)"""
        new = """    def set_close_button_function(self, function):
        if self.embedded:
            return
        self.root.protocol('WM_DELETE_WINDOW', function)"""
        txt = txt.replace(old, new, 1)

        # Evite de contaminer le theme ttk global de NPOAP via theme_use().
        txt = txt.replace(
            "            combostyle = Style()\n"
            "            combostyle.theme_create('combostyle', parent='alt',\n"
            "                                    settings={'TCombobox': {'configure':\n"
            "                                                                {'selectbackground': 'white',\n"
            "                                                                 'fieldbackground': 'white',\n"
            "                                                                 'background': 'white'}}})\n"
            "            combostyle.theme_use('combostyle')",
            "            style_name = 'HOPS.TCombobox'\n"
            "            combostyle = Style()\n"
            "            combostyle.configure(style_name,\n"
            "                                selectbackground='white',\n"
            "                                fieldbackground='white',\n"
            "                                background='white')"
        )
        txt = txt.replace(
            "        if width:\n"
            "            widget = Combobox(window.main_frame, textvariable=self.variable, state='readonly', width=width)\n"
            "        else:\n"
            "            widget = Combobox(window.main_frame, textvariable=self.variable, state='readonly', width=int(window.log.entries_width * 0.8))",
            "        if width:\n"
            "            widget = Combobox(window.main_frame, textvariable=self.variable, state='readonly', width=width, style=style_name)\n"
            "        else:\n"
            "            widget = Combobox(window.main_frame, textvariable=self.variable, state='readonly', width=int(window.log.entries_width * 0.8), style=style_name)"
        )

        app_windows.write_text(txt, encoding="utf-8")

    def install_hops_from_zip(self) -> None:
        initial_zip = self._default_hops_zip()
        # Si l'archive de distribution est présente, on l'utilise directement.
        if initial_zip.is_file():
            path = str(initial_zip)
        else:
            path = filedialog.askopenfilename(
                title="Sélectionner HOPS-modified.zip / hops-master.zip",
                initialdir=str(initial_zip.parent if initial_zip.parent.exists() else Path.home()),
                filetypes=[("Archive ZIP", "*.zip"), ("Tous", "*.*")],
            )
            if not path:
                return
        try:
            zip_path = Path(path)
            if not zip_path.is_file():
                raise FileNotFoundError("Archive ZIP introuvable.")

            base = self._hops_base_dir()
            source = self._hops_source_dir()
            base.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.rmtree(source)
            # Extraction robuste : accepte soit un ZIP racine "hops-master/", soit un ZIP
            # contenant directement "hops/" et les scripts d'installation.
            with tempfile.TemporaryDirectory() as td:
                tmp_dir = Path(td)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_dir)

                # Cherche le dossier racine qui contient hops/__main__.py
                candidate_root = None
                if (tmp_dir / "hops" / "__main__.py").is_file():
                    candidate_root = tmp_dir
                else:
                    for p in tmp_dir.rglob("__main__.py"):
                        if p.parent.name == "hops":
                            candidate_root = p.parent.parent
                            break

                if candidate_root is None:
                    raise RuntimeError("Structure ZIP invalide : impossible de trouver hops/__main__.py")

                shutil.copytree(candidate_root, source)
            self._enable_hops_embedded_mode_source()

            if not self._hops_entry_file().is_file():
                raise RuntimeError("Structure HOPS inattendue : __main__.py introuvable.")

            self.hops_app = None
            self.hops_status_var.set(self._hops_status_text())
            messagebox.showinfo("HOPS", f"Installation terminée dans :\n{source}")
            logging.info(f"HOPS installé depuis {zip_path} vers {source}")
        except Exception as e:
            logging.error(f"Installation HOPS impossible: {e}", exc_info=True)
            messagebox.showerror("HOPS", f"Échec installation HOPS:\n{e}")

    def launch_hops(self) -> None:
        source = self._hops_source_dir()
        if not self._hops_entry_file().is_file():
            messagebox.showwarning(
                "HOPS",
                "HOPS n'est pas installé.\nUtilisez d'abord « Installer / Réinstaller HOPS (ZIP) ».",
            )
            return
        try:
            # Intégration en mode embarqué dans le cadre HOPS (pas de fenêtre externe).
            added_path = False
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
                added_path = True
            self._enable_hops_embedded_mode_source()
            self._invalidate_hops_import_cache()
            self._ensure_hops_dependencies()
            self._register_gaia_filters_from_resources()

            from hops.application import HOPS
            if added_path:
                try:
                    sys.path.remove(str(source))
                except ValueError:
                    pass

            self._recreate_hops_isolated_container()

            hops_kw: dict = dict(
                embedded=True,
                host_root=self.hops_isolated_container,
                host_frame=self.hops_isolated_container,
            )
            if "on_embedded_close" in inspect.signature(HOPS.__init__).parameters:
                hops_kw["on_embedded_close"] = self._on_hops_embedded_closed
            self.hops_app = HOPS(**hops_kw)
            self.hops_app.run(f_after=self.hops_app.log.check_for_updates)
            self.hops_status_var.set(f"HOPS intégré dans le cadre depuis : {source}")
            logging.info(f"HOPS intégré dans l'onglet Exoplanètes: source={source}")
        except RuntimeError as e:
            logging.error("Lancement HOPS impossible: %s", e)
            messagebox.showerror("HOPS — dépendances", str(e))
        except Exception as e:
            logging.error(f"Lancement HOPS impossible: {e}", exc_info=True)
            messagebox.showerror("HOPS", f"Impossible de lancer HOPS:\n{e}")

    def _on_hops_embedded_closed(self) -> None:
        """Appelé par HOPS après EXIT en mode embarqué (cadre vidé, référence à nettoyer)."""
        self.hops_app = None
        self.hops_status_var.set(
            "HOPS fermé (EXIT). Cliquez sur « Lancer HOPS » pour rouvrir."
        )

    def reset_hops(self) -> None:
        """Réinitialise HOPS embarqué et recharge la fenêtre principale dans le cadre."""
        try:
            self.hops_status_var.set("HOPS réinitialisé. Rechargement en cours...")
            self.launch_hops()
        except Exception as e:
            logging.error(f"Réinitialisation HOPS impossible: {e}", exc_info=True)
            messagebox.showerror("HOPS", f"Impossible de réinitialiser HOPS:\n{e}")

