"""Content-addressed blob store on the local filesystem."""

from __future__ import annotations

import hashlib
from pathlib import Path

from autoskill.config import get_settings


class ContentStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (get_settings().data_dir / "store" / "objects")

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def put(self, data: bytes) -> str:
        digest = self.digest(data)
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return digest

    def get(self, digest: str) -> bytes:
        return self._path(digest).read_bytes()

    def exists(self, digest: str) -> bool:
        return self._path(digest).exists()

    def delete(self, digest: str) -> None:
        path = self._path(digest)
        if path.exists():
            path.unlink()


_store: ContentStore | None = None


def get_content_store() -> ContentStore:
    global _store
    if _store is None:
        _store = ContentStore()
    return _store


def reset_content_store() -> None:
    global _store
    _store = None
