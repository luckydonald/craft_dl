from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn


class Bars:
    """Two bars: overall (repos) and in-repo (steps and release assets)."""

    def __init__(self, console: Console | None = None, enabled: bool = True) -> None:
        self.progress = Progress(
            TextColumn("{task.description:<28}"), BarColumn(), TaskProgressColumn(), TimeElapsedColumn(), TextColumn("{task.fields[detail]}"),
            console=console, disable=not enabled,
        )
        self.overall: TaskID = self.progress.add_task("all repositories", total=0, detail="")
        self.current: TaskID = self.progress.add_task("-", total=0, visible=False, detail="")
        self.done = 0
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
        self.done += count
        self.progress.update(self.current, completed=self.done, detail="")
    # end def

    def step_progress(self, fraction: float, detail: str = "") -> None:
        """Partial progress (0..1) of the step in flight, e.g. a running `git fetch`."""
        self.progress.update(self.current, completed=self.done + min(max(fraction, 0.0), 0.99), detail=detail)
    # end def

    def finish_repo(self) -> None:
        self.progress.advance(self.overall)
    # end def
# end class
