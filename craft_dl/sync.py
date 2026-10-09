import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from craft_dl import git_ops
from craft_dl.backup_refs import backup_refs
from craft_dl.github import ORG, ReleaseSource
from craft_dl.models import Dl, ReleaseInfo
from craft_dl.progress import Bars
from craft_dl.releases import CONCURRENT_DOWNLOADS, ensure_releases_dir, sync_release
from craft_dl.report import ErrorCollector
from craft_dl.selection import resolve_apps

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)
# end def


@dataclass
class Context:
    repo_dir: Path
    dl: set[Dl]
    errors: ErrorCollector
    bars: Bars
    source: ReleaseSource | None = None
    http: httpx.AsyncClient | None = None
    clock: Callable[[], datetime] = utc_now
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(CONCURRENT_DOWNLOADS))
# end class


def local_repo_names(repo_dir: Path) -> list[str]:
    if not repo_dir.is_dir():
        return []
    # end if
    return sorted(path.name for path in repo_dir.iterdir() if (path / ".git").exists())
# end def


async def sync_git(name: str, ctx: Context) -> None:
    path = ctx.repo_dir / name
    url = f"https://github.com/{ORG}/{name}.git"
    try:
        if not path.exists():
            await git_ops.clone(url, path)
        elif not (path / ".git").exists():
            await git_ops.init_and_fetch(url, path)
        else:
            await git_ops.fetch_all(path)
        # end if
    except (git_ops.GitError, OSError) as error:
        ctx.errors.add(name, Dl.repo, "clone/fetch", error)
    # end try
    ctx.bars.work_done()
    if not (path / ".git").exists():
        ctx.bars.work_done()
        return
    # end if
    try:
        result = await backup_refs(path, ctx.clock())
        logger.info("%s: created %d backup ref(s)", name, result.created)
        for message in result.errors:
            ctx.errors.add(name, Dl.repo, "backup refs", message)
        # end for
    except git_ops.GitError as error:
        ctx.errors.add(name, Dl.repo, "backup refs", error)
    # end try
    ctx.bars.work_done()
# end def


async def list_all_releases(name: str, ctx: Context) -> list[ReleaseInfo]:
    """All releases, or at least `latest` if listing them fails."""
    assert ctx.source is not None
    releases: list[ReleaseInfo] = []
    try:
        async for release in ctx.source.list_releases(name):
            releases.append(release)
        # end for
    except Exception as error:  # githubkit raises its own exception hierarchy on top of httpx's
        ctx.errors.add(name, Dl.release, "list releases", error)
        try:
            latest = await ctx.source.latest_release(name)
            if all(r.tag != latest.tag for r in releases):
                releases.append(latest)
            # end if
        except Exception as latest_error:
            ctx.errors.add(name, Dl.release, "latest release", latest_error)
        # end try
    # end try
    return releases
# end def


async def sync_releases(name: str, ctx: Context) -> None:
    root: Path | None = None
    try:
        root = ensure_releases_dir(ctx.repo_dir / name)
    except OSError as error:
        ctx.errors.add(name, Dl.release, "_releases_ setup", error)
    # end try
    ctx.bars.work_done()
    if ctx.source is None or ctx.http is None or root is None:
        ctx.bars.work_done()
        return
    # end if
    releases = await list_all_releases(name, ctx)
    ctx.bars.work_done()
    await asyncio.gather(*(
        sync_release(name, release, root, ctx.http, ctx.errors, ctx.semaphore, ctx.bars.add_work, ctx.bars.work_done)
        for release in releases
    ))
# end def


async def sync_repo(name: str, ctx: Context) -> None:
    """`repo` and `release` parts are independent: a failure in one never skips the other."""
    steps = (2 if Dl.repo in ctx.dl else 0) + (2 if Dl.release in ctx.dl else 0)
    ctx.bars.start_repo(name, steps)
    if Dl.repo in ctx.dl:
        await sync_git(name, ctx)
    # end if
    if Dl.release in ctx.dl:
        await sync_releases(name, ctx)
    # end if
    ctx.bars.finish_repo()
# end def


async def run(
    apps: Sequence[str], ctx: Context, list_names: Callable[[], Awaitable[list[str]]],
) -> None:
    """If the repo list can't be fetched, still run `git fetch` in the existing checkouts."""
    offline = False
    try:
        names = await list_names()
    except Exception as error:
        ctx.errors.add(None, None, "list repositories", error)
        names = local_repo_names(ctx.repo_dir)
        offline = True
    # end try
    if offline:
        ctx.dl.discard(Dl.release)
    # end if
    resolved, unresolved = resolve_apps(apps, names)
    for app in unresolved:
        ctx.errors.add(None, None, "resolve app", f"no repository matches {app!r}")
    # end for
    ctx.bars.set_repo_count(len(resolved))
    for name in resolved:
        await sync_repo(name, ctx)
    # end for
# end def
