"""Filesystem artifact store (D-07): sha256 content-addressed, insert-only, indexed in mbos.artifacts.

Layout: <root>/sha256/ab/cd/<64 hex>. Files are written atomically (temp + fsync + rename + dir fsync) and
made read-only; a file that already exists is verified, never overwritten. Every read re-hashes the bytes,
so a tampered or truncated file is detected, never returned. Inline (bytea) artifacts from
mbos.put_artifact() are read through the same API.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import psycopg


class ArtifactError(Exception):
    pass


class ArtifactTampered(ArtifactError):
    pass


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def rel_path(sha: str) -> str:
    h = sha.removeprefix("sha256:")
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise ArtifactError(f"not a sha256 address: {sha!r}")
    return f"sha256/{h[:2]}/{h[2:4]}/{h}"


def default_root() -> Path:
    return Path(os.environ.get("MBOS_ARTIFACT_ROOT", Path.home() / ".local/share/mbos/artifacts"))


@dataclass
class ArtifactStore:
    conn: psycopg.Connection
    root: Path

    def _file(self, sha: str) -> Path:
        return self.root / rel_path(sha)

    def put(self, data: bytes, media_type: str) -> str:
        sha = sha256_hex(data)
        path = self._file(sha)
        if path.exists():
            self._check_file(sha, path)          # identical content already stored; verify, never overwrite
        else:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(prefix=".tmp.", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(tmp, 0o444)
                os.replace(tmp, path)
                dfd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        self.conn.execute("SELECT mbos.register_artifact(%s, %s, %s)", (sha, media_type, len(data)))
        return sha

    def get(self, sha: str) -> bytes:
        row = self.conn.execute("SELECT storage, location, content, byte_size FROM mbos.artifacts WHERE sha256 = %s",
                                (sha,)).fetchone()
        if row is None:
            raise ArtifactError(f"{sha} is not indexed")
        storage, location, content, size = row
        if storage == "inline":
            data = bytes(content)
        elif storage == "fs":
            if location != rel_path(sha):
                raise ArtifactTampered(f"{sha}: index location {location!r} is not its canonical path")
            data = self._check_file(sha, self.root / location)
        else:
            raise ArtifactError(f"{sha}: storage {storage!r} not supported by this store")
        if sha256_hex(data) != sha or len(data) != size:
            raise ArtifactTampered(f"{sha}: content does not match its address")
        return data

    @staticmethod
    def _check_file(sha: str, path: Path) -> bytes:
        try:
            data = path.read_bytes()
        except FileNotFoundError as e:
            raise ArtifactTampered(f"{sha}: file missing at {path}") from e
        if sha256_hex(data) != sha:
            raise ArtifactTampered(f"{sha}: file content was modified ({path})")
        return data

    def verify_all(self) -> list[str]:
        """Re-hash every indexed artifact. Returns problems (empty = intact). Also reports unindexed files."""
        problems: list[str] = []
        indexed = set()
        for (sha,) in self.conn.execute("SELECT sha256 FROM mbos.artifacts ORDER BY created_at, sha256").fetchall():
            indexed.add(rel_path(sha))
            try:
                self.get(sha)
            except ArtifactError as e:
                problems.append(str(e))
        base = self.root / "sha256"
        if base.exists():
            for f in base.rglob("*"):
                if f.is_file() and not f.name.startswith(".tmp.") and str(f.relative_to(self.root)) not in indexed:
                    problems.append(f"unindexed file {f.relative_to(self.root)}")
        return problems
