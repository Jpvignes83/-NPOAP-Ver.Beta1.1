"""Historique SHOBS-FLUX (SQLite) et rapport système PDF pour NPOAP."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.shobs_flux_runtime import import_shobs

WRITTEN_BY = "NPOAP (SHOBS-FLUX 1.0.1)"


def history_db_path() -> Path:
    history = import_shobs("history")
    return Path(history.db_path())


def list_setups() -> list[dict]:
    history = import_shobs("history")
    return history.setups()


def list_recent_runs(limit: int = 80, kind: str | None = None) -> list[dict]:
    history = import_shobs("history")
    return history.recent_runs(limit=limit, kind=kind)


def available_values(kind: str, setup_id: str) -> list[tuple]:
    history = import_shobs("history")
    return history.available(kind, setup_id)


def series_points(
    kind: str,
    setup_id: str,
    key: str | None = None,
    channel: str | None = "*",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    history = import_shobs("history")
    return history.series_points(
        kind, setup_id, key=key, channel=channel, date_from=date_from, date_to=date_to
    )


def set_run_removed(run_key: str, removed: bool = True) -> bool:
    history = import_shobs("history")
    return history.set_removed(run_key, removed)


def export_series_csv(path: str | Path, points: list[dict], setup_words: str = "") -> Path:
    history = import_shobs("history")
    settings = import_shobs("settings")
    out = Path(path)
    history.write_csv(str(out), points, setup_words or "setup", settings.APP_VERSION)
    return out


def draw_trend_figure(fig, points: list[dict], words: str, unit: str, event: str = "") -> None:
    trend_plots = import_shobs("trend_plots")
    trend_plots.draw_trend(fig, points, words, unit, event=event or None)


def stamp_trend_figure(fig) -> None:
    trend_plots = import_shobs("trend_plots")
    settings = import_shobs("settings")
    trend_plots.stamp(fig, settings.APP_VERSION, "NPOAP")


def list_system_profile_paths() -> list[tuple[str, str]]:
    """[(profile_id, path), …] pour le rapport PDF."""
    sp = import_shobs("shobs_profile")
    out = []
    for path in sp.list_profiles("systems"):
        try:
            doc = sp.load(path)
            out.append((str(doc.get("profile_id") or Path(path).stem), path))
        except Exception:
            continue
    return out


def write_system_report_pdf(
    system_path: str | Path,
    dest: str | Path,
    *,
    share: bool = False,
    event: str = "",
    date_from: str = "",
    date_to: str = "",
) -> tuple[Path, int]:
    """Génère le rapport PDF système SHOBS. Retourne (chemin, n_pages)."""
    report = import_shobs("report")
    settings = import_shobs("settings")
    from config import EQUIPMENT_OBSERVATION, OBSERVATORY

    prefs = {
        "site_entries": [
            {
                "camera": "",
                "focal": None,
                "lat": OBSERVATORY.get("latitude", OBSERVATORY.get("lat")),
                "lon": OBSERVATORY.get("longitude", OBSERVATORY.get("lon")),
                "elevation": OBSERVATORY.get("elevation", OBSERVATORY.get("elev")),
                "name": OBSERVATORY.get("name"),
            }
        ],
        "sky_telescope_aperture": EQUIPMENT_OBSERVATION.get("telescope_diameter_mm"),
    }
    info = report.gather(
        str(system_path),
        prefs=prefs,
        event=event or "",
        optics_override={
            "aperture_mm": EQUIPMENT_OBSERVATION.get("telescope_diameter_mm"),
        },
        date_from=date_from or "",
        date_to=date_to or "",
    )
    # compléter ouverture si manquante dans le profil
    tel = info.get("telescope") or {}
    if not tel.get("aperture_mm") and EQUIPMENT_OBSERVATION.get("telescope_diameter_mm"):
        tel["aperture_mm"] = float(EQUIPMENT_OBSERVATION["telescope_diameter_mm"])
        info["telescope"] = tel

    dest_p = Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    n = report.write_pdf(info, str(dest_p), share=share, version=f"{settings.APP_VERSION} / NPOAP")
    return dest_p, int(n)


def default_report_name(system_path: str | Path, share: bool = False) -> str:
    report = import_shobs("report")
    try:
        info = report.gather(str(system_path))
        return report.default_name(info, share)
    except Exception:
        return f"shobs_system_report{'_shared' if share else ''}.pdf"


def history_status_text() -> str:
    history = import_shobs("history")
    runs = history.recent_runs(limit=1)
    setups = history.setups()
    db = history.db_path()
    n_setup = len(setups)
    if not runs:
        return f"Historique vide · {db}"
    return f"{n_setup} setup(s) · dernier run {runs[0].get('kind')} {str(runs[0].get('started') or '')[:19]} · {db}"
