import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.logging import RichHandler

from craft_dl.github import GitHubClient
from craft_dl.models import Dl
from craft_dl.progress import Bars
from craft_dl.report import ErrorCollector
from craft_dl.selection import ALL_DEFAULT, split_values
from craft_dl.sync import Context, run
from craft_dl.token import resolve_token

cli = App(name="craft_dl", help="Archive the storytold/*craft repositories: git history plus release assets.")

DEFAULT_REPO_DIR = Path("~/git/storytold/")


def parse_dl(values: list[str]) -> set[Dl]:
    names = split_values(values)
    if not names:
        return set(Dl)
    # end if
    try:
        return {Dl(name) for name in names}
    except ValueError as error:
        raise SystemExit(f"invalid --dl value ({error}), expected one of: {', '.join(d.value for d in Dl)}") from error
    # end try
# end def


async def download_async(dl: set[Dl], apps: list[str], repo_dir: Path, github_token: str | None) -> int:
    console = Console(stderr=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler(console=console, show_path=False)])
    errors = ErrorCollector()
    token = await resolve_token(github_token)
    client = GitHubClient(token)
    with Bars(console) as bars:
        async with client.http_client() as http:
            ctx = Context(repo_dir=repo_dir, dl=dl, errors=errors, bars=bars, source=client, http=http)
            await run(apps, ctx, client.list_org_repos)
        # end with
    # end with
    print(errors.render())
    return 1 if errors.failures else 0
# end def


@cli.default
@cli.command
def download(
    *,
    dl: Annotated[list[str], Parameter(help="What to download: `repo`, `release`. Comma-separated or repeated; default: all.")] = [],
    app: Annotated[list[str], Parameter(help="Which apps: `photo` (suffix `craft` implied, else bare name), `*` (default), `**` (all repos).")] = [],
    repo_dir: Annotated[Path, Parameter(help="Where the repositories live.")] = DEFAULT_REPO_DIR,
    github_token: Annotated[str | None, Parameter(help="Overrides `gh auth token` and `$GITHUB_TOKEN`.")] = None,
) -> int:
    """Clone/fetch the repositories, back up every branch/tag tip, and save the releases."""
    apps = split_values(app) or [ALL_DEFAULT]
    return asyncio.run(download_async(parse_dl(dl), apps, repo_dir.expanduser(), github_token))
# end def


def main() -> None:
    result = cli()
    sys.exit(result if isinstance(result, int) else 0)
# end def
