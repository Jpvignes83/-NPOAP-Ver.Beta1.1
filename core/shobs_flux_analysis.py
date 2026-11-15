"""Wrappers scientifiques SHOBS-FLUX pour NPOAP (bench, darks, check, sky / on-sky).

Utilise le code GPL-3 vendu dans ``external_apps/shobs_flux/`` sans l'UI ``flux_app``.
Les résultats peuvent être poussés vers ``config.json`` et/ou ``~/.shobs/``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.shobs_flux_bridge import (
    CameraProfileSummary,
    apply_camera_profile_to_npoap,
    equipment_from_summary,
    summarize_camera_doc,
)
from core.shobs_flux_runtime import import_shobs

StepFn = Callable[[str], None] | None
WRITTEN_BY = "NPOAP (SHOBS-FLUX 1.0.1)"


def _step(step: StepFn, text: str) -> None:
    if step is not None:
        step(text)


def _record_history(
    kind: str,
    source: str,
    summary: dict,
    *,
    camera_id: str | None = None,
    system_id: str | None = None,
    n_frames: int | None = None,
    status: str = "ok",
    values: list | None = None,
    run_key: str | None = None,
) -> str | None:
    """Enregistre un run dans ``~/.shobs/flux_runs.sqlite`` (jamais d'exception)."""
    try:
        history = import_shobs("history")
        settings = import_shobs("settings")
        return history.record_run(
            kind,
            source,
            summary or {},
            camera_id=camera_id,
            system_id=system_id,
            n_frames=n_frames,
            status=status or "ok",
            app=WRITTEN_BY or settings.WRITTEN_BY,
            values=values or [],
            run_key=run_key,
        )
    except Exception:
        return None


def _finite(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


@dataclass
class BenchAnalysisResult:
    raw: Any
    findings: list[tuple[str, str]] = field(default_factory=list)
    equipment: dict[str, Any] = field(default_factory=dict)
    profile_path: str | None = None
    status: str = "ok"
    run_key: str | None = None

    @property
    def gain_e_per_adu(self) -> float | None:
        return _finite(getattr(self.raw, "gain", None))

    @property
    def read_noise_e(self) -> float | None:
        return _finite(getattr(self.raw, "read_noise_e", None))

    @property
    def linear_limit_adu(self) -> float | None:
        return _finite(getattr(self.raw, "linear_limit_adu", None))


@dataclass
class DarkAnalysisResult:
    raw: Any
    findings: list[tuple[str, str]] = field(default_factory=list)
    equipment: dict[str, Any] = field(default_factory=dict)
    profile_path: str | None = None
    status: str = "ok"
    run_key: str | None = None

    @property
    def dark_e_per_s(self) -> float | None:
        main = getattr(self.raw, "main", None)
        if main is None:
            return None
        return _finite(getattr(main, "rate", None))

    @property
    def read_noise_e(self) -> float | None:
        return _finite(getattr(self.raw, "read_noise_e", None))


@dataclass
class CheckAnalysisResult:
    raw: Any
    findings: list[tuple[str, str]] = field(default_factory=list)
    status: str = "ok"
    n_stars: int = 0
    run_key: str | None = None


def _equipment_from_bench(res) -> dict[str, Any]:
    eq: dict[str, Any] = {}
    g = _finite(res.gain)
    rn = _finite(res.read_noise_e)
    lin = _finite(res.linear_limit_adu)
    sat = _finite(res.saturation_adu)
    setup = getattr(res, "setup", None) or {}
    if g is not None and g > 0:
        eq["camera_gain_e_per_adu"] = g
    if rn is not None and rn >= 0:
        eq["camera_readnoise_e"] = rn
    if lin is not None and lin > 0:
        eq["camera_linear_limit_adu"] = lin
    if sat is not None and sat > 0:
        eq["camera_saturation_adu"] = sat
    instrume = setup.get("instrume")
    if instrume:
        eq["camera"] = str(instrume)
    binning = setup.get("binning")
    try:
        b = int(binning) if binning is not None else None
    except (TypeError, ValueError):
        b = None
    if b is not None and b >= 1:
        eq["binning"] = b
    cam_id = setup.get("camera_id")
    if cam_id:
        eq["shobs_camera_profile_id"] = str(cam_id)
    return eq


def _equipment_from_darks(res) -> dict[str, Any]:
    eq: dict[str, Any] = {}
    main = getattr(res, "main", None)
    if main is not None:
        dark = _finite(getattr(main, "rate", None))
        if dark is not None and dark >= 0:
            eq["camera_dark_e_per_s"] = dark
    rn = _finite(getattr(res, "read_noise_e", None))
    if rn is not None and rn >= 0:
        eq["camera_readnoise_e"] = rn
    setup = getattr(res, "setup", None) or {}
    instrume = setup.get("instrume")
    if instrume:
        eq["camera"] = str(instrume)
    cam_id = setup.get("camera_id")
    if cam_id:
        eq["shobs_camera_profile_id"] = str(cam_id)
    return eq


def run_bench_folder(
    flats_folder: str | Path,
    *,
    bias_folder: str | Path | None = None,
    region_name: str | None = None,
    step: StepFn = None,
    save_shobs_profile: bool = True,
    apply_npoap_config: bool = True,
) -> BenchAnalysisResult:
    """PTC + linéarité + RN via ``bench.run_bench`` sur un dossier de flats (paires)."""
    bench = import_shobs("bench")
    settings = import_shobs("settings")
    sp = import_shobs("shobs_profile")

    folder = str(Path(flats_folder))
    bias = str(Path(bias_folder)) if bias_folder else None
    region = region_name or bench.DEFAULT_REGION

    def _s(msg: str) -> None:
        _step(step, msg)

    _s("Scan du dossier flats…")
    res = bench.run_bench(folder, region_name=region, step=_s, bias_folder=bias)
    out = BenchAnalysisResult(
        raw=res,
        findings=list(getattr(res, "lines", []) or []),
        equipment=_equipment_from_bench(res),
        status=str(getattr(res, "status", "ok")),
    )

    profile_path = None
    if save_shobs_profile:
        _s("Écriture du profil caméra ~/.shobs…")
        try:
            cam_id = (res.setup or {}).get("camera_id") or ""
            existing = sp.find_camera_profile(cam_id) if cam_id else None
            doc = bench.apply_to_profile(res, existing, written_by=WRITTEN_BY)
            profile_path = sp.save_profile(doc, written_by=WRITTEN_BY)
            out.profile_path = profile_path
            out.equipment["shobs_camera_profile_id"] = doc.get("profile_id")
            # Re-lire valeurs via le résumé bridge (sources incluses)
            summary = summarize_camera_doc(doc, Path(profile_path) if profile_path else None)
            out.equipment.update(
                {k: v for k, v in equipment_from_summary(summary).items() if v is not None}
            )
        except Exception as exc:
            settings.log(f"NPOAP save bench profile failed: {exc!r}")
            out.findings.append(("warn", f"Profil ~/.shobs non sauvegardé : {exc}"))

    if apply_npoap_config and out.equipment:
        _s("Mise à jour config.json NPOAP…")
        from config import persist_camera_equipment

        persist_camera_equipment(out.equipment)

    pid = out.equipment.get("shobs_camera_profile_id") or (res.setup or {}).get("camera_id")
    out.run_key = _record_history(
        "bench",
        folder,
        getattr(res, "summary", None) or bench.summary_of(res),
        camera_id=str(pid) if pid else None,
        n_frames=2 * (int(getattr(res, "n_flat_pairs", 0) or 0) + int(getattr(res, "n_bias_pairs", 0) or 0)),
        status=out.status,
        values=bench.run_values(res, str(pid or "unknown")),
    )
    return out


def run_darks_folder(
    darks_folder: str | Path,
    *,
    bias_folder: str | Path | None = None,
    region_name: str | None = None,
    step: StepFn = None,
    save_shobs_profile: bool = True,
    apply_npoap_config: bool = True,
) -> DarkAnalysisResult:
    """Courant d'obscurité via ``darks.run_darks``."""
    darks = import_shobs("darks")
    bench = import_shobs("bench")
    settings = import_shobs("settings")
    sp = import_shobs("shobs_profile")

    folder = str(Path(darks_folder))
    bias = str(Path(bias_folder)) if bias_folder else None
    region = region_name or bench.DEFAULT_REGION

    def _s(msg: str) -> None:
        _step(step, msg)

    _s("Scan des darks…")
    res = darks.run_darks(folder, region_name=region, step=_s, bias_folder=bias)
    out = DarkAnalysisResult(
        raw=res,
        findings=list(getattr(res, "lines", []) or []),
        equipment=_equipment_from_darks(res),
        status=str(getattr(res, "status", "ok")),
    )

    if save_shobs_profile:
        _s("Écriture du profil caméra ~/.shobs…")
        try:
            cam_id = (res.setup or {}).get("camera_id") or ""
            existing = sp.find_camera_profile(cam_id) if cam_id else None
            doc = darks.apply_to_profile(res, existing, written_by=WRITTEN_BY)
            path = sp.save_profile(doc, written_by=WRITTEN_BY)
            out.profile_path = path
            out.equipment["shobs_camera_profile_id"] = doc.get("profile_id")
            summary = summarize_camera_doc(doc, Path(path) if path else None)
            # Ne pas écraser gain/lin déjà mesurés au bench : fusionner dark (+ RN si présent)
            merged = equipment_from_summary(summary)
            for k in (
                "camera_dark_e_per_s",
                "camera_readnoise_e",
                "shobs_camera_profile_id",
                "camera",
            ):
                if merged.get(k) is not None:
                    out.equipment[k] = merged[k]
        except Exception as exc:
            settings.log(f"NPOAP save dark profile failed: {exc!r}")
            out.findings.append(("warn", f"Profil ~/.shobs non sauvegardé : {exc}"))

    if apply_npoap_config and out.equipment:
        _s("Mise à jour config.json NPOAP…")
        from config import persist_camera_equipment

        persist_camera_equipment(out.equipment)

    pid = out.equipment.get("shobs_camera_profile_id") or (res.setup or {}).get("camera_id")
    n = int(getattr(res, "n_bias", 0) or 0) + sum(
        int(getattr(tr, "n_darks", 0) or 0) for tr in (getattr(res, "temps", {}) or {}).values()
    )
    out.run_key = _record_history(
        "darks",
        folder,
        getattr(res, "summary", None) or darks.summary_of(res),
        camera_id=str(pid) if pid else None,
        n_frames=n,
        status=out.status,
        values=darks.run_values(res, str(pid or "unknown")),
    )
    return out


def check_one_image(path: str | Path, *, step: StepFn = None) -> CheckAnalysisResult:
    """Diagnostic d'une frame (ciel e⁻, sat/linéarité, étoiles)."""
    image_check = import_shobs("image_check")

    def _s(msg: str) -> None:
        _step(step, msg)

    _s("Analyse de l'image…")
    p = str(Path(path))
    res = image_check.check_image(p, step=_s)
    cam_id = None
    try:
        cam_id = getattr(getattr(res, "cam", None), "cam_id", None)
    except Exception:
        cam_id = None
    out = CheckAnalysisResult(
        raw=res,
        findings=list(getattr(res, "lines", []) or []),
        status=str(getattr(res, "status", "ok")),
        n_stars=len(getattr(res, "stars", []) or []),
    )
    out.run_key = _record_history(
        "check",
        p,
        getattr(res, "summary", None) or {},
        camera_id=str(cam_id) if cam_id else None,
        n_frames=1,
        status=out.status,
    )
    return out


def shooting_plan_from_flat(
    test_flat: str | Path,
    *,
    bias_adu: float | None = None,
    gain_setting=None,
    offset=None,
    temp=None,
) -> str:
    """Plan de tir (ladder) à partir d'un flat de test."""
    bench = import_shobs("bench")
    rates, bias, _exp = bench.rates_from_test_flat(str(Path(test_flat)), bias=bias_adu)
    plan = bench.plan_ladder(rates, bias)
    color = len(rates) > 1
    return bench.plan_text(
        plan, gain_setting=gain_setting, offset=offset, temp=temp, color=color
    )


def apply_profile_summary_to_npoap(summary: CameraProfileSummary) -> dict[str, Any]:
    """Raccourci : import profil déjà mesuré → config NPOAP."""
    return apply_camera_profile_to_npoap(summary)


def draw_bench_figure(fig, res) -> None:
    plots = import_shobs("bench_plots")
    plots.draw(fig, res)


def draw_darks_figure(fig, res) -> None:
    plots = import_shobs("dark_plots")
    plots.draw(fig, res)


# ---------------------------------------------------------------------------
# Phase 3 — Sky / on-sky (ZP, extinction, seeing, sky, scintillation)
# ---------------------------------------------------------------------------

FOCAL_TOL = 0.03


@dataclass
class SkyAnalysisResult:
    summary: Any
    findings: list[tuple[str, str]] = field(default_factory=list)
    onsky: dict[str, Any] = field(default_factory=dict)
    band_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    system_profile_path: str | None = None
    onsky_log_path: str | None = None
    n_nights: int = 0
    n_datasets: int = 0
    run_key: str | None = None


def _npoap_site() -> tuple[dict, float | None, float | None]:
    """Site NPOAP (lat/lon/elev) + ouverture / focale pour scintillation."""
    from config import EQUIPMENT_OBSERVATION, OBSERVATORY

    lat = OBSERVATORY.get("latitude", OBSERVATORY.get("lat"))
    lon = OBSERVATORY.get("longitude", OBSERVATORY.get("lon"))
    elev = OBSERVATORY.get("elevation", OBSERVATORY.get("elev"))
    site = {
        "lat": _finite(lat),
        "lon": _finite(lon),
        "elevation": _finite(elev),
    }
    aperture = _finite(EQUIPMENT_OBSERVATION.get("telescope_diameter_mm"))
    elev_m = _finite(elev)
    return site, aperture, elev_m


def _resolve_system_id(name: str, focal, cam: str) -> str:
    """Comme sky_page.resolve_system_id, sans importer l'UI Tk."""
    sp = import_shobs("shobs_profile")
    pid = sp.system_id(name, focal, cam)
    if Path(sp.profile_path("systems", pid, make=False)).is_file():
        return pid
    want = sp.slug(name)
    best = None
    for path in sp.list_profiles("systems"):
        try:
            doc = sp.load(path)
        except Exception:
            continue
        if doc.get("camera_profile") != cam or not doc.get("profile_id"):
            continue
        tel = doc.get("telescope") or {}
        if sp.slug(tel.get("name") or "") != want:
            continue
        f, g = sp._finite(tel.get("focal_mm")), sp._finite(focal)
        if not ((not f and not g) or (f and g and abs(f - g) <= FOCAL_TOL * max(f, g))):
            continue
        d = abs(f - g) if f is not None and g is not None else 0.0
        if best is None or d < best[0]:
            best = (d, doc["profile_id"])
    return best[1] if best else pid


def _onsky_from_summary(summary) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Extrait le bloc config ``onsky`` + détail par bande depuis un ``onsky.Summary``."""
    bands_out: dict[str, dict[str, Any]] = {}
    primary_band = None
    primary_score = -1
    for band, b in (getattr(summary, "bands", None) or {}).items():
        detail = {
            "zero_point": _finite(getattr(b, "zp1", None)),
            "extinction_k": _finite(getattr(b, "k", None)),
            "seeing_fwhm_arcsec": _finite(getattr(b, "fwhm_in_focus", None)),
            "sky_mag_arcsec2": _finite(getattr(b, "sky", None)),
            "scintillation_cy": _finite(getattr(b, "cy", None)),
        }
        bands_out[str(band)] = {k: v for k, v in detail.items() if v is not None}
        score = len(getattr(b, "zp_nights", []) or [])
        if detail["zero_point"] is not None and score >= primary_score:
            primary_band, primary_score = str(band), score

    if primary_band is None and bands_out:
        primary_band = next(iter(bands_out))

    onsky: dict[str, Any] = {"bands": bands_out, "band": primary_band}
    if primary_band and primary_band in bands_out:
        onsky.update(bands_out[primary_band])
    oh = _finite(getattr(summary, "overhead_s", None))
    if oh is not None:
        onsky["overhead_s"] = oh
    return onsky, bands_out


def _findings_from_summary(summary) -> list[tuple[str, str]]:
    lines = list(getattr(summary, "lines", []) or [])
    for night in getattr(summary, "nights", []) or []:
        for item in getattr(night, "lines", []) or []:
            lines.append(item)
    return lines


def _learn_and_save(
    datasets: list,
    *,
    telescope_name: str,
    aperture_mm: float | None,
    elevation_m: float | None,
    step: StepFn,
    save_system_profile: bool,
    apply_npoap_config: bool,
    folder_doc: dict | None = None,
) -> SkyAnalysisResult:
    onsky = import_shobs("onsky")
    sky_folder = import_shobs("sky_folder")
    settings = import_shobs("settings")
    sp = import_shobs("shobs_profile")

    if not datasets:
        raise onsky.OnSkyError("Aucun jeu de données on-sky utilisable.")

    def _dataset_focal(d) -> float | None:
        s = getattr(d, "setup", None) or {}
        return _finite(s.get("focal_header_mm") or s.get("focal_mm"))

    _step(step, "Profil système…")
    cam_id = datasets[0].camera_id
    focals = [f for f in (_dataset_focal(d) for d in datasets) if f is not None]
    focal = float(sorted(focals)[len(focals) // 2]) if focals else None
    name = (telescope_name or "").strip() or "Telescope"
    prof = sp.find_system_profile(cam_id, focal)

    _step(step, "Analyse des nuits…")
    summary = onsky.run_all(datasets, prof, aperture_mm, elevation_m, step)
    onsky_cfg, band_details = _onsky_from_summary(summary)
    findings = _findings_from_summary(summary)
    findings.extend(list(getattr(summary, "lines", []) or []))

    out = SkyAnalysisResult(
        summary=summary,
        findings=findings,
        onsky=onsky_cfg,
        band_details=band_details,
        n_nights=len(getattr(summary, "nights", []) or []),
        n_datasets=len(datasets),
    )

    log_path = None
    if folder_doc is not None and save_system_profile:
        try:
            _step(step, "Écriture log on-sky…")
            log_path = sky_folder.save_log(folder_doc)
            out.onsky_log_path = log_path
        except Exception as exc:
            settings.log(f"NPOAP save onsky log failed: {exc!r}")
            out.findings.append(("warn", f"Log on-sky non écrit : {exc}"))

    if save_system_profile:
        try:
            _step(step, "Écriture profil système ~/.shobs…")
            pid = _resolve_system_id(name, focal, cam_id)
            existing = None
            try:
                existing = sp.load(sp.profile_path("systems", pid, make=False))
            except Exception:
                existing = prof
            telescope = {
                "name": name,
                "aperture_mm": aperture_mm,
                "focal_mm": focal,
                "focal_header": focal,
            }
            setup = {"pixel_um": None}
            try:
                cam = sp.find_camera_profile(cam_id)
                if cam:
                    setup["pixel_um"] = ((cam.get("camera") or {}).get("pixel_um"))
            except Exception:
                pass
            doc = onsky.apply_to_profile(
                summary,
                existing,
                written_by=WRITTEN_BY,
                system_id=pid,
                cam_id=cam_id,
                telescope=telescope,
                setup=setup,
            )
            path = sp.save_profile(doc, written_by=WRITTEN_BY)
            out.system_profile_path = path
            out.onsky["shobs_system_profile_id"] = doc.get("profile_id")
        except Exception as exc:
            settings.log(f"NPOAP save system profile failed: {exc!r}")
            out.findings.append(("warn", f"Profil système non sauvegardé : {exc}"))

    if apply_npoap_config and out.onsky:
        _step(step, "Mise à jour config.json (onsky)…")
        from config import persist_onsky_calibration

        persist_onsky_calibration(out.onsky)

    # Historique : une entrée « sky » + une par nuit (log fichier)
    try:
        history = import_shobs("history")
        sid = out.onsky.get("shobs_system_profile_id")
        if not sid and out.system_profile_path:
            sid = Path(out.system_profile_path).stem
        cam = datasets[0].camera_id if datasets else None
        sky_summ = _sky_summary_dict(summary)
        values = _sky_values_rows(summary, str(sid or "unknown"))
        out.run_key = _record_history(
            "sky",
            out.onsky_log_path or "(sky-run)",
            sky_summ,
            camera_id=cam,
            system_id=str(sid) if sid else None,
            n_frames=sum(int(getattr(r, "n_frames", 0) or 0) for r in (getattr(summary, "nights", []) or [])),
            status="warn" if sky_summ.get("worst") else "ok",
            values=values,
        )
        for r in getattr(summary, "nights", []) or []:
            path = getattr(getattr(r, "ds", None), "path", "") or ""
            if not path or path.startswith("("):
                if out.onsky_log_path:
                    path = out.onsky_log_path
                else:
                    continue
            try:
                st = Path(path).stat()
            except OSError:
                continue
            if history.onsky_file_known(path, st.st_size, st.st_mtime):
                continue
            status = "ok"
            if not getattr(r, "usable", True):
                status = "bad"
            elif not getattr(r, "photometric", False):
                status = "warn"
            key = _record_history(
                "onsky",
                path,
                onsky.night_summary(r),
                camera_id=getattr(r.ds, "camera_id", cam),
                system_id=str(sid) if sid else None,
                n_frames=getattr(r, "n_frames", None),
                status=status,
                values=onsky.night_values(r, str(sid or "unknown")),
            )
            if key:
                history.mark_onsky_file(path, st.st_size, st.st_mtime, key)
    except Exception as exc:
        settings = import_shobs("settings")
        settings.log(f"NPOAP history sky record failed: {exc!r}")

    return out


def _sky_summary_dict(summary) -> dict[str, Any]:
    def n(v, nd=4):
        return round(v, nd) if v is not None and math.isfinite(v) else None

    bands = {}
    for band, b in (getattr(summary, "bands", None) or {}).items():
        bands[band] = {
            "zp1": n(getattr(b, "zp1", None)),
            "k": n(getattr(b, "k", None)),
            "fwhm_in_focus": n(getattr(b, "fwhm_in_focus", None), 3),
            "sky": n(getattr(b, "sky", None), 3),
            "cy": n(getattr(b, "cy", None), 3),
        }
    worst = ""
    if not any(
        math.isfinite(getattr(b, "zp1", float("nan")))
        for b in (getattr(summary, "bands", None) or {}).values()
    ):
        worst = "⚠ no photometric night yet"
    nights = getattr(summary, "nights", []) or []
    return {
        "nights": len({getattr(r.ds, "night", None) for r in nights}),
        "runs": len(nights),
        "bands": bands,
        "worst": worst,
        "overhead_s": n(getattr(summary, "overhead_s", None), 3),
    }


def _sky_values_rows(summary, pid: str) -> list[dict]:
    onsky = import_shobs("onsky")
    sp = import_shobs("shobs_profile")
    bands, cad = onsky.measured_records(summary)
    today = sp.now_iso()[:10]
    rows = []

    def add(key, rec, channel):
        if isinstance(rec, dict) and rec.get("value") is not None:
            rows.append(
                {
                    "key": key,
                    "value": rec["value"],
                    "sigma": rec.get("sigma"),
                    "unit": rec.get("unit"),
                    "source": "measured",
                    "channel": channel,
                    "profile_id": pid,
                    "date": today,
                }
            )

    for band, recs in bands.items():
        for key, rec in recs.items():
            if key == "fwhm_defocus" and isinstance(rec, dict):
                for _dk, dr in rec.items():
                    add("bands.fwhm_defocus", dr, band)
            else:
                add(f"bands.{key}", rec, band)
    for key, rec in cad.items():
        add(f"cadence.{key}", rec, None)
    return rows


def run_sky_from_lights_folder(
    lights_folder: str | Path,
    *,
    telescope_name: str | None = None,
    channel: str = "G",
    frames_are: str = "photometry",
    step: StepFn = None,
    save_system_profile: bool = True,
    apply_npoap_config: bool = True,
    include_existing_onsky_logs: bool = True,
) -> SkyAnalysisResult:
    """Mesure un dossier de lights (WCS recommandé) puis apprend ZP/extinction/seeing."""
    sky_folder = import_shobs("sky_folder")
    onsky = import_shobs("onsky")
    from config import OBSERVATORY

    site, aperture, elev_m = _npoap_site()
    name = (telescope_name or OBSERVATORY.get("name") or "Telescope").strip()

    def _s(msg: str) -> None:
        _step(step, msg)

    _s("Mesure du dossier de lights…")
    fr = sky_folder.run_folder(
        str(Path(lights_folder)),
        channel=channel,
        step=_s,
        elevation_m=elev_m,
        site=site,
    )
    doc = getattr(fr, "doc", None)
    if not doc:
        raise sky_folder.SkyFolderError(
            "Aucune mesure on-sky n'a pu être produite (WCS / catalogue / étoiles ?)."
        )
    doc["frames_are"] = frames_are

    datasets = []
    findings_pre = list(getattr(fr, "lines", []) or [])
    if include_existing_onsky_logs:
        _s("Lecture des logs on-sky existants…")
        paths = onsky.log_files()
        got, bad = onsky.read_logs(paths)
        datasets.extend(got)
        for p, why in bad:
            findings_pre.append(("warn", f"Log ignoré ({Path(p).name}): {why}"))

    _s("Chargement du log de cette nuit…")
    datasets.append(onsky.load_dataset(doc, path="(folder-run)"))

    # Filtrer sur la caméra dominante du run dossier
    cam_id = (doc.get("setup") or {}).get("camera_id") or getattr(datasets[-1], "camera_id", None)
    if cam_id:
        datasets = [d for d in datasets if getattr(d, "camera_id", None) == cam_id] or datasets

    out = _learn_and_save(
        datasets,
        telescope_name=name,
        aperture_mm=aperture,
        elevation_m=elev_m,
        step=step,
        save_system_profile=save_system_profile,
        apply_npoap_config=apply_npoap_config,
        folder_doc=doc if save_system_profile else None,
    )
    out.findings = findings_pre + out.findings
    return out


def run_sky_from_onsky_logs(
    *,
    telescope_name: str | None = None,
    camera_id: str | None = None,
    step: StepFn = None,
    save_system_profile: bool = True,
    apply_npoap_config: bool = True,
) -> SkyAnalysisResult:
    """Apprend uniquement depuis les logs déjà présents dans ``~/.shobs/onsky/``."""
    onsky = import_shobs("onsky")
    from config import OBSERVATORY

    _site, aperture, elev_m = _npoap_site()
    name = (telescope_name or OBSERVATORY.get("name") or "Telescope").strip()

    def _s(msg: str) -> None:
        _step(step, msg)

    _s("Lecture des logs on-sky…")
    paths = onsky.log_files()
    datasets, bad = onsky.read_logs(paths)
    findings = [("warn", f"Log ignoré ({Path(p).name}): {why}") for p, why in bad]
    if camera_id:
        datasets = [d for d in datasets if getattr(d, "camera_id", None) == camera_id]
    if not datasets:
        raise onsky.OnSkyError(
            "Aucun log on-sky utilisable dans ~/.shobs/onsky/. "
            "Lancez d'abord un run « dossier de lights »."
        )

    out = _learn_and_save(
        datasets,
        telescope_name=name,
        aperture_mm=aperture,
        elevation_m=elev_m,
        step=step,
        save_system_profile=save_system_profile,
        apply_npoap_config=apply_npoap_config,
        folder_doc=None,
    )
    out.findings = findings + out.findings
    return out


def onsky_from_system_profile(doc: dict) -> dict[str, Any]:
    """Convertit un profil système SHOBS en dict ``persist_onsky_calibration``."""
    sp = import_shobs("shobs_profile")
    bands_out: dict[str, dict[str, Any]] = {}
    primary = None
    primary_n = -1
    for band, slot in (doc.get("bands") or {}).items():
        if not isinstance(slot, dict):
            continue
        detail = {
            "zero_point": _finite(sp.value_of(slot.get("zero_point"))),
            "extinction_k": _finite(sp.value_of(slot.get("extinction_k"))),
            "seeing_fwhm_arcsec": _finite(sp.value_of(slot.get("fwhm_in_focus"))),
            "sky_mag_arcsec2": _finite(sp.value_of(slot.get("sky_brightness"))),
            "scintillation_cy": _finite(sp.value_of(slot.get("scintillation_cy"))),
        }
        cleaned = {k: v for k, v in detail.items() if v is not None}
        if cleaned:
            bands_out[str(band)] = cleaned
            n = slot.get("zero_point", {}).get("n") if isinstance(slot.get("zero_point"), dict) else 0
            n = int(n or 0)
            if detail["zero_point"] is not None and n >= primary_n:
                primary, primary_n = str(band), n
    if primary is None and bands_out:
        primary = next(iter(bands_out))
    out: dict[str, Any] = {
        "bands": bands_out,
        "band": primary,
        "shobs_system_profile_id": doc.get("profile_id"),
    }
    if primary and primary in bands_out:
        out.update(bands_out[primary])
    cad = doc.get("cadence") or {}
    oh = _finite(sp.value_of(cad.get("overhead_s")))
    if oh is not None:
        out["overhead_s"] = oh
    return out


def draw_sky_figure(fig, summary) -> None:
    plots = import_shobs("sky_plots")
    plots.draw(fig, summary)

