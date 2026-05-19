from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.tools.session import SessionLike, execute, first_mapping


class RetrievalLogger:
    def __init__(
        self,
        db: SessionLike,
        *,
        agent_run_id: str,
        turn_id: str | None = None,
        source: str = "local_sql",
    ) -> None:
        self.db = db
        self.agent_run_id = agent_run_id
        self.turn_id = turn_id
        self.source = source

    async def start_run(
        self,
        *,
        query: str,
        question_id: str | None = None,
        user_id: str | None = None,
        limit: int,
    ) -> str:
        run_id = str(uuid4())
        result = await execute(
            self.db,
            """
            INSERT INTO retrieval_runs (
                id,
                agent_run_id,
                turn_id,
                query,
                source,
                status,
                top_k,
                filters_json,
                metadata_json,
                started_at,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :agent_run_id,
                :turn_id,
                :query,
                :source,
                'running',
                :limit,
                CAST(:filters_json AS JSONB),
                CAST(:metadata_json AS JSONB),
                NOW(),
                NOW(),
                NOW()
            )
            RETURNING id
            """,
            {
                "id": run_id,
                "agent_run_id": self.agent_run_id,
                "turn_id": self.turn_id,
                "query": query,
                "source": self.source,
                "limit": limit,
                "filters_json": json.dumps(
                    {"question_id": question_id, "user_id": user_id},
                    ensure_ascii=False,
                ),
                "metadata_json": json.dumps({}, ensure_ascii=False),
            },
        )
        row = first_mapping(result)
        return str(row["id"]) if row else run_id

    async def log_hit(
        self,
        *,
        retrieval_run_id: str,
        rank: int,
        hit_type: str,
        source_id: str,
        score: float,
        payload: dict[str, Any],
    ) -> str:
        hit_id = str(uuid4())
        result = await execute(
            self.db,
            """
            INSERT INTO retrieval_hits (
                id,
                retrieval_run_id,
                rank,
                score,
                source_type,
                source_id,
                title,
                snippet,
                payload_json,
                created_at
            )
            VALUES (
                :id,
                :retrieval_run_id,
                :rank,
                :score,
                :hit_type,
                :source_id,
                :title,
                :snippet,
                CAST(:payload_json AS JSONB),
                NOW()
            )
            RETURNING id
            """,
            {
                "id": hit_id,
                "retrieval_run_id": retrieval_run_id,
                "rank": rank,
                "hit_type": hit_type,
                "source_id": source_id,
                "score": score,
                "title": payload.get("title"),
                "snippet": payload.get("text"),
                "payload_json": json.dumps(payload, ensure_ascii=False),
            },
        )
        row = first_mapping(result)
        return str(row["id"]) if row else hit_id

    async def finish_run(
        self,
        *,
        retrieval_run_id: str,
        status: str,
        hit_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        await execute(
            self.db,
            """
            UPDATE retrieval_runs
            SET status = :status,
                metadata_json = CAST(:metadata_json AS JSONB),
                finished_at = NOW(),
                updated_at = NOW()
            WHERE id = :retrieval_run_id
            """,
            {
                "retrieval_run_id": retrieval_run_id,
                "status": status,
                "metadata_json": json.dumps(
                    {"hit_count": hit_count, "error_message": error_message},
                    ensure_ascii=False,
                ),
            },
        )
