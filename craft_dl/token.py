import asyncio
import os
from collections.abc import Mapping


async def gh_cli_token() -> str | None:
    """Token of the logged-in `gh` CLI, or `None` if `gh` is missing or not logged in."""
    try:
        process = await asyncio.create_subprocess_exec(
            "gh", "auth", "token",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    # end try
    stdout, _ = await process.communicate()
    token = stdout.decode().strip()
    if process.returncode != 0 or not token:
        return None
    # end if
    return token
# end def


async def resolve_token(flag: str | None, environ: Mapping[str, str] | None = None) -> str | None:
    """`--github-token`, then `gh auth token`, then `$GITHUB_TOKEN`, else unauthenticated."""
    if flag:
        return flag
    # end if
    token = await gh_cli_token()
    if token:
        return token
    # end if
    env = os.environ if environ is None else environ
    return env.get("GITHUB_TOKEN") or None
# end def
