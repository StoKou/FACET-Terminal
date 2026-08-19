from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import time
from typing import Any, Callable, Generic, TypeVar

from common.progress import ProgressBar


T = TypeVar("T")


class BatchRunner(Generic[T]):
    def __init__(self, label: str, workers: int, batch_size: int, max_inflight_batches: int, total: int) -> None:
        self.label = label
        self.batch_size = max(1, batch_size)
        self.max_inflight = max(1, self.batch_size * max_inflight_batches)
        self.executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix=label.replace(":", "-"))
        self.futures: dict[Future[dict[str, Any]], T] = {}
        self.results: list[dict[str, Any]] = []
        self.progress = ProgressBar(label, total)

    def __enter__(self) -> "BatchRunner[T]":
        self.progress.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.executor.shutdown(wait=True)
        self.progress.__exit__(exc_type, exc, tb)

    def submit_batch(self, items: list[T], worker: Callable[[T], dict[str, Any]]) -> None:
        for item in items:
            self.futures[self.executor.submit(worker, item)] = item

    def at_capacity(self) -> bool:
        return len(self.futures) >= self.max_inflight

    def drain_ready(self) -> list[dict[str, Any]]:
        ready = [future for future in self.futures if future.done()]
        rows: list[dict[str, Any]] = []
        for future in ready:
            item = self.futures.pop(future)
            row = future.result()
            self.results.append(row)
            rows.append(row)
            self.progress.update(suffix=item_label(item))
        return rows

    def wait_one(self) -> list[dict[str, Any]]:
        while True:
            rows = self.drain_ready()
            if rows:
                return rows
            time.sleep(0.2)

    def drain_all(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while self.futures:
            rows.extend(self.wait_one())
        return rows


def run_batched(
    label: str,
    items: list[T],
    workers: int,
    batch_size: int,
    max_inflight_batches: int,
    worker: Callable[[T], dict[str, Any]],
) -> list[dict[str, Any]]:
    with BatchRunner(label, workers, batch_size, max_inflight_batches, len(items)) as runner:
        cursor = 0
        while cursor < len(items) or runner.futures:
            while cursor < len(items) and not runner.at_capacity():
                batch = items[cursor : cursor + runner.batch_size]
                runner.submit_batch(batch, worker)
                cursor += len(batch)
            if not runner.drain_ready() and runner.futures:
                time.sleep(0.2)
        runner.drain_all()
        return runner.results


def item_label(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("task_id") or item.get("task_name") or item.get("pair_id") or "")
    if isinstance(item, Path):
        return item.name
    return str(item)
