"""
Client HTTP pour l'API avancée NINA (v2).

Référence : https://nighttime-imaging.eu/docs/master/site/advanced_api/api.html
Inspiré du proxy astrobatch (GET + paramètres query, timeouts longs pour capture / slew).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

DEVICE_TYPES = ("mount", "camera", "filterwheel", "focuser", "flatdevice", "guider")

_STATUS_DEVICE_MAP = {
    "mount": ("Mount", "Connected"),
    "camera": ("Camera", "Connected"),
    "filterwheel": ("FilterWheel", "Connected"),
    "focuser": ("Focuser", "Connected"),
    "guider": ("Guider", "Connected"),
    "flatdevice": ("FlatDevice", "Connected"),
}


@dataclass(frozen=True)
class NinaConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 1888
    protocol: str = "http"

    def validate(self) -> None:
        if not (self.host or "").strip():
            raise ValueError("Hôte NINA requis")
        if self.port < 1 or self.port > 65535:
            raise ValueError("Port NINA invalide (1–65535)")
        if self.protocol not in ("http", "https"):
            raise ValueError("Protocole : http ou https")

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host.strip()}:{self.port}"


@dataclass
class NinaApiResult:
    ok: bool
    status: int
    body: Any
    url: str
    error: Optional[str] = None


@dataclass
class NinaConnectionTest:
    success: bool
    message: str
    devices: Dict[str, bool] = field(default_factory=dict)
    equipment: Optional[Dict[str, Any]] = None
    raw: Any = None


def api_success(result: NinaApiResult) -> bool:
    if not result.ok:
        return False
    if isinstance(result.body, dict) and "Success" in result.body:
        return bool(result.body["Success"])
    return True


def api_error_message(result: NinaApiResult) -> str:
    """Message d'erreur lisible (réponse JSON NINA ou HTTP)."""
    if result.error:
        return result.error
    if isinstance(result.body, dict):
        err = result.body.get("Error")
        if err not in (None, ""):
            return str(err)
        resp = result.body.get("Response")
        if isinstance(resp, str) and resp:
            return resp
    if result.status:
        return f"HTTP {result.status}"
    return "erreur inconnue"


def equipment_response(result: NinaApiResult) -> Optional[Dict[str, Any]]:
    if not isinstance(result.body, dict):
        return None
    resp = result.body.get("Response")
    return resp if isinstance(resp, dict) else None


