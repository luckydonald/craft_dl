import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

RELEASES_DIR = "_releases_"
LATEST_LINK = "latest"


def safe_relative(path: str) -> str:
    """Rejects anything that could leave the store root (`..`, absolute paths, backslashes, empty segments)."""
    if not path or "\\" in path or any(segment in ("", ".", "..") for segment in path.split("/")):
        raise ValueError(f"unsafe path {path!r}")
    # end if
    return path
# end def


class Store(Protocol):
    """Where release data goes: a local directory or a WebDAV collection. Paths are relative, `/`-separated."""

    @property
    def location(self) -> str: ...

    def sub(self, name: str) -> "Store": ...

    async def exists_size(self, path: str) -> int | None:
        """Size of the file, or `None` if it doesn't exist."""
        ...

    async def mkdirs(self, path: str) -> None: ...

    async def write_text(self, path: str, text: str) -> None: ...

    async def write_stream(self, path: str, chunks: AsyncIterator[bytes], size: int) -> None:
        """Never leaves a truncated file at the final name."""
        ...

    async def read(self, path: str, start: int = 0, end: int | None = None) -> bytes:
        """The bytes `[start, end)` of the file."""
        ...

    async def set_latest(self, tag: str) -> bool:
        """Marks `tag` as the latest release; `False` if that was not possible (e.g. a filter excluded the release)."""
        ...
# end class


def release_dir(root: Path, tag: str) -> Path:
    path = (root / tag).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"unsafe release tag {tag!r}")
    # end if
    return path
# end def


def link_latest(root: Path, tag: str) -> bool:
    """Points `_releases_/latest` at the latest release's folder (relative link, replaced atomically).

    Returns `False` if that folder doesn't exist (e.g. a filter excluded it) or `latest` is a real folder we must not touch.
    """
    directory = release_dir(root, tag)
    link = root / LATEST_LINK
    if not directory.is_dir():
        return False
    # end if
    if link.exists() and not link.is_symlink():
        logger.warning("%s is a real directory, not touching it", link)
        return False
    # end if
    target = os.path.relpath(directory, root.resolve())
    if link.is_symlink() and os.readlink(link) == target:
        return True
    # end if
    temporary = root / f".{LATEST_LINK}.tmp"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(link)
    logger.info("%s -> %s", link, target)
    return True
# end def


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root
    # end def

    @property
    def location(self) -> str:
        return str(self.root)
    # end def

    def sub(self, name: str) -> "LocalStore":
        return LocalStore(self.root / safe_relative(name))
    # end def

    def path(self, path: str) -> Path:
        return self.root / safe_relative(path)
    # end def

    async def exists_size(self, path: str) -> int | None:
        target = self.path(path)
        return target.stat().st_size if target.exists() else None
    # end def

    async def mkdirs(self, path: str) -> None:
        self.path(path).mkdir(parents=True, exist_ok=True)
    # end def

    async def write_text(self, path: str, text: str) -> None:
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    # end def

    async def write_stream(self, path: str, chunks: AsyncIterator[bytes], size: int) -> None:
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        try:
            with partial.open("wb") as file:
                async for chunk in chunks:
                    file.write(chunk)
                # end for
            # end with
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        # end try
    # end def

    async def read(self, path: str, start: int = 0, end: int | None = None) -> bytes:
        with self.path(path).open("rb") as file:
            file.seek(start)
            return file.read() if end is None else file.read(max(end - start, 0))
        # end with
    # end def

    async def set_latest(self, tag: str) -> bool:
        return link_latest(self.root / RELEASES_DIR, tag)
    # end def
# end class
