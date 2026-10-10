import asyncio
import logging
import shlex
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.logging import RichHandler

from craft_dl import smb, webdav
from craft_dl.chain import ChainError, Selector, chain_apps, parse_chain
from craft_dl.filtering import CliMode, parse_cli_mode
from craft_dl.github import GitHubClient
from craft_dl.models import Dl
from craft_dl.progress import Bars
from craft_dl.report import ErrorCollector
from craft_dl.selection import is_wildcard, split_values
from craft_dl.store import Store
from craft_dl.sync import Context, run
from craft_dl.token import resolve_token

logger = logging.getLogger(__name__)

cli = App(name="craft_dl", help="Archive the storytold/*craft repositories: git history plus release assets.")

DEFAULT_REPO_DIR = Path("~/git/storytold/")


def parse_dl(values: list[str]) -> set[Dl]:
    names = split_values(values)
    if not names or any(is_wildcard(name) or name.lower() == "both" for name in names):
        return set(Dl)
    # end if
    try:
        return {Dl(name) for name in names}
    except ValueError as error:
        raise SystemExit(f"invalid --dl value ({error}), expected one of: {', '.join(d.value for d in Dl)}") from error
    # end try
# end def


def dir_args(tokens: Sequence[str]) -> list[str]:
    """`--repo-dir`/`--download-dir` exactly as typed (a `Path` would collapse `smb://` and `webdavs://`), for the retry commands."""
    found: dict[str, str] = {}
    for index, token in enumerate(tokens):
        name, equals, value = token.partition("=")
        if name not in ("--repo-dir", "--download-dir"):
            continue
        # end if
        if not equals and index + 1 < len(tokens):
            value = tokens[index + 1]
        # end if
        found[name] = value
    # end for
    return [f"{name}={shlex.quote(value)}" for name, value in found.items()]
# end def


def setup_logging() -> Console:
    console = Console(stderr=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler(console=console, show_path=False)])
    return console
# end def


def parse_filters(tokens: Sequence[str], dl_cli: str) -> tuple[list[Selector], CliMode]:
    try:
        return parse_chain(tokens), parse_cli_mode(dl_cli)
    except (ChainError, ValueError) as error:
        raise SystemExit(str(error)) from error
    # end try
# end def


async def download_async(
    dl: set[Dl], chain: list[Selector], cli_mode: CliMode, repo_dir: Path, download_dir: Path | webdav.WebdavLocation | None,
    github_token: str | None, console: Console, retry_args: Sequence[str] = (),
) -> int:
    errors = ErrorCollector()
    logger.info("Resolving the GitHub token (--github-token, gh auth token, $GITHUB_TOKEN)…")
    token = await resolve_token(github_token)
    logger.info("Using %s", "an API token" if token else "no API token (rate limits apply)")
    client = GitHubClient(token)
    async with AsyncExitStack() as stack:
        if isinstance(download_dir, webdav.WebdavLocation):
            dav = await stack.enter_async_context(download_dir.client())  # dedicated client: its credentials must not go to GitHub
            target: Path | Store | None = webdav.WebdavStore(download_dir.base_url, dav)
        else:
            target = download_dir
        # end if
        with Bars(console) as bars:
            async with client.http_client() as http:
                ctx = Context(repo_dir=repo_dir, dl=dl, errors=errors, bars=bars, source=client, http=http, cli_mode=cli_mode, download_dir=target)
                await run(chain_apps(chain), ctx, client.list_org_repos, chain)
            # end with
        # end with
    # end async with
    extra_args = [*retry_args, *([] if cli_mode is CliMode.both else [f"--dl-cli={cli_mode.value}"])]
    print(errors.render(ctx.selectors, extra_args))
    return 1 if errors.failures else 0
# end def


def resolve_dir(path: Path, option: str, *, allow_webdav: bool) -> Path | webdav.WebdavLocation:
    path = path.expanduser()
    if smb.has_protocol(path):
        try:
            return smb.mount(path)
        except smb.SmbError as error:
            raise SystemExit(str(error)) from error
        # end try
    # end if
    if webdav.has_protocol(path):
        if not allow_webdav:
            raise SystemExit(f"invalid {option}: git needs a local directory, use --download-dir for webdav")
        # end if
        try:
            return webdav.parse(path)
        except webdav.WebdavError as error:
            raise SystemExit(f"invalid {option}: {error}") from error
        # end try
    # end if
    return path
# end def


@cli.default
@cli.command
def download(
    *,
    dl: Annotated[list[str], Parameter(help="What to download: `repo`, `release`. Comma-separated or repeated; default: all.")] = [],
    app: Annotated[list[str], Parameter(help="Which apps: `photo` (suffix `craft` implied, else bare name), `*` (default), `**` (all repos).")] = [],
    release: Annotated[list[str], Parameter(help="Only these releases (`v0.41.0`, `0.41.0`, `latest`) of the preceding `--app`; default: all.")] = [],
    platform: Annotated[list[str], Parameter(help="Only this platform of the preceding `--release`: `win`, `mac` (`apple`, `macos`), `linux`, `freebsd`. `win-x64-setup` adds variants.")] = [],
    variant: Annotated[list[str], Parameter(help="Only these variants (`msi`, `dmg`, `x64`, `aarch64`, `m1`, `portable`, `x64-setup`, …), alternatives; dashes combine.")] = [],
    dl_cli: Annotated[str, Parameter(help="Assets containing `-cli-`: `both` (default), `app` (skip them), `cli-only`. Also `yes/no/only`, `ja/nein/nur`, `1/0/-1`.")] = "both",
    repo_dir: Annotated[Path, Parameter(help="Where the git repositories live; `smb://<server>/<mount>/<dir>` is mounted first (macOS).")] = DEFAULT_REPO_DIR,
    download_dir: Annotated[Path | None, Parameter(help="Where the releases go, default: `--repo-dir`. Also `smb://…`, or `webdavs://<user>:<password>@<host>/<dir>` (percent-escaped), read/written directly.")] = None,
    github_token: Annotated[str | None, Parameter(help="Overrides `gh auth token` and `$GITHUB_TOKEN`.")] = None,
    tokens: Annotated[Sequence[str] | None, Parameter(parse=False)] = None,
) -> int:
    """Clone/fetch the repositories, back up every branch/tag tip, and save the releases.

    `--app`, `--release`, `--platform` and `--variant` form a chain in this order of scope: a new option keeps the levels above it and resets the ones below,
    e.g. `--app=art --release=latest --platform=win --variant=msi --platform=mac --app=photo --variant=dmg`.
    """
    arguments = sys.argv[1:] if tokens is None else tokens
    chain, cli_mode = parse_filters(arguments, dl_cli)
    console = setup_logging()
    local_repo_dir = resolve_dir(repo_dir, "--repo-dir", allow_webdav=False)
    assert isinstance(local_repo_dir, Path)
    target = None if download_dir is None else resolve_dir(download_dir, "--download-dir", allow_webdav=True)
    return asyncio.run(download_async(parse_dl(dl), chain, cli_mode, local_repo_dir, target, github_token, console, dir_args(arguments)))
# end def


def main() -> None:
    result = cli()
    sys.exit(result if isinstance(result, int) else 0)
# end def
