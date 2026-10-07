"""Content-addressed raw payload retention (`raw_ref`).

Every payload a source returns is stored byte-for-byte under its sha256 *before* it is
normalized, so an Item can always be traced (and re-normalized) from what the source
actually said. Writes are immutable: an existing object is never overwritten. The file
layout mirrors Agent 04's artifact store so the directory can be handed over as-is.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

from .ids import sha256_ref


class RawStoreError(Exception):
    pass


class RawStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, raw_ref: str) -> bytes: ...
    def exists(self, raw_ref: str) -> bool: ...


class MemoryRawStore:
    def __init__(self) -> None:
        self._objs: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        ref = sha256_ref(data)
        self._objs.setdefault(ref, bytes(data))
        return ref

    def get(self, raw_ref: str) -> bytes:
        try:
            return self._objs[raw_ref]
        except KeyError:
            raise RawStoreError(f"unknown raw_ref {raw_ref}") from None

    def exists(self, raw_ref: str) -> bool:
        return raw_ref in self._objs

    def __len__(self) -> int:
        return len(self._objs)


class FileRawStore:
    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)

    def _path(self, raw_ref: str) -> Path:
        if not raw_ref.startswith("sha256:") or len(raw_ref) != 71:
            raise RawStoreError(f"malformed raw_ref {raw_ref!r}")
        hexd = raw_ref[7:]
        return self.root / "sha256" / hexd[:2] / hexd[2:4] / hexd

    def put(self, data: bytes) -> str:
        ref = sha256_ref(data)
        path = self._path(ref)
        if path.exists():
            return ref
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            os.chmod(path, 0o444)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return ref

    def get(self, raw_ref: str) -> bytes:
        path = self._path(raw_ref)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise RawStoreError(f"unknown raw_ref {raw_ref}") from None
        if sha256_ref(data) != raw_ref:
            raise RawStoreError(f"raw object {raw_ref} failed hash verification")
        return data

    def exists(self, raw_ref: str) -> bool:
        return self._path(raw_ref).exists()
