from __future__ import annotations

from app.schemas.tools import KnowledgeHit, SearchKnowledgeInput, SearchKnowledgeOutput
from app.tools.session import SessionLike, all_mappings, commit, execute, rollback

from .retrieval_logger import RetrievalLogger
from .tavily_service import TavilyService


class RetrievalService:
    def __init__(self, db: SessionLike, logger: RetrievalLogger | None = None) -> None:
        self.db = db
        self.logger = logger

    async def search_knowledge(self, input_data: SearchKnowledgeInput) -> SearchKnowledgeOutput:
        retrieval_run_id: str | None = None
        try:
            if self.logger is not None:
                retrieval_run_id = await self.logger.start_run(
                    query=input_data.query,
                    question_id=input_data.question_id,
                    user_id=input_data.user_id,
                    limit=input_data.limit,
                )

            hits = await self._search_hits(input_data)

            if self.logger is not None and retrieval_run_id is not None:
                for index, hit in enumerate(hits, start=1):
                    evidence_id = await self.logger.log_hit(
                        retrieval_run_id=retrieval_run_id,
                        rank=index,
                        hit_type=hit.hit_type,
                        source_id=hit.source_id or hit.id,
                        score=hit.score,
                        payload=hit.model_dump(mode="json"),
                    )
                    hit.evidence_id = evidence_id
                await self.logger.finish_run(
                    retrieval_run_id=retrieval_run_id,
                    status="succeeded",
                    hit_count=len(hits),
                )
            await commit(self.db)
            return SearchKnowledgeOutput(
                query=input_data.query,
                retrieval_run_id=retrieval_run_id,
                hits=hits,
            )
        except Exception as error:
            if self.logger is not None and retrieval_run_id is not None:
                await self.logger.finish_run(
                    retrieval_run_id=retrieval_run_id,
                    status="failed",
                    error_message=str(error),
                )
                await commit(self.db)
            else:
                await rollback(self.db)
            raise

    async def _search_hits(self, input_data: SearchKnowledgeInput) -> list[KnowledgeHit]:
        pattern = f"%{input_data.query.lower()}%"
        image_limit = max(1, input_data.limit // 2)
        answer_limit = max(1, input_data.limit - image_limit)

        image_result = await execute(
            self.db,
            """
            SELECT
                id,
                place_key,
                item_key,
                url,
                source_url,
                credit
            FROM image_assets
            WHERE verified = TRUE
              AND verification_status = 'verified'
              AND displayable = TRUE
              AND is_ai_generated = FALSE
              AND LOWER(
                COALESCE(place_key, '') || ' ' || COALESCE(item_key, '') || ' ' || COALESCE(credit, '')
              ) LIKE :pattern
            ORDER BY created_at ASC
            LIMIT :limit
            """,
            {"pattern": pattern, "limit": image_limit},
        )
        answer_result = await execute(
            self.db,
            """
            SELECT
                id,
                help_card_id,
                raw_text,
                normalized_text
            FROM help_answers
            WHERE status = 'submitted'
              AND LOWER(COALESCE(normalized_text, raw_text, '')) LIKE :pattern
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"pattern": pattern, "limit": answer_limit},
        )

        hits: list[KnowledgeHit] = []
        for row in all_mappings(image_result):
            label = " / ".join(
                str(value) for value in (row.get("placeKey"), row.get("itemKey")) if value
            )
            if not label:
                label = " / ".join(
                    str(value) for value in (row.get("place_key"), row.get("item_key")) if value
                )
            hits.append(
                KnowledgeHit(
                    id=f"image_asset:{row['id']}",
                    hit_type="image_asset",
                    title=label or "Verified image asset",
                    text=label or str(row.get("credit") or row["id"]),
                    score=0.9,
                    source_id=str(row["id"]),
                    image_asset_id=str(row["id"]),
                    metadata={
                        "url": row.get("url"),
                        "source_url": row.get("source_url"),
                        "credit": row.get("credit"),
                    },
                )
            )

        for row in all_mappings(answer_result):
            raw_text = str(row.get("raw_text") or "")
            hits.append(
                KnowledgeHit(
                    id=f"help_answer:{row['id']}",
                    hit_type="help_answer",
                    title="来一句",
                    text=raw_text,
                    score=0.72,
                    source_id=str(row["id"]),
                    metadata={"help_card_id": row.get("help_card_id")},
                )
            )

        if input_data.allow_web and len(hits) < input_data.limit:
            hits.extend(await self._search_web_hits(input_data, remaining=input_data.limit - len(hits)))

        return hits[: input_data.limit]

    async def _search_web_hits(self, input_data: SearchKnowledgeInput, *, remaining: int) -> list[KnowledgeHit]:
        if remaining <= 0:
            return []

        tavily = TavilyService(self.db)  # type: ignore[arg-type]
        hits: list[KnowledgeHit] = []
        text_result = await tavily.search_text(input_data.query, max_results=min(remaining, 5))
        for result in text_result.results[:remaining]:
            hits.append(
                KnowledgeHit(
                    id=f"web_result:{result['id']}",
                    hit_type="web_result",
                    title=result.get("title") or result.get("domain") or "Web result",
                    text=result.get("content") or result.get("url") or "",
                    score=min(max(float(result.get("score") or 0.62), 0.0), 1.0),
                    source_id=result["id"],
                    metadata={
                        "url": result.get("url"),
                        "domain": result.get("domain"),
                        "web_search_run_id": text_result.run_id,
                    },
                )
            )

        if input_data.allow_images and len(hits) < remaining:
            image_result = await tavily.search_images(
                input_data.query,
                max_results=min(remaining - len(hits), 8),
            )
            for image in image_result.images:
                hits.append(
                    KnowledgeHit(
                        id=f"image_asset:{image.id}",
                        hit_type="image_asset",
                        title=image.alt_text or image.source_domain or "Image candidate",
                        text=image.alt_text or image.source_url or image.url,
                        score=0.68 if image.displayable else 0.42,
                        source_id=str(image.id),
                        image_asset_id=str(image.id),
                        metadata={
                            "url": image.url,
                            "source_url": image.source_url,
                            "source_domain": image.source_domain,
                            "displayable": image.displayable,
                            "verification_status": image.verification_status,
                            "web_search_run_id": image_result.run_id,
                        },
                    )
                )
        return hits
