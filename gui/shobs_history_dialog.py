"""Dialogue Historique instrument + rapport PDF (SHOBS-FLUX / NPOAP Phase 4)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class ShobsHistoryDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Historique instrument (SHOBS-FLUX)")
        self.geometry("980x720")
        try:
            self.transient(parent.winfo_toplevel())
        except Exception:
            pass

        self._setups: list[dict] = []
        self._available: list[tuple] = []
        self._points: list[dict] = []
        self._fig = None
        self._canvas = None

        self._build()
        self.after(50, self.refresh_setups)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Setup:").pack(side="left")
        self.setup_var = tk.StringVar()
        self.setup_combo = ttk.Combobox(top, textvariable=self.setup_var, width=55, state="readonly")
        self.setup_combo.pack(side="left", padx=(4, 10))
        self.setup_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_setup_changed())

        ttk.Label(top, text="Valeur:").pack(side="left")
        self.value_var = tk.StringVar()
        self.value_combo = ttk.Combobox(top, textvariable=self.value_var, width=35, state="readonly")
        self.value_combo.pack(side="left", padx=(4, 10))
        self.value_combo.bind("<<ComboboxSelected>>", lambda _e: self.redraw())

        ttk.Label(top, text="Événement (YYYY-MM-DD):").pack(side="left")
        self.event_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.event_var, width=12).pack(side="left", padx=(4, 8))
        ttk.Button(top, text="Tracer", command=self.redraw).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        self.plot_host = ttk.Frame(mid)
        self.plot_host.pack(fill="both", expand=True)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="both", expand=False)

        left = ttk.LabelFrame(bottom, text="Runs récents", padding=4)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.runs_list = tk.Listbox(left, height=8)
        self.runs_list.pack(fill="both", expand=True)
        run_btns = ttk.Frame(left)
        run_btns.pack(fill="x", pady=(4, 0))
        ttk.Button(run_btns, text="Retirer du graphique", command=self.remove_selected_run).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(run_btns, text="Rafraîchir", command=self.refresh_all).pack(side="left")

        right = ttk.LabelFrame(bottom, text="Export / Rapport", padding=4)
        right.pack(side="right", fill="y")
        ttk.Button(right, text="Exporter CSV…", command=self.export_csv, width=22).pack(fill="x", pady=2)
        ttk.Button(right, text="Exporter PNG…", command=self.export_png, width=22).pack(fill="x", pady=2)
        ttk.Button(right, text="Rapport système PDF…", command=self.make_report, width=22).pack(
            fill="x", pady=2
        )
        ttk.Button(right, text="Rapport partagé PDF…", command=lambda: self.make_report(share=True), width=22).pack(
            fill="x", pady=2
        )
        ttk.Button(right, text="Fermer", command=self.destroy, width=22).pack(fill="x", pady=(10, 2))

        self.status = ttk.Label(self, text="", foreground="gray")
        self.status.pack(anchor="w", padx=10, pady=(0, 8))

    def _selected_setup(self) -> dict | None:
        idx = self.setup_combo.current()
        if idx < 0 or idx >= len(self._setups):
            return None
        return self._setups[idx]

    def _selected_value(self) -> tuple | None:
        idx = self.value_combo.current()
        if idx < 0 or idx >= len(self._available):
            return None
        return self._available[idx]

    def refresh_setups(self) -> None:
        try:
            from core.shobs_flux_history import history_status_text, list_recent_runs, list_setups

            self._setups = list_setups()
            labels = [s.get("words") or s.get("id") or "?" for s in self._setups]
            self.setup_combo["values"] = labels
            if labels:
                self.setup_combo.current(0)
                self.on_setup_changed()
            else:
                self.value_combo["values"] = []
                self.status.config(text=history_status_text() + " — aucun setup (lancez Bench/Sky d'abord).")
            self._fill_runs(list_recent_runs(limit=60))
            if labels:
                self.status.config(text=history_status_text())
        except Exception as e:
            messagebox.showerror("Historique", str(e), parent=self)

    def refresh_all(self) -> None:
        self.refresh_setups()
        self.redraw()

    def on_setup_changed(self) -> None:
        setup = self._selected_setup()
        if not setup:
            return
        try:
            from core.shobs_flux_history import available_values

            self._available = available_values(setup["kind"], setup["id"])
            labels = [f"{words} (n={n})" for _k, _c, words, n in self._available]
            self.value_combo["values"] = labels
            if labels:
                self.value_combo.current(0)
            self.redraw()
        except Exception as e:
            messagebox.showerror("Historique", str(e), parent=self)

    def redraw(self) -> None:
        setup = self._selected_setup()
        val = self._selected_value()
        if not setup or not val:
            return
        key, channel, words, _n = val
        try:
            from core.shobs_flux_history import draw_trend_figure, series_points

            self._points = series_points(
                setup["kind"], setup["id"], key=key, channel=channel if channel is not None else "*"
            )
            unit = ""
            if self._points:
                unit = str(self._points[0].get("unit") or "")

            for child in self.plot_host.winfo_children():
                child.destroy()
            if self._fig is not None:
                plt.close(self._fig)

            self._fig = plt.figure(figsize=(9.0, 3.8))
            draw_trend_figure(self._fig, self._points, words, unit, event=self.event_var.get().strip())
            self._canvas = FigureCanvasTkAgg(self._fig, master=self.plot_host)
            self._canvas.get_tk_widget().pack(fill="both", expand=True)
            self._canvas.draw()
            self.status.config(
                text=f"{setup.get('words')} · {words} · {len(self._points)} point(s)"
            )
        except Exception as e:
            messagebox.showerror("Historique", str(e), parent=self)

    def _fill_runs(self, runs: list[dict]) -> None:
        self.runs_list.delete(0, tk.END)
        self._runs = runs
        for r in runs:
            kind = r.get("kind") or "?"
            started = str(r.get("started") or "")[:19]
            status = r.get("status") or ""
            src = Path(str(r.get("source") or "")).name or str(r.get("source") or "")
            self.runs_list.insert(tk.END, f"{kind:6}  {started}  [{status}]  {src}")

    def remove_selected_run(self) -> None:
        sel = self.runs_list.curselection()
        if not sel:
            return
        run = self._runs[int(sel[0])]
        key = run.get("run_key")
        if not key:
            return
        if not messagebox.askyesno(
            "Historique",
            "Retirer ce run des tendances ?\n(Rien n'est effacé ; il peut être remis via SHOBS-FLUX.)",
            parent=self,
        ):
            return
        try:
            from core.shobs_flux_history import set_run_removed

            set_run_removed(str(key), True)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Historique", str(e), parent=self)

    def export_csv(self) -> None:
        if not self._points:
            messagebox.showwarning("Export", "Aucun point à exporter.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            from core.shobs_flux_history import export_series_csv

            setup = self._selected_setup() or {}
            export_series_csv(path, self._points, setup.get("words") or "")
            messagebox.showinfo("Export", f"CSV enregistré :\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Export", str(e), parent=self)

    def export_png(self) -> None:
        if self._fig is None:
            messagebox.showwarning("Export", "Aucun graphique à exporter.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter PNG",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if not path:
            return
        try:
            from core.shobs_flux_history import stamp_trend_figure

            stamp_trend_figure(self._fig)
            self._fig.savefig(path, dpi=150)
            messagebox.showinfo("Export", f"PNG enregistré :\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Export", str(e), parent=self)

    def make_report(self, share: bool = False) -> None:
        try:
            from core.shobs_flux_history import (
                default_report_name,
                list_system_profile_paths,
                write_system_report_pdf,
            )
        except Exception as e:
            messagebox.showerror("Rapport", str(e), parent=self)
            return

        systems = list_system_profile_paths()
        if not systems:
            messagebox.showwarning(
                "Rapport",
                "Aucun profil système dans ~/.shobs/systems/.\n"
                "Lancez d'abord un run Sky et sauvegardez le profil.",
                parent=self,
            )
            return

        win = tk.Toplevel(self)
        win.title("Choisir le profil système")
        win.transient(self)
        win.grab_set()
        lb = tk.Listbox(win, width=70, height=min(12, max(4, len(systems))))
        lb.pack(fill="both", expand=True, padx=10, pady=10)
        for pid, _p in systems:
            lb.insert(tk.END, pid)
        lb.selection_set(0)

        def _go():
            sel = lb.curselection()
            if not sel:
                return
            pid, path = systems[int(sel[0])]
            win.destroy()
            dest = filedialog.asksaveasfilename(
                parent=self,
                title="Enregistrer le rapport PDF",
                initialfile=default_report_name(path, share=share),
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
            )
            if not dest:
                return
            try:
                out, n = write_system_report_pdf(
                    path,
                    dest,
                    share=share,
                    event=self.event_var.get().strip(),
                )
                messagebox.showinfo(
                    "Rapport",
                    f"Rapport PDF ({n} page(s)) :\n{out}",
                    parent=self,
                )
            except Exception as e:
                messagebox.showerror("Rapport", str(e), parent=self)

        ttk.Button(win, text="Générer…", command=_go).pack(pady=(0, 10))


def open_shobs_history(parent) -> None:
    ShobsHistoryDialog(parent)
