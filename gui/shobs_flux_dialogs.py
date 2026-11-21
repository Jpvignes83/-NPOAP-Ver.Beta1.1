"""Dialogues Tk pour lancer SHOBS-FLUX et importer un profil caméra."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable


def launch_shobs_flux_ui(parent) -> None:
    try:
        from core.shobs_flux_bridge import is_installed, launch_shobs_flux, status_text

        if not is_installed():
            messagebox.showerror(
                "SHOBS-FLUX",
                "SHOBS-FLUX est introuvable dans external_apps/shobs_flux/.",
                parent=parent,
            )
            return
        launch_shobs_flux()
        messagebox.showinfo(
            "SHOBS-FLUX",
            "SHOBS-FLUX a été lancé dans une fenêtre séparée.\n\n"
            f"{status_text()}\n\n"
            "Après un bench / dark run et « Save to camera profile », "
            "utilisez « Importer profil SHOBS ».",
            parent=parent,
        )
    except Exception as e:
        messagebox.showerror("SHOBS-FLUX", str(e), parent=parent)


def prompt_import_camera_profile(
    parent,
    *,
    telescope_name: str = "",
    on_imported: Callable[[dict], None] | None = None,
) -> None:
    try:
        from core.shobs_flux_bridge import (
            apply_camera_profile_to_npoap,
            cameras_dir,
            hops_snippet_from_summary,
            list_camera_profiles,
        )
    except Exception as e:
        messagebox.showerror("Import SHOBS", str(e), parent=parent)
        return

    profiles = list_camera_profiles()
    if not profiles:
        messagebox.showwarning(
            "Import SHOBS",
            "Aucun profil caméra trouvé dans\n"
            f"{cameras_dir()}\n\n"
            "Lancez SHOBS-FLUX, mesurez (Camera → Bench/Dark), "
            "puis « Save to camera profile ».",
            parent=parent,
        )
        return

    win = tk.Toplevel(parent)
    win.title("Importer un profil caméra SHOBS-FLUX")
    try:
        win.transient(parent.winfo_toplevel())
    except Exception:
        pass
    win.grab_set()

    ttk.Label(
        win,
        text="Choisissez un profil (~/.shobs/cameras) à injecter dans NPOAP :",
        wraplength=480,
    ).pack(anchor="w", padx=10, pady=(10, 4))

    listbox = tk.Listbox(win, width=80, height=min(12, max(4, len(profiles))))
    listbox.pack(fill="both", expand=True, padx=10, pady=4)
    for p in profiles:
        listbox.insert(tk.END, p.label())
    listbox.selection_set(0)

    detail = ttk.Label(win, text="", foreground="gray", wraplength=480, justify="left")
    detail.pack(anchor="w", padx=10, pady=4)

    def _on_select(_evt=None):
        sel = listbox.curselection()
        if not sel:
            return
        p = profiles[int(sel[0])]
        detail.config(
            text="\n".join(
                [
                    f"Fichier : {p.path.name}",
                    f"Gain : {p.gain_e_per_adu}"
                    + (f" ({p.sources.get('gain_e_per_adu', '')})" if p.gain_e_per_adu is not None else ""),
                    f"RN : {p.read_noise_e}"
                    + (f" ({p.sources.get('read_noise_e', '')})" if p.read_noise_e is not None else ""),
                    f"Dark : {p.dark_current_e_per_s}",
                    f"Limite linéaire : {p.linear_limit_adu} ADU",
                    f"Saturation : {p.saturation_adu} ADU",
                ]
            )
        )

    listbox.bind("<<ListboxSelect>>", _on_select)
    _on_select()

    def _apply():
        sel = listbox.curselection()
        if not sel:
            return
        p = profiles[int(sel[0])]
        try:
            eq = apply_camera_profile_to_npoap(p)
            snippet = hops_snippet_from_summary(p, telescope=telescope_name)
            try:
                win.clipboard_clear()
                win.clipboard_append(snippet)
                clip_note = "\n\nUn résumé HOPS a été copié dans le presse-papiers."
            except Exception:
                clip_note = ""
            if on_imported is not None:
                on_imported(eq)
            messagebox.showinfo(
                "Import SHOBS",
                "Profil importé dans config.json :\n"
                + "\n".join(f"  {k} = {v}" for k, v in eq.items())
                + clip_note,
                parent=win,
            )
            win.destroy()
        except Exception as exc:
            messagebox.showerror("Import SHOBS", str(exc), parent=win)

    btns = ttk.Frame(win)
    btns.pack(fill="x", padx=10, pady=10)
    ttk.Button(btns, text="Importer", command=_apply).pack(side="left", padx=(0, 8))
    ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="left")


def prompt_import_system_profile(
    parent,
    *,
    on_imported: Callable[[dict], None] | None = None,
) -> None:
    try:
        from core.shobs_flux_bridge import (
            apply_system_profile_to_npoap,
            list_system_profiles,
            shobs_data_dir,
        )
    except Exception as e:
        messagebox.showerror("Import système SHOBS", str(e), parent=parent)
        return

    profiles = list_system_profiles()
    if not profiles:
        messagebox.showwarning(
            "Import système SHOBS",
            "Aucun profil système trouvé dans\n"
            f"{shobs_data_dir() / 'systems'}\n\n"
            "Lancez un run Sky (dossier de lights) puis sauvegardez le profil système.",
            parent=parent,
        )
        return

    win = tk.Toplevel(parent)
    win.title("Importer un profil système SHOBS-FLUX")
    try:
        win.transient(parent.winfo_toplevel())
    except Exception:
        pass
    win.grab_set()

    ttk.Label(
        win,
        text="Choisissez un profil (~/.shobs/systems) → ZP / extinction / seeing NPOAP :",
        wraplength=480,
    ).pack(anchor="w", padx=10, pady=(10, 4))

    listbox = tk.Listbox(win, width=80, height=min(12, max(4, len(profiles))))
    listbox.pack(fill="both", expand=True, padx=10, pady=4)
    for p in profiles:
        listbox.insert(tk.END, p.label())
    listbox.selection_set(0)

    detail = ttk.Label(win, text="", foreground="gray", wraplength=480, justify="left")
    detail.pack(anchor="w", padx=10, pady=4)

    def _on_select(_evt=None):
        sel = listbox.curselection()
        if not sel:
            return
        p = profiles[int(sel[0])]
        detail.config(
            text="\n".join(
                [
                    f"Fichier : {p.path.name}",
                    f"Télescope : {p.telescope_name}",
                    f"Caméra : {p.camera_profile}",
                    f"Bandes : {', '.join(p.bands) or '—'}",
                    f"ZP : {p.zero_point}",
                    f"Extinction k : {p.extinction_k}",
                    f"Seeing : {p.seeing_fwhm_arcsec}",
                ]
            )
        )

    listbox.bind("<<ListboxSelect>>", _on_select)
    _on_select()

    def _apply():
        sel = listbox.curselection()
        if not sel:
            return
        p = profiles[int(sel[0])]
        try:
            eq = apply_system_profile_to_npoap(p)
            if on_imported is not None:
                on_imported(eq)
            messagebox.showinfo(
                "Import système SHOBS",
                "Profil système importé dans config.json (bloc onsky) :\n"
                + "\n".join(f"  {k} = {v}" for k, v in eq.items() if k != "bands")
                + (f"\n  bands = {list((eq.get('bands') or {}).keys())}" if eq.get("bands") else ""),
                parent=win,
            )
            win.destroy()
        except Exception as exc:
            messagebox.showerror("Import système SHOBS", str(exc), parent=win)

    btns = ttk.Frame(win)
    btns.pack(fill="x", padx=10, pady=10)
    ttk.Button(btns, text="Importer", command=_apply).pack(side="left", padx=(0, 8))
    ttk.Button(btns, text="Annuler", command=win.destroy).pack(side="left")
