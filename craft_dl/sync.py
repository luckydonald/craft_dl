import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx

from craft_dl import git_ops
from craft_dl.backup_refs import backup_refs
from craft_dl.chain import Selector
from craft_dl.filtering import CliMode, matching_selectors, missing_releases, select_assets, unmatched_selectors, wants_latest
from craft_dl.github import ORG, ReleaseSource
from craft_dl.models import Dl, ReleaseInfo
from craft_dl.progress import Bars
from craft_dl.releases import CONCURRENT_DOWNLOADS, ensure_releases_dir, link_latest, sync_release
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
    selectors: dict[str, list[Selector]] = field(default_factory=dict)
    cli_mode: CliMode = CliMode.both
# end class


@dataclass
class Listing:
    releases: list[ReleaseInfo] = field(default_factory=list)
    latest_tag: str | None = None
    complete: bool = True
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
            logger.info("%s: cloning %s", name, url)
            await git_ops.clone(url, path, ctx.bars.git_progress)
        elif not (path / ".git").exists():
            logger.info("%s: %s is not a git repository yet, initializing it and fetching %s", name, path, url)
            await git_ops.init_and_fetch(url, path, ctx.bars.git_progress)
        else:
            logger.info("%s: fetching all remotes and tags (forced, no prune)", name)
            await git_ops.fetch_all(path, ctx.bars.git_progress)
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
        logger.info("%s: backing up new or changed branch/tag tips under bak/", name)
        result = await backup_refs(path, ctx.clock(), ctx.bars.step_progress)
        logger.info("%s: created %d backup ref(s)", name, result.created)
        for message in result.errors:
            ctx.errors.add(name, Dl.repo, "backup refs", message)
        # end for
    except git_ops.GitError as error:
        ctx.errors.add(name, Dl.repo, "backup refs", error)
    # end try
    ctx.bars.work_done()
# end def


async def fetch_latest(name: str, ctx: Context, report: bool = True) -> ReleaseInfo | None:
    """Without `report` a failure (e.g. a repo without any release) is only logged: nobody asked for `latest` explicitly."""
    assert ctx.source is not None
    logger.info("%s: fetching the latest release from the GitHub API…", name)
    try:
        return await ctx.source.latest_release(name)
    except Exception as error:
        if report:
            ctx.errors.add(name, Dl.release, "latest release", error)
        else:
            logger.info("%s: no latest release (%s)", name, error)
        # end if
        return None
    # end try
# end def


async def list_all_releases(name: str, ctx: Context, want_latest: bool) -> Listing:
    """All releases, or at least `latest` if listing them fails."""
    assert ctx.source is not None
    listing = Listing()
    latest = await fetch_latest(name, ctx, report=want_latest)
    logger.info("%s: listing releases from the GitHub API…", name)
    try:
        async for release in ctx.source.list_releases(name):
            listing.releases.append(release)
        # end for
    except Exception as error:  # githubkit raises its own exception hierarchy on top of httpx's
        listing.complete = False
        ctx.errors.add(name, Dl.release, "list releases", error)
        if latest is None and not want_latest:
            latest = await fetch_latest(name, ctx, report=True)
        # end if
        if latest is not None and all(r.tag != latest.tag for r in listing.releases):
            listing.releases.append(latest)
        # end if
    # end try
    listing.latest_tag = latest.tag if latest is not None else None
    return listing
# end def


def filter_releases(name: str, listing: Listing, ctx: Context) -> list[ReleaseInfo]:
    """Drops releases no selector asks for and reduces the others to the wanted assets."""
    selectors = ctx.selectors.get(name, [])
    if listing.complete:
        for value in missing_releases(selectors, [r.tag for r in listing.releases], listing.latest_tag):
            ctx.errors.add(name, Dl.release, "select release", f"release {value!r} not found")
        # end for
    # end if
    chosen: list[ReleaseInfo] = []
    for release in listing.releases:
        matched = matching_selectors(selectors, release.tag, listing.latest_tag)
        if selectors and not matched:
            continue
        # end if
        for selector in unmatched_selectors(matched, release.assets):
            logger.warning("%s %s: no asset matches platform=%s variant=%s", name, release.tag, selector.platforms or "*", selector.variants or "*")
        # end for
        chosen.append(replace(release, assets=select_assets(matched, release.assets, ctx.cli_mode)))
    # end for
    return chosen
# end def


async def sync_releases(name: str, ctx: Context) -> None:
    root: Path | None = None
    try:
        root = ensure_releases_dir(ctx.repo_dir / name)
    except OSError as error:
        ctx.errors.add(name, Dl.release, "_releases_ setup", error)
    # end try
    ctx.bars.work_done()
    if root is not None:
        logger.info("%s: saving releases into %s", name, root)
    # end if
    if ctx.source is None or ctx.http is None or root is None:
        ctx.bars.work_done()
        return
    # end if
    listing = await list_all_releases(name, ctx, wants_latest(ctx.selectors.get(name, [])))
    releases = filter_releases(name, listing, ctx)
    logger.info("%s: %d of %d release(s) selected", name, len(releases), len(listing.releases))
    ctx.bars.work_done()
    await asyncio.gather(*(
        sync_release(name, release, root, ctx.http, ctx.errors, ctx.semaphore, ctx.bars.add_work, ctx.bars.work_done, ctx.bars.file)
        for release in releases
    ))
    if listing.latest_tag is not None:
        try:
            link_latest(root, listing.latest_tag)
        except (OSError, ValueError) as error:
            ctx.errors.add(name, Dl.release, "latest symlink", error)
        # end try
    # end if
# end def


async def sync_repo(name: str, ctx: Context) -> None:
    """`repo` and `release` parts are independent: a failure in one never skips the other."""
    steps = (2 if Dl.repo in ctx.dl else 0) + (2 if Dl.release in ctx.dl else 0)
    logger.info("%s: starting (%s)", name, ", ".join(sorted(d.value for d in ctx.dl)))
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
    apps: Sequence[str], ctx: Context, list_names: Callable[[], Awaitable[list[str]]], chain: Sequence[Selector] = (),
) -> None:
    """If the repo list can't be fetched, still run `git fetch` in the existing checkouts."""
    offline = False
    logger.info("Fetching the repository list from the GitHub API…")
    try:
        names = await list_names()
    except Exception as error:
        ctx.errors.add(None, None, "list repositories", error)
        names = local_repo_names(ctx.repo_dir)
        offline = True
        logger.warning("Repository list unavailable, falling back to the %d local checkout(s) in %s", len(names), ctx.repo_dir)
    # end try
    if offline:
        ctx.dl.discard(Dl.release)
    # end if
    resolved, unresolved = resolve_apps(apps, names)
    logger.info("%d repositor%s selected: %s", len(resolved), "y" if len(resolved) == 1 else "ies", ", ".join(resolved) or "-")
    for app in unresolved:
        ctx.errors.add(None, None, "resolve app", f"no repository matches {app!r}")
    # end for
    for selector in chain:
        for name in resolve_apps(selector.apps, names)[0]:
            ctx.selectors.setdefault(name, []).append(selector)
        # end for
    # end for
    ctx.bars.set_repo_count(len(resolved))
    for name in resolved:
        await sync_repo(name, ctx)
    # end for
# end def
