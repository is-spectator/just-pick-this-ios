from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import anyio
import tldextract
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ImageAsset, WebSearchResult, WebSearchRun


@dataclass
class TavilyTextSearchResult:
    run_id: str | None
    results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TavilyImageSearchResult:
    run_id: str | None
    images: list[ImageAsset] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    extracted = tldextract.extract(url)
    if not extracted.domain or not extracted.suffix:
        return None
    return f"{extracted.domain}.{extracted.suffix}".lower()


class TavilyService:
    def __init__(self, session: Session, *, client: Any | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self._client = client

    async def search_text(self, query: str, *, max_results: int = 5) -> TavilyTextSearchResult:
        return await anyio.to_thread.run_sync(
            lambda: self.search_text_sync(query, max_results=max_results)
        )

    async def search_images(self, query: str, *, max_results: int = 8) -> TavilyImageSearchResult:
        return await anyio.to_thread.run_sync(
            lambda: self.search_images_sync(query, max_results=max_results)
        )

    def search_text_sync(self, query: str, *, max_results: int = 5) -> TavilyTextSearchResult:
        if not self._has_api_key():
            return TavilyTextSearchResult(run_id=None, results=[])

        request_json = {
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        run = self._create_run(query=query, search_type="text", request_json=request_json)
        try:
            response = self._client_instance().search(timeout=self.settings.tavily_timeout_seconds, **request_json)
            run.status = "success"
            run.response_json = _jsonable(response)
            results = self._persist_results(run, response.get("results", []))
            return TavilyTextSearchResult(run_id=str(run.id), results=results)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            return TavilyTextSearchResult(run_id=str(run.id), results=[])
        finally:
            self.session.flush()

    def search_images_sync(self, query: str, *, max_results: int = 8) -> TavilyImageSearchResult:
        if not self._has_api_key():
            return TavilyImageSearchResult(run_id=None, images=[], results=[])

        request_json = {
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": True,
            "include_image_descriptions": True,
        }
        run = self._create_run(query=query, search_type="image", request_json=request_json)
        try:
            response = self._client_instance().search(timeout=self.settings.tavily_timeout_seconds, **request_json)
            run.status = "success"
            run.response_json = _jsonable(response)
            results = self._persist_results(run, response.get("results", []))
            images = self._persist_image_candidates(
                run=run,
                query=query,
                images=response.get("images", []),
                results=response.get("results", []),
            )
            return TavilyImageSearchResult(run_id=str(run.id), images=images, results=results)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            return TavilyImageSearchResult(run_id=str(run.id), images=[], results=[])
        finally:
            self.session.flush()

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client

        from tavily import TavilyClient

        if not self._has_api_key() or self.settings.tavily_api_key is None:
            raise RuntimeError("TAVILY_API_KEY is required for Tavily search")
        self._client = TavilyClient(api_key=self.settings.tavily_api_key.get_secret_value())
        return self._client

    def _has_api_key(self) -> bool:
        return (
            self.settings.tavily_api_key is not None
            and bool(self.settings.tavily_api_key.get_secret_value().strip())
        )

    def _create_run(self, *, query: str, search_type: str, request_json: dict[str, Any]) -> WebSearchRun:
        run = WebSearchRun(
            id=uuid.uuid4(),
            provider="tavily",
            query_text=query,
            search_type=search_type,
            request_json=request_json,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def _persist_results(self, run: WebSearchRun, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        persisted: list[dict[str, Any]] = []
        for raw in results:
            url = str(raw.get("url") or "").strip()
            if not url:
                continue
            domain = extract_domain(url)
            result = WebSearchResult(
                web_search_run_id=run.id,
                title=str(raw.get("title") or ""),
                url=url,
                domain=domain,
                content=str(raw.get("content") or "")[:4000],
                score=_float_or_none(raw.get("score")),
                raw_json=_jsonable(raw),
            )
            self.session.add(result)
            self.session.flush()
            persisted.append(
                {
                    "id": str(result.id),
                    "title": result.title,
                    "url": result.url,
                    "domain": result.domain,
                    "content": result.content,
                    "score": result.score,
                }
            )
        return persisted

    def _persist_image_candidates(
        self,
        *,
        run: WebSearchRun,
        query: str,
        images: list[Any],
        results: list[dict[str, Any]],
    ) -> list[ImageAsset]:
        result_source_url = _first_result_url(results)
        candidates: list[ImageAsset] = []
        for index, raw_image in enumerate(images):
            image = _normalize_image(raw_image, fallback_source_url=result_source_url)
            url = image.get("url")
            if not url:
                continue
            source_url = image.get("source_url")
            source_domain = extract_domain(source_url)
            asset = ImageAsset(
                source_type="tavily_web",
                url=url,
                thumbnail_url=image.get("thumbnail_url"),
                source_url=source_url,
                source_domain=source_domain,
                credit="Tavily web image candidate",
                verified=False,
                verification_status="candidate",
                is_ai_generated=False,
                ai_generated_risk="unknown",
                displayable=False,
                query_text=query,
                tavily_result_id=str(image.get("id") or index),
                web_search_run_id=run.id,
                license_note="引用图，仅作识别和购买参考",
                alt_text=image.get("description"),
                metadata_json={"raw": _jsonable(raw_image), "description": image.get("description")},
            )
            self.session.add(asset)
            self.session.flush()
            candidates.append(asset)
        return candidates


def _normalize_image(raw_image: Any, *, fallback_source_url: str | None) -> dict[str, Any]:
    if isinstance(raw_image, str):
        return {"url": raw_image, "source_url": fallback_source_url}
    if not isinstance(raw_image, dict):
        return {}
    return {
        "id": raw_image.get("id") or raw_image.get("result_id"),
        "url": raw_image.get("url") or raw_image.get("image_url"),
        "thumbnail_url": raw_image.get("thumbnail_url") or raw_image.get("thumbnail"),
        "source_url": (
            raw_image.get("source_url")
            or raw_image.get("source")
            or raw_image.get("page_url")
            or raw_image.get("origin_url")
            or fallback_source_url
        ),
        "description": raw_image.get("description") or raw_image.get("image_description"),
    }


def _first_result_url(results: list[dict[str, Any]]) -> str | None:
    for result in results:
        url = result.get("url")
        if url:
            return str(url)
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
