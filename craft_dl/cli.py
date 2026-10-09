import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.logging import RichHandler

from craft_dl.chain import ChainError, Selector, chain_apps, parse_chain
from craft_dl.filtering import CliMode, parse_cli_mode
from craft_dl.github import GitHubClient
from craft_dl.models import Dl
from craft_dl.progress import Bars
from craft_dl.report import ErrorCollector
from craft_dl.selection import is_wildcard, split_values
from craft_dl.sync import Context, run
from craft_dl.token import resolve_token

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


def parse_filters(tokens: Sequence[str], dl_cli: str) -> tuple[list[Selector], CliMode]:
    try:
        return parse_chain(tokens), parse_cli_mode(dl_cli)
    except (ChainError, ValueError) as error:
        raise SystemExit(str(error)) from error
    # end try
# end def


async def download_async(
    dl: set[Dl], chain: list[Selector], cli_mode: CliMode, repo_dir: Path, github_token: str | None,
) -> int:
    console = Console(stderr=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler(console=console, show_path=False)])
    errors = ErrorCollector()
    token = await resolve_token(github_token)
    client = GitHubClient(token)
    with Bars(console) as bars:
        async with client.http_client() as http:
            ctx = Context(repo_dir=repo_dir, dl=dl, errors=errors, bars=bars, source=client, http=http, cli_mode=cli_mode)
            await run(chain_apps(chain), ctx, client.list_org_repos, chain)
        # end with
    # end with
    extra_args = [] if cli_mode is CliMode.both else [f"--dl-cli={cli_mode.value}"]
    print(errors.render(ctx.selectors, extra_args))
    return 1 if errors.failures else 0
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
    repo_dir: Annotated[Path, Parameter(help="Where the repositories live.")] = DEFAULT_REPO_DIR,
    github_token: Annotated[str | None, Parameter(help="Overrides `gh auth token` and `$GITHUB_TOKEN`.")] = None,
    tokens: Annotated[Sequence[str] | None, Parameter(parse=False)] = None,
) -> int:
    """Clone/fetch the repositories, back up every branch/tag tip, and save the releases.

    `--app`, `--release`, `--platform` and `--variant` form a chain in this order of scope: a new option keeps the levels above it and resets the ones below,
    e.g. `--app=art --release=latest --platform=win --variant=msi --platform=mac --app=photo --variant=dmg`.
    """
    chain, cli_mode = parse_filters(sys.argv[1:] if tokens is None else tokens, dl_cli)
    return asyncio.run(download_async(parse_dl(dl), chain, cli_mode, repo_dir.expanduser(), github_token))
# end def


def main() -> None:
    result = cli()
    sys.exit(result if isinstance(result, int) else 0)
# end def
