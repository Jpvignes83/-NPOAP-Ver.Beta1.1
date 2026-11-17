# gui/nina_control_tab.py
"""
Contrôle à distance de NINA (API HTTP v2) : connexion, slew, capture, séquence.
Les cibles de séquence proviennent de l'onglet « Observation de la Nuit » (cases ☑).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from threading import Thread
from tkinter import messagebox, scrolledtext, ttk
from typing import TYPE_CHECKING, List, Optional, Tuple

import tkinter as tk

from config import get_nina_config, persist_nina_config
from core.nina_client import NinaClient, NinaConnectionConfig, api_success
from core.nina_sequence import (
    NinaSequenceAborted,
    NinaSequencePlan,
    NinaSequenceRunner,
    NinaSequenceTarget,
    build_filter_steps,
    parse_filter_names_csv,
)
from gui.manual_help import add_manual_help_header

if TYPE_CHECKING:
    from gui.night_observation_tab import NightObservationTab, EphemerisObject

logger = logging.getLogger(__name__)


class NinaControlTab(ttk.Frame):
    """Onglet de pilotage NINA (Tailscale / réseau local)."""

    def __init__(self, parent, night_observation_tab: Optional["NightObservationTab"] = None):
        super().__init__(parent)
        self._night_tab = night_observation_tab

        _nina = get_nina_config()
        self.nina_host_var = tk.StringVar(value=str(_nina.get("host", "127.0.0.1")))
        self.nina_port_var = tk.StringVar(value=str(_nina.get("port", 1888)))
        self.nina_protocol_var = tk.StringVar(value=str(_nina.get("protocol", "http")))
        self.nina_capture_duration_var = tk.StringVar(
            value=str(_nina.get("capture_duration_s", 30.0))
        )
        self.nina_capture_gain_var = tk.StringVar(value=str(_nina.get("capture_gain", 56.0)))
        self.nina_slew_center_var = tk.BooleanVar(value=bool(_nina.get("slew_center", False)))
        self.nina_seq_filters_var = tk.StringVar(value=str(_nina.get("seq_filters", "G,G bp,G rp")))
        self.nina_seq_frames_var = tk.StringVar(value=str(_nina.get("seq_frames_per_filter", 3)))
        self.nina_seq_cool_var = tk.BooleanVar(value=bool(_nina.get("seq_cool_camera", True)))
        self.nina_seq_cool_temp_var = tk.StringVar(value=str(_nina.get("seq_cool_target_c", -5.0)))
        self.nina_seq_park_var = tk.BooleanVar(value=bool(_nina.get("seq_park_at_end", True)))
        self.nina_seq_connect_var = tk.BooleanVar(value=bool(_nina.get("seq_connect_at_start", True)))
        self.nina_seq_guider_var = tk.BooleanVar(value=bool(_nina.get("seq_start_guider", False)))
        self.nina_seq_af_var = tk.BooleanVar(value=bool(_nina.get("seq_auto_focus", False)))
        self.nina_seq_progress_var = tk.StringVar(value="")
        self._nina_busy = False
        self._nina_abort_event = threading.Event()

        self._build_ui()

    def set_night_observation_tab(self, tab: Optional["NightObservationTab"]) -> None:
        self._night_tab = tab

    def _build_ui(self) -> None:
        add_manual_help_header(self, "14-controle-nina")

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text=(
                "NINA doit être lancé sur le PC télescope (API avancée, port 1888). "
                "Slew et séquence utilisent les cibles cochées (☑) dans l'onglet "
                "« Observation de la Nuit »."
            ),
            wraplength=720,
        ).pack(anchor="w", pady=(0, 8))

        nina_frame = ttk.LabelFrame(
            outer,
            text="Connexion NINA (HTTP)",
            padding=8,
        )
        nina_frame.pack(fill=tk.BOTH, expand=True)

        conn_row = ttk.Frame(nina_frame)
        conn_row.pack(fill=tk.X, pady=2)
        ttk.Label(conn_row, text="Hôte:").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(conn_row, textvariable=self.nina_host_var, width=20).pack(side=tk.LEFT, padx=2)
        ttk.Label(conn_row, text="Port:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(conn_row, textvariable=self.nina_port_var, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(conn_row, text="Protocole:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Combobox(
            conn_row,
            textvariable=self.nina_protocol_var,
            values=("http", "https"),
            width=7,
            state="readonly",
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(conn_row, text="💾", width=3, command=self._nina_save_config).pack(
            side=tk.LEFT, padx=(6, 2)
        )
        ttk.Button(conn_row, text="Tester connexion", command=self._nina_test_connection).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(conn_row, text="Connecter tout", command=self._nina_connect_all).pack(
            side=tk.LEFT, padx=2
        )

        self.nina_status_label = ttk.Label(nina_frame, text="Non testé", foreground="gray")
        self.nina_status_label.pack(anchor="w", pady=(0, 4))

        act_row = ttk.Frame(nina_frame)
        act_row.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(
            act_row,
            text="Slew + centrage (plate-solve NINA)",
            variable=self.nina_slew_center_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            act_row,
            text="🎯 Slew vers cible cochée (1 seule)",
            command=self._nina_slew_selected,
        ).pack(side=tk.LEFT, padx=4)

        cap_row = ttk.Frame(nina_frame)
        cap_row.pack(fill=tk.X, pady=2)
        ttk.Label(cap_row, text="Capture test — durée (s):").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(cap_row, textvariable=self.nina_capture_duration_var, width=6).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Label(cap_row, text="Gain:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(cap_row, textvariable=self.nina_capture_gain_var, width=6).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(cap_row, text="📷 Capture test", command=self._nina_capture_test).pack(
            side=tk.LEFT, padx=8
        )

        seq_lf = ttk.LabelFrame(
            nina_frame,
            text="Séquence (cibles ☑ dans Observation de la Nuit, ordre du tableau)",
            padding=6,
        )
        seq_lf.pack(fill=tk.X, pady=(6, 2))

        filt_row = ttk.Frame(seq_lf)
        filt_row.pack(fill=tk.X, pady=2)
        ttk.Label(filt_row, text="Filtres NINA (virgules, vide = filtre actuel) :").pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Entry(filt_row, textvariable=self.nina_seq_filters_var, width=32).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=2
        )
        ttk.Label(filt_row, text="Images/filtre :").pack(side=tk.LEFT, padx=(6, 4))
        ttk.Entry(filt_row, textvariable=self.nina_seq_frames_var, width=4).pack(side=tk.LEFT)

        opt_row = ttk.Frame(seq_lf)
        opt_row.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(opt_row, text="Refroidir", variable=self.nina_seq_cool_var).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Label(opt_row, text="°C :").pack(side=tk.LEFT)
        ttk.Entry(opt_row, textvariable=self.nina_seq_cool_temp_var, width=5).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Checkbutton(
            opt_row, text="Connecter au début", variable=self.nina_seq_connect_var
        ).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(opt_row, text="Guidage", variable=self.nina_seq_guider_var).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Checkbutton(opt_row, text="AF / cible", variable=self.nina_seq_af_var).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Checkbutton(opt_row, text="Park fin", variable=self.nina_seq_park_var).pack(
            side=tk.LEFT, padx=4
        )

        run_row = ttk.Frame(seq_lf)
        run_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(run_row, text="▶ Lancer séquence", command=self._nina_run_sequence).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(run_row, text="■ Arrêter", command=self._nina_stop_sequence).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(run_row, text="Lister filtres NINA", command=self._nina_list_filters).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(run_row, textvariable=self.nina_seq_progress_var, foreground="blue").pack(
            side=tk.LEFT, padx=8
        )

        log_frame = ttk.LabelFrame(outer, text="Journal", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.nina_log_text = scrolledtext.ScrolledText(
            log_frame, height=14, wrap=tk.WORD, state="disabled"
        )
        self.nina_log_text.pack(fill=tk.BOTH, expand=True)

    def _require_night_tab(self) -> "NightObservationTab":
        if self._night_tab is None:
            raise RuntimeError(
                "L'onglet « Observation de la Nuit » n'est pas disponible."
            )
        return self._night_tab

    def _nina_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"

        def _append() -> None:
            self.nina_log_text.configure(state="normal")
            self.nina_log_text.insert(tk.END, line)
            self.nina_log_text.see(tk.END)
            self.nina_log_text.configure(state="disabled")

        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            self.after(0, _append)

    def _nina_parse_connection_config(self) -> NinaConnectionConfig:
        host = self.nina_host_var.get().strip()
        try:
            port = int(self.nina_port_var.get().strip())
        except ValueError as exc:
            raise ValueError("Port NINA invalide") from exc
        protocol = (self.nina_protocol_var.get() or "http").strip().lower()
        return NinaConnectionConfig(host=host, port=port, protocol=protocol)

    def _nina_build_client(self) -> NinaClient:
        return NinaClient(self._nina_parse_connection_config())

    def _nina_save_config(self) -> None:
        try:
            cfg = self._nina_parse_connection_config()
            dur = float(self.nina_capture_duration_var.get().strip().replace(",", "."))
            gain = float(self.nina_capture_gain_var.get().strip().replace(",", "."))
            frames = int(self.nina_seq_frames_var.get().strip())
            cool_t = float(self.nina_seq_cool_temp_var.get().strip().replace(",", "."))
            persist_nina_config(
                host=cfg.host,
                port=cfg.port,
                protocol=cfg.protocol,
                capture_duration_s=dur,
                capture_gain=gain,
                slew_center=self.nina_slew_center_var.get(),
                seq_filters=self.nina_seq_filters_var.get().strip(),
                seq_frames_per_filter=frames,
                seq_cool_camera=self.nina_seq_cool_var.get(),
                seq_cool_target_c=cool_t,
                seq_park_at_end=self.nina_seq_park_var.get(),
                seq_connect_at_start=self.nina_seq_connect_var.get(),
                seq_start_guider=self.nina_seq_guider_var.get(),
                seq_auto_focus=self.nina_seq_af_var.get(),
            )
            self._nina_log(f"Paramètres NINA enregistrés ({cfg.base_url})")
            messagebox.showinfo("NINA", "Configuration enregistrée dans config.json.", parent=self)
        except Exception as e:
            messagebox.showerror("NINA", str(e), parent=self)

    def _nina_set_busy(self, busy: bool) -> None:
        self._nina_busy = busy

    def _nina_run_async(self, label: str, worker) -> None:
        if self._nina_busy:
            messagebox.showwarning("NINA", "Une opération NINA est déjà en cours.", parent=self)
            return

        def _task() -> None:
            self._nina_set_busy(True)
            self._nina_log(f"▶ {label}…")
            try:
                worker()
            except Exception as e:
                logger.exception("NINA %s", label)
                self.after(0, lambda e=e: self._nina_on_error(label, str(e)))
            finally:
                self._nina_set_busy(False)

        Thread(target=_task, daemon=True).start()

    def _nina_on_error(self, label: str, err: str) -> None:
        self._nina_log(f"✗ {label} : {err}")
        self.nina_status_label.config(text=f"Erreur : {err[:80]}", foreground="red")
        messagebox.showerror("NINA", f"{label}\n\n{err}", parent=self)

    def _nina_on_success(self, message: str) -> None:
        self._nina_log(f"✓ {message}")
        self.nina_status_label.config(text=message[:120], foreground="green")

    def _nina_test_connection(self) -> None:
        def work() -> None:
            client = self._nina_build_client()
            test = client.test_connection()

            def ui() -> None:
                self._nina_log(test.message)
                if test.success:
                    self.nina_status_label.config(text=test.message, foreground="green")
                else:
                    self.nina_status_label.config(text=test.message, foreground="red")
                    messagebox.showwarning("NINA", test.message, parent=self)

            self.after(0, ui)

        self._nina_run_async("Test connexion", work)

    def _nina_connect_all(self) -> None:
        def work() -> None:
            client = self._nina_build_client()
            results = client.connect_all()
            lines = []
            for device, res in results:
                ok = "OK" if res.ok and not res.error else "échec"
                lines.append(f"{device}: {ok}")
            msg = "Connexion — " + ", ".join(lines)
            test = client.test_connection()

            def ui() -> None:
                self._nina_log(msg)
                self._nina_on_success(test.message if test.success else msg)

            self.after(0, ui)

        self._nina_run_async("Connexion périphériques", work)

    def _nina_resolve_slew_target(self) -> Tuple[str, float, float]:
        night = self._require_night_tab()
        selected = night._get_selected_objects()
        if len(selected) == 1:
            obj = selected[0]
            return obj.name, float(obj.ra), float(obj.dec)
        if len(selected) > 1:
            raise ValueError(
                "Cochez une seule cible dans « Observation de la Nuit » pour le slew."
            )
        manual = night._parse_manual_icrs_deg_for_export()
        if manual is not None:
            ra_deg, dec_deg = manual
            return "ICRS saisi", ra_deg, dec_deg
        raise ValueError(
            "Cochez une cible dans « Observation de la Nuit », "
            "ou renseignez les coordonnées ICRS manuelles (graphique d'altitude)."
        )

    def _nina_slew_selected(self) -> None:
        def work() -> None:
            name, ra_deg, dec_deg = self._nina_resolve_slew_target()
            center = self.nina_slew_center_var.get()
            client = self._nina_build_client()
            client.slew_to_target(name, ra_deg, dec_deg, center=center)
            msg = f"Slew terminé — {name} (RA {ra_deg:.4f}°, Dec {dec_deg:+.4f}°)"
            if center:
                msg += " [avec centrage]"

            def ui() -> None:
                self._nina_on_success(msg)

            self.after(0, ui)

        self._nina_run_async("Slew", work)

    def _nina_capture_test(self) -> None:
        def work() -> None:
            dur = float(self.nina_capture_duration_var.get().strip().replace(",", "."))
            gain = float(self.nina_capture_gain_var.get().strip().replace(",", "."))
            target_name = ""
            try:
                name, _, _ = self._nina_resolve_slew_target()
                target_name = name
            except ValueError:
                pass
            client = self._nina_build_client()
            _, equipment = client.get_equipment_info()
            if gain <= 0 and equipment:
                cam = equipment.get("Camera") or {}
                try:
                    default_g = float(cam.get("DefaultGain", cam.get("Gain", gain)))
                    if default_g > 0:
                        gain = default_g
                        self._nina_log(f"Gain 0 → gain caméra NINA {gain:g}")
                except (TypeError, ValueError):
                    pass
            filt = client.prepare_filter_for_light_capture(preferred="G", equipment=equipment)
            if filt:
                self._nina_log(f"Filtre pour capture : {filt}")
            self._nina_log(f"Exposition {dur}s, gain {gain:g}…")
            client.capture_checked(
                dur,
                gain,
                target_name=target_name,
                filter_name=filt,
                wait_complete=True,
            )
            msg = f"Capture terminée — {dur}s @ gain {gain:g}"
            if filt:
                msg += f", filtre {filt}"
            if target_name:
                msg += f" ({target_name})"

            def ui() -> None:
                self._nina_on_success(msg)

            self.after(0, ui)

        self._nina_run_async("Capture test", work)

    def _get_selected_objects_ordered(self) -> List["EphemerisObject"]:
        night = self._require_night_tab()
        ordered: List[EphemerisObject] = []
        for item in night.results_tree.get_children():
            values = night.results_tree.item(item, "values")
            if len(values) < 2:
                continue
            obj_name = night._object_name_from_display_name(values[1])
            if not night.selected_objects.get(obj_name):
                continue
            obj = night._find_object_by_name(obj_name)
            if obj is not None:
                ordered.append(obj)
        return ordered

    def _nina_build_sequence_plan(self, targets: List["EphemerisObject"]) -> NinaSequencePlan:
        dur = float(self.nina_capture_duration_var.get().strip().replace(",", "."))
        gain = float(self.nina_capture_gain_var.get().strip().replace(",", "."))
        frames = int(self.nina_seq_frames_var.get().strip())
        cool_t = float(self.nina_seq_cool_temp_var.get().strip().replace(",", "."))
        filter_names = parse_filter_names_csv(self.nina_seq_filters_var.get())
        filter_steps = build_filter_steps(filter_names, frames)
        seq_targets = [
            NinaSequenceTarget(name=obj.name, ra_deg=float(obj.ra), dec_deg=float(obj.dec))
            for obj in targets
        ]
        return NinaSequencePlan(
            targets=seq_targets,
            filter_steps=filter_steps,
            duration_s=dur,
            gain=gain,
            center_slew=self.nina_slew_center_var.get(),
            cool_camera=self.nina_seq_cool_var.get(),
            cool_target_c=cool_t,
            park_at_end=self.nina_seq_park_var.get(),
            connect_at_start=self.nina_seq_connect_var.get(),
            start_guider=self.nina_seq_guider_var.get(),
            auto_focus_per_target=self.nina_seq_af_var.get(),
        )

    def _nina_stop_sequence(self) -> None:
        if self._nina_busy:
            self._nina_abort_event.set()
            self._nina_log("Arrêt demandé…")
            self.nina_seq_progress_var.set("Arrêt en cours…")
        else:
            messagebox.showinfo("NINA", "Aucune séquence en cours.", parent=self)

    def _nina_list_filters(self) -> None:
        def work() -> None:
            client = self._nina_build_client()
            _, equipment = client.get_equipment_info()
            filters = client.list_filters(equipment)
            if not filters:
                msg = "Aucun filtre listé (roue non connectée ou API sans AvailableFilters)."
            else:
                msg = "Filtres NINA : " + ", ".join(
                    f"{f.name} (id {f.filter_id})" for f in filters
                )

            def ui() -> None:
                self._nina_log(msg)
                self.nina_status_label.config(text=msg[:120], foreground="blue")

            self.after(0, ui)

        self._nina_run_async("Liste filtres", work)

    def _nina_run_sequence(self) -> None:
        try:
            targets = self._get_selected_objects_ordered()
        except RuntimeError as e:
            messagebox.showerror("Séquence NINA", str(e), parent=self)
            return
        if not targets:
            messagebox.showwarning(
                "Séquence NINA",
                "Cochez au moins une cible dans l'onglet « Observation de la Nuit » (☑).",
                parent=self,
            )
            return
        if self._nina_busy:
            messagebox.showwarning("NINA", "Une opération NINA est déjà en cours.", parent=self)
            return

        try:
            plan = self._nina_build_sequence_plan(targets)
        except Exception as e:
            messagebox.showerror("Séquence NINA", str(e), parent=self)
            return

        n_targets = len(targets)
        n_frames = sum(s.frame_count for s in plan.filter_steps) * n_targets
        if not messagebox.askyesno(
            "Confirmer la séquence",
            f"Lancer la séquence sur {n_targets} cible(s) ?\n"
            f"Environ {n_frames} exposition(s) de {plan.duration_s}s "
            f"(gain {plan.gain}).\n\n"
            "NINA doit être prêt ; l'arrêt demande ■ Arrêter.",
            parent=self,
        ):
            return

        self._nina_abort_event.clear()
        self.nina_seq_progress_var.set("Séquence…")

        def work() -> None:
            self._nina_set_busy(True)
            self._nina_log(
                f"▶ Séquence : {n_targets} cible(s), "
                f"{sum(s.frame_count for s in plan.filter_steps)} img/cible"
            )
            try:
                client = self._nina_build_client()
                runner = NinaSequenceRunner(
                    client,
                    plan,
                    log=self._nina_log,
                    should_abort=lambda: self._nina_abort_event.is_set(),
                    on_progress=lambda text: self.after(
                        0, lambda t=text: self.nina_seq_progress_var.set(t)
                    ),
                )
                result = runner.run()

                def ui_ok() -> None:
                    msg = (
                        f"Séquence OK — {result.targets_done} cible(s), "
                        f"{result.frames_taken} image(s)"
                    )
                    self._nina_on_success(msg)
                    messagebox.showinfo("Séquence NINA", msg, parent=self)

                def ui_abort() -> None:
                    msg = (
                        f"Séquence interrompue — {result.targets_done} cible(s), "
                        f"{result.frames_taken} image(s) avant arrêt"
                    )
                    self._nina_log(f"■ {msg}")
                    self.nina_status_label.config(text=msg, foreground="orange")
                    self.nina_seq_progress_var.set("Interrompu")
                    messagebox.showinfo("Séquence NINA", msg, parent=self)

                if result.aborted:
                    self.after(0, ui_abort)
                else:
                    self.after(0, ui_ok)
            except NinaSequenceAborted:
                self.after(0, lambda: self.nina_seq_progress_var.set("Interrompu"))
            except Exception as e:
                logger.exception("Séquence NINA")
                self.after(0, lambda e=e: self._nina_on_error("Séquence", str(e)))
            finally:
                self._nina_set_busy(False)

        Thread(target=work, daemon=True).start()
