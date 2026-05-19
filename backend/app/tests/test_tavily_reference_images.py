from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.config import get_settings
from app.models import ImageAsset, WebSearchResult, WebSearchRun
from app.retrieval import tavily_service as tavily_module
from app.retrieval.tavily_service import TavilyService
from app.schemas.tools import CreateRecommendationCardInput
from app.services.image_selection_service import ImageSelectionService
from app.services.runtime import (
    create_question_for_turn,
    create_turn,
    get_or_create_conversation,
    ensure_user,
    session_scope,
)
from app.tools.errors import ToolValidationError
from app.tools.recommendation import create_recommendation_card

from .conftest import bootstrap, chat_turn


class FakeTavilyClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def test_tavily_key_missing_still_returns_recommendation_card_without_image(
    monkeypatch: pytest.MonkeyPatch,
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "")
        get_settings.cache_clear()
        with session_scope() as session:
            datong_images = list(
                session.scalars(select(ImageAsset).where(ImageAsset.place_key == "datong-xijindao"))
            )
            original_state = [
                (image.id, image.displayable, image.verification_status, image.verified)
                for image in datong_images
            ]
            for image in datong_images:
                image.displayable = False
                image.verified = False
                image.verification_status = "candidate"

        try:
            boot = await bootstrap(async_client, device_id="pytest-no-tavily-image")
            body = await chat_turn(
                async_client,
                conversation_id=boot["conversation_id"],
                message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
            )
            assert body["cards"], body
            card = body["cards"][0]
            assert card["image"] is None
            assert card["image_status"] == "missing"
        finally:
            with session_scope() as session:
                for image_id, displayable, verification_status, verified in original_state:
                    image = session.get(ImageAsset, image_id)
                    if image is not None:
                        image.displayable = displayable
                        image.verification_status = verification_status
                        image.verified = verified
            get_settings.cache_clear()

    run_async(scenario)


def test_tavily_trusted_official_image_is_persisted_and_displayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "results": [
            {
                "title": "Waveshare 5inch HDMI LCD",
                "url": "https://www.waveshare.com/5inch-hdmi-lcd.htm",
                "content": "Official product page.",
                "score": 0.93,
            }
        ],
        "images": [
            {
                "url": "https://www.waveshare.com/w/upload/5/5d/5inch-HDMI-LCD.jpg",
                "source_url": "https://www.waveshare.com/5inch-hdmi-lcd.htm",
                "description": "Official product photo.",
            }
        ],
    }
    monkeypatch.setattr(
        tavily_module,
        "get_settings",
        lambda: SimpleNamespace(tavily_api_key=SecretStr("unit-test-key"), tavily_timeout_seconds=8),
    )

    with session_scope() as session:
        selector = ImageSelectionService(
            session,
            tavily_service=TavilyService(session, client=FakeTavilyClient(response)),
        )
        image = selector.find_best_card_image_sync(query="Waveshare 5-inch HDMI LCD", allow_tavily=True)

        assert image is not None
        assert image.source_type == "tavily_web"
        assert image.source_domain == "waveshare.com"
        assert image.displayable is True
        assert image.verification_status == "verified"
        assert image.is_ai_generated is False
        assert image.license_note == "引用图，仅作识别和购买参考"
        assert session.scalar(select(func.count(WebSearchRun.id)).where(WebSearchRun.provider == "tavily")) >= 1
        assert session.scalar(select(func.count(WebSearchResult.id)).where(WebSearchResult.domain == "waveshare.com")) >= 1
        assert not _web_search_requests_contain_key(session)


