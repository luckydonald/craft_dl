import re
from collections.abc import Callable
from dataclasses import dataclass, replace

ENUMERATING = "Enumerating objects"
COUNTING = "Counting objects"
COMPRESSING = "Compressing objects"
RECEIVING = "Receiving objects"
RESOLVING = "Resolving deltas"
UPDATING = "Updating files"

# The steps a command goes through, each an equal share of the middle bar (a fetch ends after resolving, only a checkout updates files).
FETCH_PHASES = (ENUMERATING, COUNTING, COMPRESSING, RECEIVING, RESOLVING)
CLONE_PHASES = (*FETCH_PHASES, UPDATING)
CHECKOUT_PHASES = (UPDATING,)

ALIASES = {"Checking out files": UPDATING}
PROGRESS = re.compile(
    r"^(?:remote: )?(?P<phase>Enumerating objects|Counting objects|Compressing objects|Receiving objects|Resolving deltas|Updating files|Checking out files)"
    r":\s+(?:(?P<percent>\d+)% \((?P<done>\d+)/(?P<total>\d+)\)|(?P<count>\d+))(?P<tail>.*)$",
)
RATE = re.compile(r"(\d+(?:\.\d+)? \w+/s)")


@dataclass(frozen=True)
class GitProgress:
    """One progress line of git, placed in the sequence of steps (`index` of `count`) of its command."""

    phase: str
    percent: int | None
    done: int
    total: int | None
    rate: str | None
    finished: bool = False
    index: int = 0
    count: int = 1

    @property
    def phase_fraction(self) -> float:
        """0..1 within this step; the count-only `Enumerating objects` jumps from 0 to 1 when it is done."""
        if self.finished:
            return 1.0
        # end if
        return (self.percent or 0) / 100
    # end def

    @property
    def fraction(self) -> float:
        """0..1 over the whole command, every step an equal share."""
        return (self.index + self.phase_fraction) / self.count
    # end def

    @property
    def detail(self) -> str:
        counts = f"{self.done}/{self.total}" if self.total is not None else str(self.done)
        return f"{counts}" + (f" · {self.rate}" if self.rate else "")
    # end def
# end class


GitProgressCallback = Callable[[GitProgress], None]


def parse_progress(line: str, phases: tuple[str, ...] = FETCH_PHASES) -> GitProgress | None:
    """`Receiving objects:  45% (390/866), 1.20 MiB | 3.92 MiB/s` -> step, percent, counts and rate; `None` for other lines or steps."""
    found = PROGRESS.match(line.strip())
    if found is None:
        return None
    # end if
    phase = ALIASES.get(found.group("phase"), found.group("phase"))
    if phase not in phases:
        return None
    # end if
    tail = found.group("tail")
    rate = RATE.search(tail)
    progress = GitProgress(
        phase, None, int(found.group("count") or 0), None, None, finished="done" in tail, index=phases.index(phase), count=len(phases),
    )
    if found.group("percent") is not None:
        progress = replace(
            progress, percent=int(found.group("percent")), done=int(found.group("done")), total=int(found.group("total")),
            rate=rate.group(1) if rate else None,
        )
    # end if
    return progress
# end def
