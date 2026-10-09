import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

import httpx

from craft_dl.models import AssetInfo, Dl, ReleaseInfo
from craft_dl.report import ErrorCollector

logger = logging.getLogger(__name__)

RELEASES_DIR = "_releases_"
CONCURRENT_DOWNLOADS = 4


def ensure_releases_dir(repo_path: Path) -> Path:
    """Create `_releases_` (with parents) and its ignore-everything `.gitignore`, without failing if they exist."""
    root = repo_path / RELEASES_DIR
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    # end if
    return root
# end def


def release_dir(root: Path, tag: str) -> Path:
    path = (root / tag).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"unsafe release tag {tag!r}")
    # end if
    return path
# end def


def write_readme(directory: Path, release: ReleaseInfo) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text(f"# {release.name}\n\n{release.body}\n")
# end def


async def download_asset(http: httpx.AsyncClient, asset: AssetInfo, directory: Path) -> bool:
    """Returns `False` if skipped because an identical-size file exists. Never leaves a truncated file at the final name."""
    if Path(asset.name).name != asset.name:
        raise ValueError(f"unsafe asset name {asset.name!r}")
    # end if
    target = directory / asset.name
    if target.exists() and target.stat().st_size == asset.size:
        return False
    # end if
    partial = target.with_name(target.name + ".part")
    try:
        async with http.stream("GET", asset.url) as response:
            response.raise_for_status()
            with partial.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    file.write(chunk)
                # end for
            # end with
        # end with
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    # end try
    return True
# end def


async def sync_release(
    repo: str, release: ReleaseInfo, root: Path, http: httpx.AsyncClient, errors: ErrorCollector,
    semaphore: asyncio.Semaphore, add_work: Callable[[int], None], work_done: Callable[[int], None],
) -> None:
    add_work(1 + len(release.assets))
    try:
        directory = release_dir(root, release.tag)
        write_readme(directory, release)
    except (OSError, ValueError) as error:
        errors.add(repo, Dl.release, f"release {release.tag}", error)
        work_done(1 + len(release.assets))
        return
    # end try
    work_done(1)

    async def fetch(asset: AssetInfo) -> None:
        async with semaphore:
            try:
                if await download_asset(http, asset, directory):
                    logger.info("%s %s: downloaded %s", repo, release.tag, asset.name)
                # end if
            except (httpx.HTTPError, OSError, ValueError) as error:
                errors.add(repo, Dl.release, f"asset {release.tag}/{asset.name}", error)
            # end try
            work_done(1)
        # end with
    # end def

    await asyncio.gather(*(fetch(asset) for asset in release.assets))
# end def