def test_tavily_suspected_ai_image_is_persisted_but_not_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "results": [
            {
                "title": "Generated image gallery",
                "url": "https://civitai.com/images/123",
                "content": "AI generated image gallery.",
                "score": 0.82,
            }
        ],
        "images": [
            {
                "url": "https://image.civitai.com/midjourney-output.png",
                "source_url": "https://civitai.com/images/123",
                "description": "AI generated product render.",
            }
        ],
    }
    monkeypatch.setattr(
        tavily_module,
        "get_settings",
        lambda: SimpleNamespace(tavily_api_key=SecretStr("unit-test-key"), tavily_timeout_seconds=8),
    )

    with session_scope() as session:
        selector = ImageSelectionService(
            session,
            tavily_service=TavilyService(session, client=FakeTavilyClient(response)),
        )
        image = selector.find_best_card_image_sync(query="AI generated product render", allow_tavily=True)
        assert image is None

        candidate = session.scalar(
            select(ImageAsset)
            .where(ImageAsset.source_type == "tavily_web", ImageAsset.source_domain == "civitai.com")
            .order_by(ImageAsset.created_at.desc())
        )
        assert candidate is not None
        assert candidate.displayable is False
        assert candidate.verification_status == "candidate"
        assert candidate.ai_generated_risk == "high"


def test_create_recommendation_card_rejects_non_displayable_or_ai_images(
    run_async: Any,
) -> None:
    async def scenario() -> None:
        with session_scope() as session:
            user = ensure_user(session, device_uid="pytest-image-tool-user")
            conversation = get_or_create_conversation(session, user=user, always_create=True)
            turn = create_turn(session, conversation=conversation, user=user, role="user", content="测试屏幕推荐")
            question = create_question_for_turn(session, conversation=conversation, user=user, turn=turn)
            ai_image = ImageAsset(
                source_type="tavily_web",
                url="https://example.com/ai-generated.png",
                source_url="https://example.com/ai-generated",
                source_domain="example.com",
                verified=True,
                verification_status="verified",
                is_ai_generated=True,
                ai_generated_risk="high",
                displayable=True,
                license_note="引用图，仅作识别和购买参考",
            )
            candidate_image = ImageAsset(
                source_type="tavily_web",
                url="https://example.com/candidate.png",
                source_url="https://example.com/candidate",
                source_domain="example.com",
                verified=False,
                verification_status="candidate",
                is_ai_generated=False,
                ai_generated_risk="unknown",
                displayable=False,
                license_note="引用图，仅作识别和购买参考",
            )
            session.add_all([ai_image, candidate_image])
            session.flush()
            ids = {
                "user_id": str(user.id),
                "question_id": str(question.id),
                "ai_image_id": str(ai_image.id),
                "candidate_image_id": str(candidate_image.id),
            }

        for image_id in (ids["ai_image_id"], ids["candidate_image_id"]):
            with session_scope() as session:
                with pytest.raises(ToolValidationError):
                    await create_recommendation_card(
                        session,
                        CreateRecommendationCardInput(
                            question_id=ids["question_id"],
                            user_id=ids["user_id"],
                            title="测试推荐卡",
                            subtitle="图片校验测试",
                            reason="验证图片不能是 AI，也必须 verified/displayable。",
                            bullets=["证据存在", "图片校验严格"],
                            image_asset_id=image_id,
                            confidence=0.8,
                            evidence_ids=["pytest-evidence"],
                        ),
                    )

    run_async(scenario)


def test_no_secrets_committed() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    scanned_patterns = ["*.py", "*.md", "*.toml", "*.env.example"]
    forbidden = ["sk-" + "or-v1-"]
    violations: list[str] = []

    for pattern in scanned_patterns:
        for path in backend_root.rglob(pattern):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    violations.append(f"{path}:{token}")
            if "tvly-" in text and "tvly-YOUR_API_KEY" not in text:
                violations.append(f"{path}:non-placeholder tvly token")

    assert violations == []


def _web_search_requests_contain_key(session: Any) -> bool:
    runs = list(session.scalars(select(WebSearchRun).where(WebSearchRun.provider == "tavily")))
    return any("unit-test-key" in str(run.request_json) for run in runs)
