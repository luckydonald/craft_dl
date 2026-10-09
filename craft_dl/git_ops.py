import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
PROGRESS = re.compile(
    r"^(?:remote: )?(?P<phase>Enumerating objects|Counting objects|Compressing objects|Receiving objects|Resolving deltas|Updating files|Checking out files)"
    r":\s+(?:(?P<percent>\d+)% \((?P<done>\d+)/(?P<total>\d+)\)|(?P<count>\d+))(?P<tail>.*)$",
)
RATE = re.compile(r"(\d+(?:\.\d+)? \w+/s)")
# Share of the whole run each git phase stands for, so one monotonic fraction can drive a bar (a fetch ends after resolving deltas).
PHASES: dict[str, tuple[float, float]] = {
    "Enumerating objects": (0.0, 0.0),
    "Counting objects": (0.0, 0.05),
    "Compressing objects": (0.05, 0.1),
    "Receiving objects": (0.1, 0.7),
    "Resolving deltas": (0.7, 0.9),
    "Updating files": (0.9, 1.0),
    "Checking out files": (0.9, 1.0),
}


@dataclass(frozen=True)
class GitProgress:
    phase: str
    percent: int | None
    done: int
    total: int | None
    rate: str | None

    @property
    def fraction(self) -> float:
        start, end = PHASES[self.phase]
        return start + (end - start) * (self.percent or 0) / 100
    # end def

    @property
    def detail(self) -> str:
        counts = f"{self.done}/{self.total}" if self.total is not None else str(self.done)
        return f"{self.phase} {counts}" + (f" · {self.rate}" if self.rate else "")
    # end def
# end class


class GitError(Exception):
    def __init__(self, args_: tuple[str, ...], returncode: int, stderr: str) -> None:
        super().__init__(f"git {' '.join(args_)} failed ({returncode}): {stderr.strip()}")
        self.returncode = returncode
        self.stderr = stderr
    # end def
# end class


def parse_progress(line: str) -> GitProgress | None:
    """`Receiving objects:  45% (390/866), 1.20 MiB | 3.92 MiB/s` -> phase, percent, counts and rate."""
    found = PROGRESS.match(line.strip())
    if found is None:
        return None
    # end if
    rate = RATE.search(found.group("tail"))
    if found.group("percent") is None:
        return GitProgress(found.group("phase"), None, int(found.group("count")), None, None)
    # end if
    return GitProgress(
        found.group("phase"), int(found.group("percent")), int(found.group("done")), int(found.group("total")), rate.group(1) if rate else None,
    )
# end def


async def read_stderr(stream: asyncio.StreamReader, label: str, on_progress: ProgressCallback | None) -> str:
    """Collects stderr; `\\r` ends an in-flight progress update (fed to the bar), `\\n` ends a line (logged)."""
    collected: list[str] = []
    buffer = ""
    best = 0.0

    def handle(segment: str, final: bool) -> None:
        nonlocal best
        segment = segment.strip()
        if not segment:
            return
        # end if
        progress = parse_progress(segment)
        if progress is not None and on_progress is not None:
            best = max(best, progress.fraction)
            on_progress(best, progress.detail)
        # end if
        if final:
            logger.info("%s: %s", label, segment)
        # end if
    # end def

    while chunk := await stream.read(4096):
        text = chunk.decode(errors="replace")
        collected.append(text)
        buffer += text
        while (match := re.search(r"[\r\n]", buffer)) is not None:
            handle(buffer[:match.start()], final=match.group() == "\n")
            buffer = buffer[match.end():]
        # end while
    # end while
    handle(buffer, final=True)
    return "".join(collected)
# end def


async def run_git(
    *args: str, cwd: Path | None = None, quiet: bool = False, on_progress: ProgressCallback | None = None, stdin: str | None = None,
) -> str:
    """Runs git, logging the command line and its output (`quiet` for chatty plumbing commands)."""
    label = f"git {args[0]}"
    logger.log(logging.DEBUG if quiet else logging.INFO, "$ git %s%s", " ".join(args), f"  (in {cwd})" if cwd else "")
    process = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    if stdin is not None:
        assert process.stdin is not None
        process.stdin.write(stdin.encode())
        process.stdin.close()
    # end if
    stderr_task = asyncio.create_task(drain(process.stderr) if quiet else read_stderr(process.stderr, label, on_progress))
    stdout = (await process.stdout.read()).decode(errors="replace")
    stderr = await stderr_task
    await process.wait()
    if process.returncode != 0:
        raise GitError(args, process.returncode or -1, stderr)
    # end if
    if not quiet:
        for line in stdout.splitlines():
            logger.info("%s: %s", label, line)
        # end for
    # end if
    return stdout
# end def


async def drain(stream: asyncio.StreamReader) -> str:
    return (await stream.read()).decode(errors="replace")
# end def


async def clone(url: str, path: Path, on_progress: ProgressCallback | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await run_git("clone", "--progress", url, str(path), on_progress=on_progress)
# end def


async def init_and_fetch(url: str, path: Path, on_progress: ProgressCallback | None = None) -> None:
    """For a directory that exists (e.g. only holds `_releases_`) but isn't a git repo yet; `git clone` refuses those."""
    await run_git("init", cwd=path)
    await run_git("remote", "add", "origin", url, cwd=path)
    await fetch_all(path, on_progress)
    await run_git("remote", "set-head", "origin", "--auto", cwd=path)
    head = (await run_git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=path, quiet=True)).strip()
    branch = head.removeprefix("origin/")
    await run_git("checkout", "--progress", "-B", branch, head, cwd=path, on_progress=on_progress)
# end def


async def fetch_all(path: Path, on_progress: ProgressCallback | None = None) -> None:
    """Forced, including tags; deliberately no `--prune`, so upstream deletions stay recoverable."""
    await run_git("fetch", "--all", "--tags", "--force", "--progress", cwd=path, on_progress=on_progress)
# end def


async def update_ref(path: Path, ref: str, sha: str) -> None:
    await run_git("update-ref", ref, sha, cwd=path, quiet=True)
# end def


async def update_refs(path: Path, updates: list[tuple[str, str]]) -> None:
    """Many refs in one git process and one transaction (thousands of single `update-ref` processes take minutes)."""
    script = "".join(f"update {ref} {sha}\n" for ref, sha in updates)
    await run_git("update-ref", "--stdin", cwd=path, quiet=True, stdin=script)
# end def
