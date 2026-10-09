import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from rich.console import Console
from rich.progress import BarColumn, Progress, ProgressColumn, Task, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.text import Text

from craft_dl.git_progress import GitProgress

SPEED_WINDOW_SECONDS = 5.0
DETAIL_INTERVAL_SECONDS = 0.25


def human_bytes(count: float) -> str:
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        # end if
        size /= 1024
    # end for
    return f"{size:.2f} GiB"
# end def


class DetailColumn(ProgressColumn):
    """Free text for the repo rows (git phase, aggregate download speed); `x/y · speed` for the per-file rows."""

    def render(self, task: Task) -> Text:
        if task.fields.get("bytes"):
            speed = f" · {human_bytes(task.speed)}/s" if task.speed else ""
            return Text(f"{human_bytes(task.completed)}/{human_bytes(task.total or 0)}{speed}")
        # end if
        return Text(str(task.fields.get("detail", "")))
    # end def
# end class


class FileTracker(Protocol):
    def advance(self, count: int) -> None: ...

    def close(self) -> None: ...
# end class


@dataclass
class FileBar:
    """Progress row of one file being downloaded; removed again when it is done."""

    bars: "Bars"
    task: TaskID

    def advance(self, count: int) -> None:
        self.bars.progress.advance(self.task, count)
        self.bars.record_bytes(count)
    # end def

    def close(self) -> None:
        self.bars.progress.remove_task(self.task)
        self.bars.active_files -= 1
    # end def
# end class


class Bars:
    """Overall (repos), in-repo (steps and release assets), plus one row per file in flight; all with speed/ETA where known."""

    def __init__(self, console: Console | None = None, enabled: bool = True) -> None:
        self.progress = Progress(
            TextColumn("{task.description:<28}"), BarColumn(), TaskProgressColumn(), TimeElapsedColumn(), TimeRemainingColumn(), DetailColumn(),
            console=console, disable=not enabled,
        )
        self.overall: TaskID = self.progress.add_task("all repositories", total=0, detail="")
        self.current: TaskID = self.progress.add_task("-", total=0, visible=False, detail="")
        self.done = 0
        self.git_tasks: tuple[TaskID, TaskID] | None = None
        self.active_files = 0
        self.samples: deque[tuple[float, int]] = deque()
        self.last_detail = 0.0
    # end def

    def __enter__(self) -> "Bars":
        self.progress.start()
        return self
    # end def

    def __exit__(self, *exc: object) -> None:
        self.progress.stop()
    # end def

    def set_repo_count(self, count: int) -> None:
        self.progress.update(self.overall, total=count)
    # end def

    def start_repo(self, name: str, steps: int) -> None:
        self.done = 0
        self.progress.reset(self.current, total=steps, description=name, visible=True, detail="")
    # end def

    def add_work(self, count: int) -> None:
        task = self.progress.tasks[self.current]
        self.progress.update(self.current, total=(task.total or 0) + count)
    # end def

    def work_done(self, count: int = 1) -> None:
        self.git_done()
        self.done += count
        self.progress.update(self.current, completed=self.done, detail="")
    # end def

    def step_progress(self, fraction: float, detail: str = "") -> None:
        """Partial progress (0..1) of the step in flight, e.g. a running `git fetch`."""
        self.progress.update(self.current, completed=self.done + min(max(fraction, 0.0), 0.99), detail=detail)
    # end def

    def git_progress(self, progress: GitProgress) -> None:
        """Two extra rows while git works: its steps (equal shares) and the step in flight (`done/total`, jumping 0 to 100% if unknown)."""
        if self.git_tasks is None:
            self.git_tasks = (
                self.progress.add_task("", total=progress.count, detail=""),
                self.progress.add_task("", total=100, detail=""),
            )
        # end if
        steps, phase = self.git_tasks
        self.progress.update(
            steps, description=f"  git step {progress.index + 1}/{progress.count}", total=progress.count,
            completed=progress.index + progress.phase_fraction,
        )
        total = progress.total if progress.total is not None else (progress.done if progress.finished else 100)
        self.progress.update(
            phase, description=f"    {progress.phase}", total=max(total, 1), completed=progress.done if progress.total is not None or progress.finished else 0,
            detail=progress.detail,
        )
        self.step_progress(progress.fraction)
    # end def

    def git_done(self) -> None:
        if self.git_tasks is not None:
            for task in self.git_tasks:
                self.progress.remove_task(task)
            # end for
            self.git_tasks = None
        # end if
    # end def

    def finish_repo(self) -> None:
        self.progress.advance(self.overall)
    # end def

    def file(self, name: str, total: int) -> FileBar:
        """A row for one download; shows `done/total · speed` and its own ETA."""
        label = name if len(name) <= 25 else "…" + name[-24:]
        self.active_files += 1
        task = self.progress.add_task(f"  {label}", total=total, bytes=True, detail="")
        return FileBar(self, task)
    # end def

    def speed(self, now: float | None = None) -> float:
        """Bytes per second over the last few seconds, over all files in flight."""
        now = time.monotonic() if now is None else now
        while self.samples and now - self.samples[0][0] > SPEED_WINDOW_SECONDS:
            self.samples.popleft()
        # end while
        if not self.samples:
            return 0.0
        # end if
        span = max(now - self.samples[0][0], 1.0)
        return sum(count for _, count in self.samples) / span
    # end def

    def record_bytes(self, count: int, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.samples.append((now, count))
        if now - self.last_detail >= DETAIL_INTERVAL_SECONDS:
            self.last_detail = now
            self.progress.update(self.current, detail=f"{self.active_files} file(s) · {human_bytes(self.speed(now))}/s")
        # end if
    # end def
# end class
