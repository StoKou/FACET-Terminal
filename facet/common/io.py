from __future__ import annotations

import json
import math
import os
import struct
import threading
import tomllib
from pathlib import Path
from typing import Any, Iterable

from .hashing import file_hash


_APPEND_LOCK = threading.Lock()


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return load_toml(path)
    if suffix in {".yaml", ".yml"}:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            payload = yaml.safe_load(f)
        return payload or {}
    raise ValueError(f"unsupported config format: {path}")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return list(iter_jsonl(path))


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, ensure_ascii=False, sort_keys=True)
            f.write("\n")
            count += 1
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return count


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK:
        with path.open("a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, sort_keys=True)
            f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def jsonl_hash(path: Path) -> str:
    return file_hash(path) if path.exists() else "sha256:" + "0" * 64


def write_npy_float32(path: Path, matrix: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    header = {
        "descr": "<f4",
        "fortran_order": False,
        "shape": (rows, cols),
    }
    header_text = repr(header)
    header_len = len(header_text) + 1
    pad_len = 16 - ((10 + header_len) % 16)
    header_bytes = (header_text + " " * pad_len + "\n").encode("latin1")
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(b"\x93NUMPY")
        f.write(bytes([1, 0]))
        f.write(struct.pack("<H", len(header_bytes)))
        f.write(header_bytes)
        for row in matrix:
            if len(row) != cols:
                raise ValueError("ragged matrix cannot be written as .npy")
            for value in row:
                if not math.isfinite(float(value)):
                    raise ValueError("non-finite embedding value")
                f.write(struct.pack("<f", float(value)))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
