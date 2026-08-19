from __future__ import annotations

import sys
import time
from typing import Iterable, Iterator, TypeVar


T = TypeVar("T")


class ProgressBar:
    def __init__(self, label: str, total: int | None = None, width: int = 28, min_interval: float = 0.25) -> None:
        self.label = label
        self.total = total if total is not None and total >= 0 else None
        self.width = width
        self.min_interval = min_interval
        self.current = 0
        self.started = time.monotonic()
        self.last_render = 0.0
        self.closed = False
        self.is_tty = sys.stderr.isatty()

    def __enter__(self) -> "ProgressBar":
        self.render(force=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            if self.total is not None and self.current < self.total:
                self.current = self.total
            self.close("done")
        else:
            self.close("failed")

    def update(self, step: int = 1, suffix: str = "") -> None:
        self.current += step
        self.render(suffix=suffix)

    def set(self, current: int, suffix: str = "") -> None:
        self.current = current
        self.render(suffix=suffix)

    def render(self, suffix: str = "", force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_render < self.min_interval:
            return
        self.last_render = now
        elapsed = now - self.started
        if self.total:
            done = min(self.current, self.total)
            ratio = done / self.total
            filled = int(self.width * ratio)
            bar = "#" * filled + "-" * (self.width - filled)
            rate = done / elapsed if elapsed > 0 else 0.0
            msg = f"{self.label} [{bar}] {done}/{self.total} {ratio:6.1%} {rate:,.1f}/s elapsed {elapsed:,.1f}s"
        else:
            msg = f"{self.label} {self.current} elapsed {elapsed:,.1f}s"
        if suffix:
            msg += f" {suffix}"
        if self.is_tty:
            sys.stderr.write("\r" + msg)
            sys.stderr.flush()
        else:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()

    def close(self, status: str = "done") -> None:
        if self.closed:
            return
        self.closed = True
        self.render(force=True, suffix=status)
        if self.is_tty:
            sys.stderr.write("\n")
            sys.stderr.flush()


def progress_iter(items: Iterable[T], label: str, total: int | None = None) -> Iterator[T]:
    if total is None:
        try:
            total = len(items)  # type: ignore[arg-type]
        except TypeError:
            total = None
    with ProgressBar(label, total) as progress:
        for item in items:
            yield item
            progress.update()
