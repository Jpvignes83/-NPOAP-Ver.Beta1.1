# gui/main_window.py

import tkinter as tk
from tkinter import ttk


def _tab_enabled(key: str, default: bool = True) -> bool:
    """Lit config/tabs_config.py (build autonome partiel / complet)."""
    try:
        from config.tabs_config import ENABLED_TABS

        return bool(ENABLED_TABS.get(key, default))
    except Exception:
        return default


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("NPOAP")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self._configure_window_for_screen(screen_w, screen_h)

        self._configure_notebook_style_for_screen(screen_w, screen_h)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        from gui.home_tab import HomeTab

        self.home_tab = HomeTab(self.notebook)
        self.notebook.add(self.home_tab, text="🏠 Accueil")

        self.night_observation_tab = None
        if _tab_enabled("ephemerides"):
            try:
                from gui.night_observation_tab import NightObservationTab

                self.night_observation_tab = NightObservationTab(self.notebook)
                self.notebook.add(self.night_observation_tab, text="🌙 Observation de la Nuit")
            except ImportError as e:
                print(f"Warning: NightObservationTab non disponible: {e}")

        self.nina_control_tab = None
        if _tab_enabled("nina_control") and self.night_observation_tab is not None:
            try:
                from gui.nina_control_tab import NinaControlTab

                self.nina_control_tab = NinaControlTab(self.notebook, self.night_observation_tab)
                self.notebook.add(self.nina_control_tab, text="🔭 Contrôle NINA")
            except ImportError as e:
                print(f"Warning: NinaControlTab non disponible: {e}")

        self.data_reduction_tab = None
        if _tab_enabled("data_reduction"):
            from gui.data_reduction_tab import CCDProcGUI

            self.data_reduction_tab = CCDProcGUI(self.notebook)
            self.notebook.add(self.data_reduction_tab.frame, text="🛠️ Réduction de Données")

        self.photometry_exoplanets_tab = None
        self.data_analysis_tab = None
        if _tab_enabled("photometry_exoplanets") or _tab_enabled("data_analysis"):
            from gui.photometry_exoplanets_tab import PhotometryExoplanetsTab

            self.photometry_exoplanets_tab = PhotometryExoplanetsTab(self.notebook, base_dir=None)
            self.data_analysis_tab = getattr(
                self.photometry_exoplanets_tab, "data_analysis_tab", None
            )
            self.notebook.add(self.photometry_exoplanets_tab, text="🔭 Photométrie Exoplanètes")

        self.asteroid_photometry_tab = None
        if _tab_enabled("asteroid_photometry"):
            from gui.asteroid_photometry_tab import AsteroidPhotometryTab

            self.asteroid_photometry_tab = AsteroidPhotometryTab(self.notebook)
            self.notebook.add(self.asteroid_photometry_tab.frame, text="🛰️ Photométrie Astéroïdes")

        self.occultations_tab = None
        if _tab_enabled("occultations"):
            from gui.occultations_tab import OccultationsTab

            self.occultations_tab = OccultationsTab(
                self.notebook,
                night_observation_tab=self.night_observation_tab,
            )
            self.notebook.add(self.occultations_tab, text="🌑 Occultation")

        self.transient_photometry_tab = None
        if _tab_enabled("transient_photometry"):
            from gui.transient_photometry_tab import TransientPhotometryTab

            self.transient_photometry_tab = TransientPhotometryTab(self.notebook)
            self.notebook.add(self.transient_photometry_tab, text="💥 Photométrie Transitoires")

        stars_any = any(
            _tab_enabled(k)
            for k in ("binary_stars", "easy_lucky_imaging", "variable_stars")
        )
        self.stars_container = None
        self.stars_notebook = None
        self.binary_stars_tab = None
        self.easy_lucky_imaging_tab = None
        self.variable_stars_tab = None
        if stars_any:
            self.stars_container = ttk.Frame(self.notebook)
            self.stars_notebook = ttk.Notebook(self.stars_container)
            self.stars_notebook.pack(fill=tk.BOTH, expand=True)

            if _tab_enabled("binary_stars"):
                from gui.binary_stars_tab import BinaryStarsTab

                self.binary_stars_tab = BinaryStarsTab(self.stars_notebook)
                self.stars_notebook.add(self.binary_stars_tab, text="⭐ Étoiles Binaires")

            if _tab_enabled("easy_lucky_imaging"):
                try:
                    from gui.easy_lucky_imaging_tab import EasyLuckyImagingTab

                    self.easy_lucky_imaging_tab = EasyLuckyImagingTab(self.stars_notebook)
                    self.stars_notebook.add(self.easy_lucky_imaging_tab, text="✨ Easy Lucky Imaging")
                except ImportError as e:
                    print(f"Warning: EasyLuckyImagingTab non disponible: {e}")

            if _tab_enabled("variable_stars"):
                try:
                    from gui.variable_stars_tab import VariableStarsTab

                    self.variable_stars_tab = VariableStarsTab(self.stars_notebook)
                    self.stars_notebook.add(self.variable_stars_tab, text="🌟 Étoiles Variables")
                except ImportError as e:
                    print(f"Warning: VariableStarsTab non disponible: {e}")

            if self.stars_notebook.index("end") > 0:
                self.notebook.add(self.stars_container, text="⭐ Etoiles")

        self.cluster_analysis_tab = None
        if _tab_enabled("cluster_analysis"):
            from gui.cluster_analysis_tab import ClusterAnalysisTab

            self.cluster_analysis_tab = ClusterAnalysisTab(self.notebook)
            self.notebook.add(self.cluster_analysis_tab, text="📊 Analyse d'amas")

        self.spectroscopy_tab = None
        if _tab_enabled("spectroscopy"):
            from gui.spectroscopy_tab import SpectroscopyTab

            self.spectroscopy_tab = SpectroscopyTab(self.notebook)
            self.notebook.add(self.spectroscopy_tab, text="🔬 Spectroscopie")

        self.catalogues_tab = None
        if _tab_enabled("catalogues"):
            try:
                from gui.catalogues_tab import CataloguesTab

                self.catalogues_tab = CataloguesTab(self.notebook)
                self.notebook.add(self.catalogues_tab, text="📚 Catalogues")
            except ImportError as e:
                print(f"Warning: CataloguesTab non disponible: {e}")

        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

    def _configure_window_for_screen(self, screen_w: int, screen_h: int) -> None:
        is_small_screen = screen_w <= 1366 or screen_h <= 768
        if is_small_screen:
            try:
                self.root.state("zoomed")
            except tk.TclError:
                self.root.geometry(f"{screen_w}x{screen_h}+0+0")
        else:
            target_w = min(1920, max(1280, int(screen_w * 0.96)))
            target_h = min(1200, max(800, int(screen_h * 0.92)))
            pos_x = max(0, (screen_w - target_w) // 2)
            pos_y = max(0, (screen_h - target_h) // 2)
            self.root.geometry(f"{target_w}x{target_h}+{pos_x}+{pos_y}")

        min_w = min(1280, max(960, int(screen_w * 0.70)))
        min_h = min(900, max(640, int(screen_h * 0.70)))
        self.root.minsize(min_w, min_h)

    def _configure_notebook_style_for_screen(self, screen_w: int, screen_h: int) -> None:
        if screen_w <= 1366 or screen_h <= 768:
            tab_font = ("Arial", 7, "bold")
            tab_padding = (6, 8)
        elif screen_w <= 1600 or screen_h <= 900:
            tab_font = ("Arial", 8, "bold")
            tab_padding = (8, 10)
        else:
            tab_font = ("Arial", 9, "bold")
            tab_padding = (10, 12)

        style = ttk.Style()
        style.configure("TNotebook.Tab", font=tab_font, padding=tab_padding)

    def on_quit(self):
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
