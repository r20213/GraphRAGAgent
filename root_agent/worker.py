"""Background ingestion worker for Root Agent memory events."""

from __future__ import annotations

import json
import signal
from dataclasses import dataclass

from .config import MEMORY_QUEUE_NAME, REDIS_URL
from .memory import RootMemoryStore

PROCESSING_QUEUE_NAME = f"{MEMORY_QUEUE_NAME}:processing"


@dataclass(slots=True)
class WorkerConfig:
    batch_size: int = 50
    idle_timeout: int = 5


class MemoryWorker:
    def __init__(self, config: WorkerConfig | None = None) -> None:
        self.config = config or WorkerConfig()
        self.store = RootMemoryStore()
        self._stopped = False

    def stop(self, *_args) -> None:
        self._stopped = True

    def run(self) -> None:
        self._install_signal_handlers()
        import asyncio

        asyncio.run(self.store.ensure_schema())
        self.store._redis_client()
        print(f"Root Agent worker listening on {MEMORY_QUEUE_NAME} ({REDIS_URL}).")
        while not self._stopped:
            batch = self._pull_batch()
            if not batch:
                continue
            try:
                count = asyncio.run(
                    self.store.persist_batch(
                        [item[1] for item in batch]
                    )
                )
                self._ack_batch(batch)
                print(f"Flushed {count} memory events to Neon.")
            except Exception as exc:  # noqa: BLE001 - worker must keep running
                print(f"Worker flush failed: {exc}")

    def _pull_batch(self) -> list[tuple[str, dict]]:
        client = self.store._redis_client()
        batch: list[tuple[str, dict]] = []
        item = client.brpoplpush(
            MEMORY_QUEUE_NAME,
            PROCESSING_QUEUE_NAME,
            timeout=self.config.idle_timeout,
        )
        if not item:
            return batch
        batch.append((item, json.loads(item)))
        while len(batch) < self.config.batch_size:
            item = client.rpoplpush(MEMORY_QUEUE_NAME, PROCESSING_QUEUE_NAME)
            if item is None:
                break
            batch.append((item, json.loads(item)))
        return batch

    def _ack_batch(self, batch: list[tuple[str, dict]]) -> None:
        client = self.store._redis_client()
        for raw_item, _parsed_item in batch:
            client.lrem(PROCESSING_QUEUE_NAME, 1, raw_item)

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)


def main() -> None:
    MemoryWorker().run()


if __name__ == "__main__":
    main()
