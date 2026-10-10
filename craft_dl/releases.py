import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx

from craft_dl.models import AssetInfo, Dl, ReleaseInfo
from craft_dl.progress import FileTracker
from craft_dl.report import ErrorCollector
from craft_dl.store import LATEST_LINK, RELEASES_DIR, Store, link_latest, release_dir, safe_relative  # noqa: F401 (re-exported)
from craft_dl.webdav import WebdavError

logger = logging.getLogger(__name__)

CONCURRENT_DOWNLOADS = 4


async def ensure_releases_dir(store: Store) -> None:
    """Create `_releases_` (with parents) and its ignore-everything `.gitignore`, without failing if they exist."""
    await store.mkdirs(RELEASES_DIR)
    gitignore = f"{RELEASES_DIR}/.gitignore"
    if await store.exists_size(gitignore) is None:
        await store.write_text(gitignore, "*\n")
    # end if
# end def


async def write_readme(store: Store, directory: str, release: ReleaseInfo) -> None:
    await store.mkdirs(directory)
    await store.write_text(f"{directory}/README.md", f"# {release.name}\n\n{release.body}\n")
# end def


async def download_asset(
    http: httpx.AsyncClient, asset: AssetInfo, store: Store, directory: str, open_file: Callable[[str, int], FileTracker] | None = None,
) -> bool:
    """Returns `False` if skipped because an identical-size file exists. Never leaves a truncated file at the final name."""
    if Path(asset.name).name != asset.name:
        raise ValueError(f"unsafe asset name {asset.name!r}")
    # end if
    target = f"{directory}/{asset.name}" if directory else asset.name
    if await store.exists_size(target) == asset.size:
        logger.info("%s: already downloaded", asset.name)
        return False
    # end if
    logger.info("%s: downloading %.1f MiB", asset.name, asset.size / 1024 / 1024)
    tracker = open_file(asset.name, asset.size) if open_file is not None else None

    async def chunks(response: httpx.Response) -> AsyncIterator[bytes]:
        async for chunk in response.aiter_bytes():
            if tracker is not None:
                tracker.advance(len(chunk))
            # end if
            yield chunk
        # end for
    # end def

    try:
        async with http.stream("GET", asset.url) as response:
            response.raise_for_status()
            await store.write_stream(target, chunks(response), asset.size)
        # end with
    finally:
        if tracker is not None:
            tracker.close()
        # end if
    # end try
    return True
# end def


async def sync_release(
    repo: str, release: ReleaseInfo, store: Store, http: httpx.AsyncClient, errors: ErrorCollector,
    semaphore: asyncio.Semaphore, add_work: Callable[[int], None], work_done: Callable[[int], None],
    open_file: Callable[[str, int], FileTracker] | None = None,
) -> None:
    add_work(1 + len(release.assets))
    logger.info("%s %s: writing README.md, %d asset(s) to download", repo, release.tag, len(release.assets))
    try:
        directory = f"{RELEASES_DIR}/{safe_relative(release.tag)}"
        await write_readme(store, directory, release)
    except (OSError, ValueError, WebdavError, httpx.HTTPError) as error:
        errors.add(repo, Dl.release, f"release {release.tag}", error)
        work_done(1 + len(release.assets))
        return
    # end try
    work_done(1)

    async def fetch(asset: AssetInfo) -> None:
        async with semaphore:
            try:
                if await download_asset(http, asset, store, directory, open_file):
                    logger.info("%s %s: downloaded %s", repo, release.tag, asset.name)
                # end if
            except (httpx.HTTPError, OSError, ValueError, WebdavError) as error:
                errors.add(repo, Dl.release, f"asset {release.tag}/{asset.name}", error)
            # end try
            work_done(1)
        # end with
    # end def

    await asyncio.gather(*(fetch(asset) for asset in release.assets))
# end def
