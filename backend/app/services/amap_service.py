from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AmapPoiCandidate, AmapPoiSearchRun, AmapRouteRun
from app.schemas.tools import (
    AmapGeocodeInput,
    AmapGeocodeOutput,
    AmapPoiCandidateSchema,
    AmapPoiSearchInput,
    AmapPoiSearchOutput,
    AmapReverseGeocodeInput,
    AmapReverseGeocodeOutput,
    AmapRoutePlanInput,
    AmapRoutePlanOutput,
    BuildAmapUriInput,
    BuildAmapUriOutput,
)


AMAP_BASE_URL = "https://restapi.amap.com"


class AmapService:
    def __init__(
        self,
        session: Session | None = None,
        *,
        client: Any | None = None,
        agent_run_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self._client = client
        self.agent_run_id = agent_run_id
        self.turn_id = turn_id

    def geocode(self, input_data: AmapGeocodeInput) -> AmapGeocodeOutput:
        request_json = {"tool": "amap_geocode", "address": input_data.address, "city": input_data.city}
        run = self._create_aux_run(city=input_data.city, keyword=input_data.address, types="geocode", request_json=request_json)
        if not self._has_key():
            self._finish_poi_run(run, status="disabled", response_json=None, error_message="AMAP_WEB_SERVICE_KEY is not configured")
            return AmapGeocodeOutput(city=input_data.city)
        try:
            response = self._get(
                "/v3/geocode/geo",
                {"address": input_data.address, "city": input_data.city},
            )
            self._finish_poi_run(run, status="succeeded", response_json=response, error_message=None)
        except Exception as exc:
            self._finish_poi_run(run, status="failed", response_json=None, error_message=str(exc))
            raise
        geocode = _first(response.get("geocodes"))
        lng, lat = _parse_lng_lat(geocode.get("location") if geocode else None)
        return AmapGeocodeOutput(
            formatted_address=geocode.get("formatted_address") if geocode else None,
            lng=lng,
            lat=lat,
            adcode=geocode.get("adcode") if geocode else None,
            city=_amap_text(geocode.get("city")) if geocode else input_data.city,
        )

    def reverse_geocode(self, input_data: AmapReverseGeocodeInput) -> AmapReverseGeocodeOutput:
        request_json = {
            "tool": "amap_reverse_geocode",
            "lng": input_data.lng,
            "lat": input_data.lat,
        }
        run = self._create_aux_run(
            city=None,
            keyword="reverse_geocode",
            types="reverse_geocode",
            request_json=request_json,
            center_lng=input_data.lng,
            center_lat=input_data.lat,
        )
        if not self._has_key():
            self._finish_poi_run(run, status="disabled", response_json=None, error_message="AMAP_WEB_SERVICE_KEY is not configured")
            return AmapReverseGeocodeOutput()
        try:
            response = self._get(
                "/v3/geocode/regeo",
                {
                    "location": f"{input_data.lng},{input_data.lat}",
                    "extensions": "all",
                    "radius": 1000,
                },
            )
            self._finish_poi_run(run, status="succeeded", response_json=response, error_message=None)
        except Exception as exc:
            self._finish_poi_run(run, status="failed", response_json=None, error_message=str(exc))
            raise
        regeocode = dict(response.get("regeocode") or {})
        address = dict(regeocode.get("addressComponent") or {})
        return AmapReverseGeocodeOutput(
            formatted_address=regeocode.get("formatted_address"),
            city=_amap_text(address.get("city")) or _amap_text(address.get("province")),
            district=_amap_text(address.get("district")),
            township=_amap_text(address.get("township")),
            pois=list(regeocode.get("pois") or []),
        )

    def poi_search(self, input_data: AmapPoiSearchInput) -> AmapPoiSearchOutput:
        limit = input_data.limit or self.settings.amap_search_limit
        radius = input_data.radius_meters or self.settings.amap_search_radius_meters
        request_json = {
            "city": input_data.city,
            "keyword": input_data.keyword,
            "types": input_data.types,
            "center_lng": input_data.center_lng,
            "center_lat": input_data.center_lat,
            "radius_meters": radius,
            "limit": limit,
        }
        run = self._create_poi_run(input_data, request_json=request_json, radius=radius, limit=limit)
        if not self._has_key():
            self._finish_poi_run(run, status="disabled", response_json=None, error_message="AMAP_WEB_SERVICE_KEY is not configured")
            return AmapPoiSearchOutput(
                search_run_id=str(run.id) if run else None,
                status="disabled",
                candidates=[],
                disabled=True,
                error_message="AMAP_WEB_SERVICE_KEY is not configured",
            )

        params: dict[str, Any]
        path: str
        if input_data.center_lng is not None and input_data.center_lat is not None:
            path = "/v3/place/around"
            params = {
                "location": f"{input_data.center_lng},{input_data.center_lat}",
                "keywords": input_data.keyword,
                "types": input_data.types,
                "radius": radius,
                "offset": limit,
                "page": 1,
                "extensions": "all",
            }
        else:
            path = "/v3/place/text"
            params = {
                "city": input_data.city,
                "keywords": input_data.keyword,
                "types": input_data.types,
                "offset": limit,
                "page": 1,
                "extensions": "all",
            }

        try:
            response = self._get(path, params)
            candidates = self._persist_candidates(run, response.get("pois", [])[:limit])
            self._finish_poi_run(run, status="succeeded", response_json=response, error_message=None)
            return AmapPoiSearchOutput(
                search_run_id=str(run.id) if run else None,
                status="succeeded",
                candidates=candidates,
            )
        except Exception as exc:
            self._finish_poi_run(run, status="failed", response_json=None, error_message=str(exc))
            return AmapPoiSearchOutput(
                search_run_id=str(run.id) if run else None,
                status="failed",
                candidates=[],
                error_message=str(exc),
            )

    def route_plan(self, input_data: AmapRoutePlanInput) -> AmapRoutePlanOutput:
        request_json = input_data.model_dump(mode="json")
        run = self._create_route_run(input_data, request_json=request_json)
        if not self._has_key():
            self._finish_route_run(run, status="disabled", response_json=None, error_message="AMAP_WEB_SERVICE_KEY is not configured")
            return AmapRoutePlanOutput(
                route_run_id=str(run.id) if run else None,
                status="disabled",
                disabled=True,
                error_message="AMAP_WEB_SERVICE_KEY is not configured",
            )

        path = _route_path(input_data.mode)
        params = {
            "origin": f"{input_data.origin_lng},{input_data.origin_lat}",
            "destination": f"{input_data.destination_lng},{input_data.destination_lat}",
        }
        try:
            response = self._get(path, params)
            distance, duration = _route_distance_duration(response, mode=input_data.mode)
            summary = _route_summary(distance, duration, input_data.mode)
            if run is not None:
                run.distance_meters = distance
                run.duration_seconds = duration
                run.summary_text = summary
            self._finish_route_run(run, status="succeeded", response_json=response, error_message=None)
            return AmapRoutePlanOutput(
                route_run_id=str(run.id) if run else None,
                status="succeeded",
                distance_meters=distance,
                duration_seconds=duration,
                summary_text=summary,
                raw_json=response,
            )
        except Exception as exc:
            self._finish_route_run(run, status="failed", response_json=None, error_message=str(exc))
            return AmapRoutePlanOutput(
                route_run_id=str(run.id) if run else None,
                status="failed",
                error_message=str(exc),
            )

    def build_uri(self, input_data: BuildAmapUriInput) -> BuildAmapUriOutput:
        mode = {
            "walking": "walk",
            "driving": "car",
            "transit": "bus",
            "bicycling": "ride",
        }.get(input_data.mode, "walk")
        target = f"{input_data.target_lng},{input_data.target_lat},{quote(input_data.target_name)}"
        query = [
            f"to={target}",
            f"mode={mode}",
            "src=just-pick-this",
            "coordinate=gaode",
            "callnative=1",
        ]
        if input_data.origin_lng is not None and input_data.origin_lat is not None:
            query.insert(0, f"from={input_data.origin_lng},{input_data.origin_lat},{quote('我的位置')}")
        return BuildAmapUriOutput(uri=f"https://uri.amap.com/navigation?{'&'.join(query)}")

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._has_key():
            raise RuntimeError("AMAP_WEB_SERVICE_KEY is not configured")
        key = self.settings.amap_web_service_key
        assert key is not None
        request_params = {
            name: value
            for name, value in params.items()
            if value is not None and value != ""
        }
        request_params["key"] = key.get_secret_value()
        if self._client is not None:
            response = self._client.get(f"{AMAP_BASE_URL}{path}", params=request_params)
        else:
            with httpx.Client(timeout=self.settings.web_search_timeout_seconds) as client:
                response = client.get(f"{AMAP_BASE_URL}{path}", params=request_params)
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        data = response.json()
        if str(data.get("status")) not in {"1", "success", "OK"}:
            raise RuntimeError(str(data.get("info") or data.get("infocode") or "AMap request failed"))
        return data

    def _has_key(self) -> bool:
        key = self.settings.amap_web_service_key
        return key is not None and bool(key.get_secret_value().strip())

    def _create_poi_run(
        self,
        input_data: AmapPoiSearchInput,
        *,
        request_json: dict[str, Any],
        radius: int,
        limit: int,
    ) -> AmapPoiSearchRun | None:
        if self.session is None:
            return None
        run = AmapPoiSearchRun(
            agent_run_id=self.agent_run_id,
            turn_id=self.turn_id,
            city=input_data.city,
            keyword=input_data.keyword,
            types=input_data.types,
            center_lng=input_data.center_lng,
            center_lat=input_data.center_lat,
            radius_meters=radius,
            limit=limit,
            request_json=request_json,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def _create_aux_run(
        self,
        *,
        city: str | None,
        keyword: str,
        types: str,
        request_json: dict[str, Any],
        center_lng: float | None = None,
        center_lat: float | None = None,
    ) -> AmapPoiSearchRun | None:
        if self.session is None:
            return None
        run = AmapPoiSearchRun(
            agent_run_id=self.agent_run_id,
            turn_id=self.turn_id,
            city=city,
            keyword=keyword,
            types=types,
            center_lng=center_lng,
            center_lat=center_lat,
            request_json=request_json,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def _finish_poi_run(
        self,
        run: AmapPoiSearchRun | None,
        *,
        status: str,
        response_json: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        if run is None:
            return
        run.status = status
        run.response_json = response_json
        run.error_message = error_message
        self.session.flush()

    def _persist_candidates(
        self,
        run: AmapPoiSearchRun | None,
        pois: list[dict[str, Any]],
    ) -> list[AmapPoiCandidateSchema]:
        candidates: list[AmapPoiCandidateSchema] = []
        for rank, raw in enumerate(pois, start=1):
            lng, lat = _parse_lng_lat(raw.get("location"))
            candidate = AmapPoiCandidateSchema(
                poi_id=str(raw.get("id") or "") or None,
                name=_amap_poi_name(raw.get("name")),
                type=_amap_text(raw.get("type")),
                typecode=_amap_text(raw.get("typecode")),
                address=_amap_text(raw.get("address")),
                lng=lng,
                lat=lat,
                distance_meters=_int_or_none(raw.get("distance")),
                tel=_amap_text(raw.get("tel")),
            )
            candidates.append(candidate)
            if self.session is not None and run is not None:
                self.session.add(
                    AmapPoiCandidate(
                        search_run_id=run.id,
                        rank=rank,
                        poi_id=candidate.poi_id,
                        name=candidate.name,
                        type=candidate.type,
                        typecode=candidate.typecode,
                        address=candidate.address,
                        lng=candidate.lng,
                        lat=candidate.lat,
                        distance_meters=candidate.distance_meters,
                        tel=candidate.tel,
                        raw_json=raw,
                    )
                )
        if self.session is not None:
            self.session.flush()
        return candidates

    def _create_route_run(self, input_data: AmapRoutePlanInput, *, request_json: dict[str, Any]) -> AmapRouteRun | None:
        if self.session is None:
            return None
        run = AmapRouteRun(
            agent_run_id=self.agent_run_id,
            turn_id=self.turn_id,
            mode=input_data.mode,
            origin_lng=input_data.origin_lng,
            origin_lat=input_data.origin_lat,
            destination_lng=input_data.destination_lng,
            destination_lat=input_data.destination_lat,
            request_json=request_json,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def _finish_route_run(
        self,
        run: AmapRouteRun | None,
        *,
        status: str,
        response_json: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        if run is None:
            return
        run.status = status
        run.response_json = response_json
        run.error_message = error_message
        self.session.flush()


def _first(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _parse_lng_lat(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, str) or "," not in value:
        return None, None
    lng, lat = value.split(",", 1)
    return _float_or_none(lng), _float_or_none(lat)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _amap_text(value: Any) -> str | None:
    if isinstance(value, list):
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _amap_poi_name(value: Any) -> str:
    text = _amap_text(value) or "未命名地点"
    for marker in ("(无)", "（无）", "(暂无)", "（暂无）"):
        text = text.replace(marker, "")
    return text.strip(" -·,，") or "未命名地点"


def _route_path(mode: str) -> str:
    if mode == "driving":
        return "/v3/direction/driving"
    if mode == "transit":
        return "/v3/direction/transit/integrated"
    if mode == "bicycling":
        return "/v4/direction/bicycling"
    return "/v3/direction/walking"


def _route_distance_duration(response: dict[str, Any], *, mode: str) -> tuple[int | None, int | None]:
    route = dict(response.get("route") or {})
    if mode == "transit":
        transit = _first(route.get("transits"))
        return _int_or_none(transit.get("distance")), _int_or_none(transit.get("duration"))
    path = _first(route.get("paths"))
    return _int_or_none(path.get("distance")), _int_or_none(path.get("duration"))


def _route_summary(distance: int | None, duration: int | None, mode: str) -> str | None:
    if distance is None and duration is None:
        return None
    mode_label = {
        "walking": "步行",
        "driving": "驾车",
        "transit": "公交",
        "bicycling": "骑行",
    }.get(mode, "路线")
    if duration is None:
        return f"{mode_label}约 {distance} 米"
    minutes = max(1, round(duration / 60))
    return f"{mode_label}约 {minutes} 分钟"
