import logging
import os
from logging import FileHandler, Formatter
from tkinter import Text
from pathlib import Path

class TextHandler(logging.Handler):
    def __init__(self, text_widget: Text):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", msg + "\n")
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")
        self.text_widget.after(0, append)


class _SafeStreamHandler(logging.StreamHandler):
    """
    StreamHandler tolérant aux interactions ``colorama ↔ threads`` sous Windows.

    En particulier, ``colorama.AnsiToWin32`` peut lever
    ``ValueError: I/O operation on closed file.`` quand un logger émet depuis un
    thread worker alors que le flux wrappé est transitoirement fermé (ex.
    ``lightkurve.utils.create_quality_mask`` qui logge depuis ``download``).
    Ces tracebacks sont du bruit : le travail métier est terminé.
    """

    def emit(self, record):
        try:
            super().emit(record)
        except (ValueError, OSError) as exc:
            # On veut filtrer uniquement les flux fermés et les pipes cassés,
            # pas les vraies erreurs de formatage.
            msg = str(exc).lower()
            if (
                "closed file" in msg
                or "broken pipe" in msg
                or "bad file descriptor" in msg
            ):
                return
            raise

def setup_logging(log_dir: str | Path = "logs", level=logging.INFO):
    """Journal fichier uniquement ; appelez ``attach_console_logging()`` après les imports lourds."""
    log_dir = Path(log_dir)
    if not log_dir.is_absolute():
        base_dir = Path(__file__).resolve().parent.parent
        log_dir = base_dir / log_dir
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"npoap_{os.getpid()}.log"

    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    detailed = Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    file_handler = FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(detailed)

    root.setLevel(level)
    root.addHandler(file_handler)

    logging.info(f"Logging initialisé → {log_file}")


def attach_console_logging(level=logging.INFO):
    """
    Ajoute la sortie console (stderr), même format que le fichier logs/npoap_*.log.
    À appeler après l'import de ``gui.main_window`` pour éviter d'afficher les milliers
    de lignes print/logging des dépendances (exoclock, Gaia, Prospector, etc.).
    """
    root = logging.getLogger()
    # FileHandler (et RotatingFileHandler, etc.) sont des sous-classes de StreamHandler :
    # sans ce filtre, on croyait à tort que la console était déjà branchée.
    if any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, FileHandler)
        for h in root.handlers
    ):
        return

    detailed = Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    console_handler = _SafeStreamHandler()
    console_handler.setFormatter(detailed)
    console_handler.setLevel(level)
    root.addHandler(console_handler)