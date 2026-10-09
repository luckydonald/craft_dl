import asyncio
from pathlib import Path


class GitError(Exception):
    def __init__(self, args_: tuple[str, ...], returncode: int, stderr: str) -> None:
        super().__init__(f"git {' '.join(args_)} failed ({returncode}): {stderr.strip()}")
        self.returncode = returncode
        self.stderr = stderr
    # end def
# end class


async def run_git(*args: str, cwd: Path | None = None) -> str:
    process = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise GitError(args, process.returncode or -1, stderr.decode(errors="replace"))
    # end if
    return stdout.decode(errors="replace")
# end def


async def clone(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await run_git("clone", url, str(path))
# end def


async def init_and_fetch(url: str, path: Path) -> None:
    """For a directory that exists (e.g. only holds `_releases_`) but isn't a git repo yet; `git clone` refuses those."""
    await run_git("init", cwd=path)
    await run_git("remote", "add", "origin", url, cwd=path)
    await fetch_all(path)
    await run_git("remote", "set-head", "origin", "--auto", cwd=path)
    head = (await run_git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=path)).strip()
    branch = head.removeprefix("origin/")
    await run_git("checkout", "-B", branch, head, cwd=path)
# end def


async def fetch_all(path: Path) -> None:
    """Forced, including tags; deliberately no `--prune`, so upstream deletions stay recoverable."""
    await run_git("fetch", "--all", "--tags", "--force", cwd=path)
# end def


async def update_ref(path: Path, ref: str, sha: str) -> None:
    await run_git("update-ref", ref, sha, cwd=path)
# end def
