"""
Mini-séquence d'imagerie NINA (multi-cibles, multi-filtres).

Orchestration légère sans serveur Node : refroidissement, slew, captures, park.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.nina_client import NinaClient, NinaFilterInfo

LogFn = Callable[[str], None]
AbortFn = Callable[[], bool]


class NinaSequenceAborted(Exception):
    """Levée lorsque l'utilisateur arrête la séquence."""


@dataclass
class NinaSequenceTarget:
    name: str
    ra_deg: float
    dec_deg: float


@dataclass
class NinaFilterStep:
    """Étape filtre : nom NINA (vide = pas de changement de filtre)."""

    filter_name: str
    frame_count: int


@dataclass
class NinaSequencePlan:
    targets: List[NinaSequenceTarget]
    filter_steps: List[NinaFilterStep]
    duration_s: float
    gain: float
    center_slew: bool = False
    cool_camera: bool = False
    cool_target_c: float = -5.0
    park_at_end: bool = True
    connect_at_start: bool = True
    start_guider: bool = False
    auto_focus_per_target: bool = False
    stop_guider_at_end: bool = False


@dataclass
class NinaSequenceResult:
    targets_done: int = 0
    frames_taken: int = 0
    aborted: bool = False
    errors: List[str] = field(default_factory=list)


def parse_filter_names_csv(text: str) -> List[str]:
    """Découpe « G, BP, RP » en noms de filtres."""
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def build_filter_steps(
    filter_names: List[str],
    frames_per_filter: int,
) -> List[NinaFilterStep]:
    if frames_per_filter < 1:
        raise ValueError("Nombre de images par filtre ≥ 1")
    if not filter_names:
        return [NinaFilterStep(filter_name="", frame_count=frames_per_filter)]
    return [
        NinaFilterStep(filter_name=name, frame_count=frames_per_filter)
        for name in filter_names
    ]


class NinaSequenceRunner:
    def __init__(
        self,
        client: NinaClient,
        plan: NinaSequencePlan,
        *,
        log: Optional[LogFn] = None,
        should_abort: Optional[AbortFn] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.client = client
        self.plan = plan
        self._log = log or (lambda _msg: None)
        self._should_abort = should_abort or (lambda: False)
        self._on_progress = on_progress or (lambda _s: None)

    def _check_abort(self) -> None:
        if self._should_abort():
            raise NinaSequenceAborted()

    def _progress(self, text: str) -> None:
        self._on_progress(text)

    def run(self) -> NinaSequenceResult:
        plan = self.plan
        result = NinaSequenceResult()
        if not plan.targets:
            raise ValueError("Aucune cible dans la séquence")

        self._log("=== Début séquence NINA ===")
        self._progress("Démarrage…")
        self._check_abort()

        if plan.connect_at_start:
            self._log("Connexion des périphériques…")
            self.client.connect_all()

        if plan.cool_camera:
            self._log(f"Refroidissement caméra → {plan.cool_target_c}°C…")
            self._progress("Refroidissement caméra…")
            self.client.cool_camera_and_wait(plan.cool_target_c)
            self._log("Caméra à température ✓")

        mount_unparked = False
        guider_started = False

        try:
            for ti, target in enumerate(plan.targets):
                self._check_abort()
                self._progress(f"Cible {ti + 1}/{len(plan.targets)} : {target.name}")
                self._log(f"--- Cible {ti + 1}/{len(plan.targets)} : {target.name} ---")

                self.client.slew_to_target(
                    target.name,
                    target.ra_deg,
                    target.dec_deg,
                    center=plan.center_slew,
                    unpark_first=not mount_unparked,
                )
                mount_unparked = True
                self._log(f"Pointage {target.name} ✓")

                if plan.auto_focus_per_target:
                    self._check_abort()
                    self._log("Autofocus…")
                    af = self.client.focuser_autofocus()
                    if not self._api_ok(af):
                        self._log("Autofocus : avertissement (échec ou non disponible)")
                    else:
                        self._log("Autofocus ✓")

                if plan.start_guider and not guider_started:
                    self._check_abort()
                    self._log("Démarrage du guidage…")
                    self.client.ensure_guider_running()
                    guider_started = True
                    self._log("Guidage actif ✓")

                for fstep in plan.filter_steps:
                    self._check_abort()
                    filt: Optional[NinaFilterInfo] = None
                    if fstep.filter_name:
                        self._log(f"Filtre {fstep.filter_name}…")
                        filt = self.client.resolve_filter(fstep.filter_name)
                        self.client.change_filter_verified(filt)
                        self._log(f"Filtre {filt.name} (ID {filt.filter_id}) ✓")

                    for frame_i in range(fstep.frame_count):
                        self._check_abort()
                        label = f"{target.name}"
                        if fstep.filter_name:
                            label += f" / {fstep.filter_name}"
                        self._progress(
                            f"{label} — image {frame_i + 1}/{fstep.frame_count}"
                        )
                        self._log(
                            f"Capture {frame_i + 1}/{fstep.frame_count}"
                            + (f" [{fstep.filter_name}]" if fstep.filter_name else "")
                            + f" {plan.duration_s}s gain {plan.gain}"
                        )
                        self.client.capture_checked(
                            plan.duration_s,
                            plan.gain,
                            target_name=target.name,
                            filter_name=fstep.filter_name or None,
                            wait_complete=True,
                        )
                        result.frames_taken += 1

                result.targets_done += 1
                self._log(f"Cible {target.name} terminée ✓")

        except NinaSequenceAborted:
            result.aborted = True
            self._log("Séquence interrompue par l'utilisateur")
            self._progress("Interrompu")
        except Exception as exc:
            result.errors.append(str(exc))
            self._log(f"Erreur séquence : {exc}")
            self._progress("Erreur")
            raise
        finally:
            if plan.stop_guider_at_end and guider_started:
                try:
                    self.client.guider_stop()
                    self._log("Guidage arrêté")
                except Exception:
                    pass
            if plan.park_at_end and mount_unparked and not result.aborted:
                try:
                    self._check_abort()
                except NinaSequenceAborted:
                    pass
                else:
                    try:
                        self._log("Parking monture…")
                        self._progress("Parking…")
                        pr = self.client.mount_park()
                        if self._api_ok(pr):
                            self._log("Monture parquée ✓")
                        else:
                            self._log("Parking : réponse NINA incertaine")
                    except Exception as e:
                        self._log(f"Parking échoué : {e}")

        if not result.aborted and not result.errors:
            self._log(
                f"=== Séquence terminée : {result.targets_done} cible(s), "
                f"{result.frames_taken} image(s) ==="
            )
            self._progress("Terminé")
        return result

    @staticmethod
    def _api_ok(result) -> bool:
        from core.nina_client import api_success

        return api_success(result)
