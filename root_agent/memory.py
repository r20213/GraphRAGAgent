"""Neon + Redis memory store for the Root Agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import (
    LESSONS_TABLE,
    MEMORY_QUEUE_MAX_LENGTH,
    MEMORY_QUEUE_NAME,
    MEMORY_TOP_K,
    MEMORY_VECTOR_DIMENSION,
    NEON_DATABASE_URL,
    REDIS_URL,
    SESSION_STATE_PREFIX,
    SESSION_TTL_SECONDS,
)


@dataclass(slots=True)
class Lesson:
    query_text: str
    assistant_text: str
    route: str
    intent: str
    similarity: float
    notes: str


class RootMemoryStore:
    """Short-term Redis session state plus long-term Neon memory."""

    def __init__(self) -> None:
        self._redis = None

    def _redis_client(self):
        if self._redis is None:
            import redis

            self._redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    @staticmethod
    def _hash_embedding(text: str, dimension: int = MEMORY_VECTOR_DIMENSION) -> list[float]:
        vector = [0.0] * dimension
        tokens = [token for token in text.lower().split() if token]
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for index in range(dimension):
                vector[index] += (digest[index % len(digest)] / 255.0) - 0.5
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [round(value / norm, 8) for value in vector]

    @property
    def embedding_dimension(self) -> int:
        return MEMORY_VECTOR_DIMENSION

    async def ensure_schema(self) -> None:
        if not NEON_DATABASE_URL:
            return
        await asyncio.to_thread(self._ensure_schema_sync)

    def _ensure_schema_sync(self) -> None:
        import psycopg

        with psycopg.connect(NEON_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {LESSONS_TABLE} (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        session_id TEXT NOT NULL,
                        user_id TEXT,
                        route TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        query_text TEXT NOT NULL,
                        assistant_text TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding vector({self.embedding_dimension}) NOT NULL
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {LESSONS_TABLE}_embedding_idx
                    ON {LESSONS_TABLE}
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                    """
                )
            conn.commit()

    async def search_lessons(self, query_text: str, limit: int = MEMORY_TOP_K) -> list[Lesson]:
        if not NEON_DATABASE_URL:
            return []
        return await asyncio.to_thread(self._search_lessons_sync, query_text, limit)

    def _search_lessons_sync(self, query_text: str, limit: int) -> list[Lesson]:
        import psycopg
        from pgvector.psycopg import register_vector

        embedding = self._hash_embedding(query_text)
        with psycopg.connect(NEON_DATABASE_URL) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT query_text,
                           assistant_text,
                           route,
                           intent,
                           1 - (embedding <=> %s) AS similarity,
                           COALESCE(metadata->>'notes', '') AS notes
                    FROM {LESSONS_TABLE}
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (embedding, embedding, limit),
                )
                rows = cur.fetchall()
        return [
            Lesson(
                query_text=row[0],
                assistant_text=row[1],
                route=row[2],
                intent=row[3],
                similarity=float(row[4]),
                notes=row[5],
            )
            for row in rows
        ]

    async def enqueue_memory_event(self, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(self._enqueue_memory_event_sync, payload)

    def _enqueue_memory_event_sync(self, payload: dict[str, Any]) -> None:
        client = self._redis_client()
        client.lpush(MEMORY_QUEUE_NAME, json.dumps(payload, ensure_ascii=False))
        client.ltrim(MEMORY_QUEUE_NAME, 0, MEMORY_QUEUE_MAX_LENGTH - 1)

    async def load_session_state(self, session_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._load_session_state_sync, session_id)

    def _load_session_state_sync(self, session_id: str) -> dict[str, Any]:
        client = self._redis_client()
        raw = client.get(self._session_key(session_id))
        if not raw:
            return {"session_id": session_id, "turns": []}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"session_id": session_id, "turns": []}

    async def save_session_state(
        self,
        session_id: str,
        state: dict[str, Any],
    ) -> None:
        await asyncio.to_thread(self._save_session_state_sync, session_id, state)

    def _save_session_state_sync(
        self,
        session_id: str,
        state: dict[str, Any],
    ) -> None:
        client = self._redis_client()
        client.set(
            self._session_key(session_id),
            json.dumps(state, ensure_ascii=False),
            ex=SESSION_TTL_SECONDS,
        )

    def _session_key(self, session_id: str) -> str:
        return f"{SESSION_STATE_PREFIX}:{session_id}"

    async def persist_batch(self, events: list[dict[str, Any]]) -> int:
        if not events or not NEON_DATABASE_URL:
            return 0
        return await asyncio.to_thread(self._persist_batch_sync, events)

    def _persist_batch_sync(self, events: list[dict[str, Any]]) -> int:
        import psycopg
        from pgvector.psycopg import register_vector

        rows = []
        for event in events:
            rows.append(
                (
                    event["session_id"],
                    event.get("user_id"),
                    event["route"],
                    event["intent"],
                    event["query_text"],
                    event["assistant_text"],
                    json.dumps(event.get("payload", {}), ensure_ascii=False),
                    json.dumps(event.get("metadata", {}), ensure_ascii=False),
                    event["embedding"],
                )
            )

        with psycopg.connect(NEON_DATABASE_URL) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {LESSONS_TABLE} (
                        session_id,
                        user_id,
                        route,
                        intent,
                        query_text,
                        assistant_text,
                        payload,
                        metadata,
                        embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                    """,
                    rows,
                )
            conn.commit()
        return len(rows)

    def build_event_payload(
        self,
        *,
        session_id: str,
        user_id: str | None,
        route: str,
        intent: str,
        query_text: str,
        assistant_text: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user_id": user_id,
            "route": route,
            "intent": intent,
            "query_text": query_text,
            "assistant_text": assistant_text,
            "payload": payload,
            "metadata": metadata or {},
            "embedding": self._hash_embedding(query_text),
        }
