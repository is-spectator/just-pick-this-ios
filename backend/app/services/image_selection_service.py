from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ImageAsset
from app.retrieval.tavily_service import TavilyService, extract_domain


TRUSTED_IMAGE_DOMAINS = [
    "waveshare.com",
    "amazon.com",
    "wikipedia.org",
    "wikimedia.org",
    "visitkorea.or.kr",
    "oliveyoung.com",
    "tripadvisor.com",
    "ctrip.com",
    "c-ctrip.com",
    "pixnet.net",
    "pimg.tw",
    "trip.com",
    "tripcdn.com",
    "anise.tw",
    "pishop.us",
    "pishop.ca",
    "core-electronics.com.au",
    "unsplash.com",
]

AI_IMAGE_DOMAINS = [
    "civitai.com",
    "playground.com",
    "playgroundai.com",
    "leonardo.ai",
    "midjourney.com",
    "lexica.art",
]

AI_IMAGE_KEYWORDS = [
    "ai-generated",
    "ai_generated",
    "midjourney",
    "stable-diffusion",
    "stablediffusion",
    "dalle",
    "dall-e",
    "flux",
    "leonardo",
    "playground",
    "civitai",
]


class ImageSelectionService:
    def __init__(
        self,
        session: Session,
        *,
        tavily_service: TavilyService | None = None,
        trusted_domains: Iterable[str] | None = None,
    ) -> None:
        self.session = session
        self.tavily_service = tavily_service or TavilyService(session)
        self.trusted_domains = [domain.lower() for domain in (trusted_domains or TRUSTED_IMAGE_DOMAINS)]

    async def find_best_card_image(
        self,
        *,
        query: str,
        place_key: str | None = None,
        item_key: str | None = None,
        preferred_domains: list[str] | None = None,
        allow_tavily: bool = True,
    ) -> ImageAsset | None:
        return self.find_best_card_image_sync(
            query=query,
            place_key=place_key,
            item_key=item_key,
            preferred_domains=preferred_domains,
            allow_tavily=allow_tavily,
        )

    def find_best_card_image_sync(
        self,
        *,
        query: str,
        place_key: str | None = None,
        item_key: str | None = None,
        preferred_domains: list[str] | None = None,
        allow_tavily: bool = True,
    ) -> ImageAsset | None:
        existing = self._find_existing_displayable(place_key=place_key, item_key=item_key)
        if existing is not None:
            return existing

        if not allow_tavily:
            return None

        image_max_results = int(getattr(self.tavily_service.settings, "tavily_image_max_results", 8))
        result = self.tavily_service.search_images_sync(query, max_results=image_max_results)
        for image in result.images:
            self._score_and_mark_candidate(image, preferred_domains=preferred_domains)
        self.session.flush()

        return self._best_displayable_from_candidates(result.images)

    def _find_existing_displayable(self, *, place_key: str | None, item_key: str | None) -> ImageAsset | None:
        if not place_key and not item_key:
            return None

        conditions = [
            ImageAsset.verification_status == "verified",
            ImageAsset.is_ai_generated.is_(False),
            ImageAsset.displayable.is_(True),
        ]
        matchers = []
        if place_key:
            matchers.append(ImageAsset.place_key == place_key)
        if item_key:
            matchers.append(ImageAsset.item_key == item_key)
        if matchers:
            conditions.append(or_(*matchers))

        return self.session.scalar(
            select(ImageAsset)
            .where(*conditions)
            .order_by(ImageAsset.created_at.asc())
            .limit(1)
        )

    def _score_and_mark_candidate(
        self,
        image: ImageAsset,
        *,
        preferred_domains: list[str] | None,
    ) -> None:
        source_domain = image.source_domain or extract_domain(image.source_url) or extract_domain(image.url)
        image.source_domain = source_domain
        if not image.source_url:
            image.source_url = image.url

        risk = self._ai_generated_risk(image)
        image.ai_generated_risk = risk
        image.is_ai_generated = risk == "high"

        if (
            image.url
            and image.source_url
            and source_domain
            and risk == "low"
            and not self._is_blacklisted_domain(source_domain)
            and self._is_trusted_domain(source_domain, preferred_domains=preferred_domains)
        ):
            image.verification_status = "verified"
            image.verified = True
            image.displayable = True
            return

        image.verification_status = "candidate"
        image.verified = False
        image.displayable = False

    def _best_displayable_from_candidates(self, images: list[ImageAsset]) -> ImageAsset | None:
        displayable = [
            image
            for image in images
            if image.displayable
            and image.verification_status == "verified"
            and not image.is_ai_generated
        ]
        if not displayable:
            return None
        return displayable[0]

    def _ai_generated_risk(self, image: ImageAsset) -> str:
        searchable = " ".join(
            str(value or "").lower()
            for value in (
                image.url,
                image.source_url,
                image.source_domain,
                image.alt_text,
                (image.metadata_json or {}).get("description"),
            )
        )
        if any(keyword in searchable for keyword in AI_IMAGE_KEYWORDS):
            return "high"
        if not image.source_url or not image.source_domain:
            return "unknown"
        return "low"

    def _is_blacklisted_domain(self, domain: str) -> bool:
        return _domain_matches(domain, AI_IMAGE_DOMAINS)

    def _is_trusted_domain(self, domain: str, *, preferred_domains: list[str] | None) -> bool:
        trusted = [*self.trusted_domains, *(preferred_domains or [])]
        return _domain_matches(domain, trusted)


def _domain_matches(domain: str, candidates: Iterable[str]) -> bool:
    normalized = domain.lower().removeprefix("www.")
    for candidate in candidates:
        candidate = candidate.lower().removeprefix("www.")
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            return True
    return False