def device_statuses(equipment_info: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    if not equipment_info:
        return out
    for device, path in _STATUS_DEVICE_MAP.items():
        section = equipment_info.get(path[0])
        if isinstance(section, dict):
            out[device] = bool(section.get(path[1]))
        else:
            out[device] = False
    return out


@dataclass(frozen=True)
class NinaFilterInfo:
    filter_id: int
    name: str


class NinaClient:
    """Client HTTP pour piloter NINA à distance (API v2)."""

    def __init__(self, config: NinaConnectionConfig, session: Optional[requests.Session] = None):
        config.validate()
        self.config = config
        self._session = session or requests.Session()
        self._session.headers.setdefault("Accept", "application/json")

    def _build_url(self, endpoint_path: str, query: Optional[Dict[str, Any]] = None) -> str:
        path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
        base = f"{self.config.base_url}{path}"
        if not query:
            return base
        params = {
            k: v
            for k, v in query.items()
            if v is not None and v != ""
        }
        if not params:
            return base
        return f"{base}?{urlencode(params)}"

    def call(
        self,
        endpoint_path: str,
        query: Optional[Dict[str, Any]] = None,
        *,
        timeout_s: float = 10.0,
    ) -> NinaApiResult:
        url = self._build_url(endpoint_path, query)
        try:
            response = self._session.get(url, timeout=timeout_s)
            text = response.text
            try:
                body = response.json() if text else None
            except ValueError:
                body = text
            return NinaApiResult(
                ok=response.ok,
                status=response.status_code,
                body=body,
                url=url,
            )
        except requests.Timeout:
            return NinaApiResult(
                ok=False,
                status=0,
                body=None,
                url=url,
                error="Délai dépassé",
            )
        except requests.RequestException as exc:
            logger.debug("NINA API %s : %s", url, exc)
            return NinaApiResult(
                ok=False,
                status=0,
                body=None,
                url=url,
                error=str(exc),
            )

    def get_equipment_info(self, timeout_s: float = 10.0) -> tuple[NinaApiResult, Optional[Dict[str, Any]]]:
        result = self.call("/v2/api/equipment/info", timeout_s=timeout_s)
        return result, equipment_response(result)

    def test_connection(self) -> NinaConnectionTest:
        result, equipment = self.get_equipment_info()
        if result.error:
            return NinaConnectionTest(
                success=False,
                message=f"Connexion impossible : {result.error}",
                raw=result.body,
            )
        if not api_success(result):
            err = ""
            if isinstance(result.body, dict):
                err = str(result.body.get("Error") or result.body.get("Response") or "")
            return NinaConnectionTest(
                success=False,
                message=f"NINA a répondu HTTP {result.status}" + (f" — {err}" if err else ""),
                raw=result.body,
            )
        devices = device_statuses(equipment)
        connected = [d for d, on in devices.items() if on]
        msg = f"Connexion OK ({self.config.base_url})"
        if connected:
            msg += f" — connectés : {', '.join(connected)}"
        else:
            msg += " — aucun périphérique connecté (utilisez « Connecter » ou NINA)"
        return NinaConnectionTest(
            success=True,
            message=msg,
            devices=devices,
            equipment=equipment,
            raw=result.body,
        )

    def connect_device(self, device: str, timeout_s: float = 15.0) -> NinaApiResult:
        if device not in DEVICE_TYPES:
            raise ValueError(f"Périphérique inconnu : {device}")
        return self.call(f"/v2/api/equipment/{device}/connect", timeout_s=timeout_s)

    def connect_all(self, timeout_s: float = 15.0) -> List[tuple[str, NinaApiResult]]:
        results: List[tuple[str, NinaApiResult]] = []
        for device in DEVICE_TYPES:
            results.append((device, self.connect_device(device, timeout_s=timeout_s)))
        return results

    def mount_unpark(self, timeout_s: float = 60.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/mount/unpark", timeout_s=timeout_s)

    def mount_park(self, timeout_s: float = 120.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/mount/park", timeout_s=timeout_s)

    def camera_cool(self, target_temp_c: float, minutes: int = 0, timeout_s: float = 15.0) -> NinaApiResult:
        return self.call(
            "/v2/api/equipment/camera/cool",
            {"temperature": target_temp_c, "minutes": minutes},
            timeout_s=timeout_s,
        )

    def guider_connect(self, timeout_s: float = 15.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/guider/connect", timeout_s=timeout_s)

    def guider_start(self, timeout_s: float = 120.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/guider/start", timeout_s=timeout_s)

    def guider_stop(self, timeout_s: float = 30.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/guider/stop", timeout_s=timeout_s)

    def focuser_autofocus(self, timeout_s: float = 15.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/focuser/auto-focus", timeout_s=timeout_s)

    def filterwheel_connect(self, timeout_s: float = 15.0) -> NinaApiResult:
        return self.call("/v2/api/equipment/filterwheel/connect", timeout_s=timeout_s)

    def filterwheel_change(
        self,
        *,
        filter_id: Optional[int] = None,
        filter_name: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> NinaApiResult:
        if filter_id is not None:
            query: Dict[str, Any] = {"filterId": filter_id}
        elif filter_name:
            query = {"filterName": filter_name}
        else:
            raise ValueError("filter_id ou filter_name requis")
        return self.call(
            "/v2/api/equipment/filterwheel/change-filter",
            query,
            timeout_s=timeout_s,
        )

    @staticmethod
    def list_filters(equipment: Optional[Dict[str, Any]]) -> List[NinaFilterInfo]:
        if not equipment:
            return []
        fw = equipment.get("FilterWheel")
        if not isinstance(fw, dict):
            return []
        raw = fw.get("AvailableFilters") or fw.get("Filters") or []
        if not isinstance(raw, list):
            return []
        out: List[NinaFilterInfo] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                fid = int(item.get("Id"))
            except (TypeError, ValueError):
                continue
            name = str(item.get("Name") or item.get("Filter") or "").strip()
            if name:
                out.append(NinaFilterInfo(filter_id=fid, name=name))
        return out

    def resolve_filter(
        self, name: str, equipment: Optional[Dict[str, Any]] = None
    ) -> NinaFilterInfo:
        """Trouve un filtre par nom (insensible à la casse)."""
        if equipment is None:
            _, equipment = self.get_equipment_info()
        key = name.strip().lower()
        for f in self.list_filters(equipment):
            if f.name.lower() == key:
                return f
        raise ValueError(f"Filtre « {name} » introuvable dans NINA")

    def change_filter_verified(
        self,
        filter_info: NinaFilterInfo,
        *,
        max_attempts: int = 2,
        poll_interval_s: float = 0.5,
        move_timeout_s: float = 15.0,
    ) -> None:
        """Change de filtre et attend la confirmation du slot."""
        for attempt in range(1, max_attempts + 1):
            if not self._ensure_filterwheel_connected():
                raise RuntimeError("Roue à filtres non connectée")
            result = self.filterwheel_change(filter_id=filter_info.filter_id, timeout_s=30.0)
            if not api_success(result):
                if attempt == max_attempts:
                    raise RuntimeError(self._format_failure(f"Filtre {filter_info.name}", result))
                continue

            deadline = time.monotonic() + move_timeout_s
            while time.monotonic() < deadline:
                _, equipment = self.get_equipment_info(timeout_s=10.0)
                selected = (equipment or {}).get("FilterWheel", {}).get("SelectedFilter")
                if isinstance(selected, dict) and int(selected.get("Id", -1)) == filter_info.filter_id:
                    return
                time.sleep(poll_interval_s)

            if attempt == max_attempts:
                raise RuntimeError(
                    f"Roue à filtres : slot {filter_info.filter_id} ({filter_info.name}) non confirmé"
                )

    def _ensure_filterwheel_connected(self) -> bool:
        _, equipment = self.get_equipment_info()
        fw = (equipment or {}).get("FilterWheel")
        if isinstance(fw, dict) and fw.get("Connected"):
            return True
        result = self.filterwheel_connect()
        return api_success(result)

    def cool_camera_and_wait(
        self,
        target_temp_c: float,
        *,
        tolerance_c: float = 0.5,
        timeout_s: float = 20 * 60.0,
        poll_interval_s: float = 10.0,
    ) -> None:
        _, equipment = self.get_equipment_info()
        camera = (equipment or {}).get("Camera")
        if not isinstance(camera, dict) or not camera.get("Connected"):
            raise RuntimeError("Caméra non connectée — impossible de refroidir")

        current = float(camera.get("Temperature", 99.0))
        if current <= target_temp_c + tolerance_c:
            return

        result = self.camera_cool(target_temp_c)
        if not api_success(result):
            raise RuntimeError(self._format_failure("Refroidissement caméra", result))

        if not self.poll_until(
            lambda info: float((info or {}).get("Camera", {}).get("Temperature", 99)) <= target_temp_c + tolerance_c,
            timeout_s=timeout_s,
            interval_s=poll_interval_s,
        ):
            raise RuntimeError(f"Timeout refroidissement caméra (objectif {target_temp_c}°C)")

    def ensure_guider_running(self) -> None:
        _, equipment = self.get_equipment_info()
        guider = (equipment or {}).get("Guider")
        if isinstance(guider, dict) and guider.get("Connected") and guider.get("GuiderState") in (
            "Guiding",
            "Locked",
            "Running",
        ):
            return
        if not isinstance(guider, dict) or not guider.get("Connected"):
            cr = self.guider_connect()
            if not api_success(cr):
                raise RuntimeError(self._format_failure("Connexion guideur", cr))
        sr = self.guider_start(timeout_s=120.0)
        if not api_success(sr):
            raise RuntimeError(self._format_failure("Démarrage guidage", sr))

    def mount_tracking(self, on: bool, timeout_s: float = 15.0) -> NinaApiResult:
        return self.call(
            "/v2/api/equipment/mount/tracking",
            {"on": str(on).lower()},
            timeout_s=timeout_s,
        )

    def mount_set_target(
        self,
        name: str,
        ra_deg: float,
        dec_deg: float,
        timeout_s: float = 10.0,
    ) -> NinaApiResult:
        return self.call(
            "/v2/api/equipment/mount/target",
            {"name": name, "ra": ra_deg, "dec": dec_deg},
            timeout_s=timeout_s,
        )

    def mount_slew(
        self,
        ra_deg: float,
        dec_deg: float,
        *,
        name: str = "",
        wait_for_result: bool = True,
        center: bool = False,
        timeout_s: float = 180.0,
    ) -> NinaApiResult:
        query: Dict[str, Any] = {
            "ra": ra_deg,
            "dec": dec_deg,
            "waitForResult": str(wait_for_result).lower(),
        }
        if name:
            query["name"] = name
        if center:
            query["center"] = "true"
        return self.call("/v2/api/equipment/mount/slew", query, timeout_s=timeout_s)

    def slew_to_target(
        self,
        name: str,
        ra_deg: float,
        dec_deg: float,
        *,
        center: bool = False,
        unpark_first: bool = True,
        enable_tracking: bool = True,
    ) -> None:
        """
        Pointe la monture vers une cible (déparkage + tracking optionnels).

        Raises
        ------
        RuntimeError
            Si une étape échoue.
        """
        if unpark_first:
            r = self.mount_unpark()
            if not api_success(r):
                raise RuntimeError(self._format_failure("Déparkage", r))

        if enable_tracking:
            r = self.mount_tracking(True)
            if not api_success(r):
                raise RuntimeError(self._format_failure("Tracking", r))

        tr = self.mount_set_target(name, ra_deg, dec_deg)
        if not api_success(tr):
            logger.debug("mount/target ignoré ou non supporté : %s", tr.body)

        sr = self.mount_slew(ra_deg, dec_deg, name=name, center=center)
        if not api_success(sr):
            raise RuntimeError(self._format_failure("Slew", sr))

    @staticmethod
    def selected_filter_name(equipment: Optional[Dict[str, Any]]) -> Optional[str]:
        if not equipment:
            return None
        fw = equipment.get("FilterWheel")
        if not isinstance(fw, dict):
            return None
        sel = fw.get("SelectedFilter")
        if isinstance(sel, dict):
            name = str(sel.get("Name") or "").strip()
            return name or None
        return None

    def prepare_filter_for_light_capture(
        self,
        *,
        preferred: str = "G",
        equipment: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Évite une capture LIGHT sur le filtre Dark : bascule vers ``preferred`` si besoin.
        Retourne le nom de filtre à passer à l'API ``capture``.
        """
        if equipment is None:
            _, equipment = self.get_equipment_info()
        if not equipment or not equipment.get("FilterWheel", {}).get("Connected"):
            return None
        current = self.selected_filter_name(equipment)
        if not current:
            return None
        if current.lower() != "dark":
            return current
        filt = self.resolve_filter(preferred, equipment)
        self.change_filter_verified(filt)
        return filt.name

    def wait_for_camera_idle(self, timeout_s: float = 180.0) -> None:
        """Attend la fin d'exposition / téléchargement (API capture non bloquante)."""

        def _idle(info: Optional[Dict[str, Any]]) -> bool:
            cam = (info or {}).get("Camera")
            if not isinstance(cam, dict):
                return False
            return not bool(cam.get("IsExposing"))

        if not self.poll_until(_idle, timeout_s=timeout_s, interval_s=2.0):
            raise RuntimeError("Timeout en attente de fin d'exposition caméra")

    def capture_checked(
        self,
        duration_s: float,
        gain: float,
        *,
        target_name: str = "",
        filter_name: Optional[str] = None,
        save: bool = True,
        timeout_s: Optional[float] = None,
        wait_complete: bool = False,
    ) -> None:
        result = self.capture(
            duration_s,
            gain,
            target_name=target_name,
            filter_name=filter_name,
            save=save,
            timeout_s=timeout_s,
        )
        if not api_success(result):
            raise RuntimeError(self._format_failure("Capture", result))
        if result.error:
            raise RuntimeError(result.error)
        if wait_complete:
            self.wait_for_camera_idle(timeout_s=max(180.0, duration_s + 120.0))

    def capture(
        self,
        duration_s: float,
        gain: float,
        *,
        target_name: str = "",
        filter_name: Optional[str] = None,
        save: bool = True,
        timeout_s: Optional[float] = None,
    ) -> NinaApiResult:
        if duration_s <= 0:
            raise ValueError("Durée d'exposition positive requise")
        if gain < 0:
            raise ValueError("Gain >= 0 requis")
        if timeout_s is None:
            timeout_s = max(30.0, duration_s + 15.0)
        query: Dict[str, Any] = {
            "duration": duration_s,
            "gain": int(gain) if float(gain).is_integer() else gain,
            "save": "true" if save else "false",
        }
        if target_name:
            query["targetName"] = target_name
        if filter_name:
            query["filter"] = filter_name
        return self.call(
            "/v2/api/equipment/camera/capture",
            query,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _format_failure(step: str, result: NinaApiResult) -> str:
        if result.error:
            return f"{step} : {result.error}"
        detail = api_error_message(result)
        return f"{step} échoué (HTTP {result.status}) : {detail}"

    def poll_until(
        self,
        condition,
        *,
        timeout_s: float = 60.0,
        interval_s: float = 2.0,
    ) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            _, equipment = self.get_equipment_info(timeout_s=10.0)
            if condition(equipment):
                return True
            time.sleep(interval_s)
        return False
